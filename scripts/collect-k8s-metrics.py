#!/usr/bin/env python3
"""Collect timestamped Pod, resource, Deployment, and HPA state to one CSV."""

import argparse
import csv
import json
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote


STOP = False


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Destination CSV path")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--selector", default="app=invoice-pdf-api")
    parser.add_argument("--deployment", default="invoice-pdf-api")
    parser.add_argument("--hpa", default="invoice-pdf-api-hpa")
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Stop after this many seconds; 0 means run until Ctrl-C",
    )
    args = parser.parse_args()
    if args.interval <= 0 or args.duration < 0:
        parser.error("--interval must be positive and --duration cannot be negative")
    return args


def kubectl_json(arguments, optional=False):
    result = subprocess.run(
        ["kubectl", *arguments],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if optional and "NotFound" in result.stderr:
            return None
        raise RuntimeError(result.stderr.strip() or "kubectl command failed")
    return json.loads(result.stdout)


def cpu_mcores(quantity):
    if not quantity:
        return None
    if quantity.endswith("n"):
        return float(quantity[:-1]) / 1_000_000
    if quantity.endswith("u"):
        return float(quantity[:-1]) / 1_000
    if quantity.endswith("m"):
        return float(quantity[:-1])
    return float(quantity) * 1000


def memory_mib(quantity):
    if not quantity:
        return None
    suffixes = {
        "Ki": 1 / 1024,
        "Mi": 1,
        "Gi": 1024,
        "K": 1000 / 1024**2,
        "M": 1000**2 / 1024**2,
        "G": 1000**3 / 1024**2,
    }
    for suffix, multiplier in suffixes.items():
        if quantity.endswith(suffix):
            return float(quantity[: -len(suffix)]) * multiplier
    return float(quantity) / 1024**2


def sum_container_usage(containers, resource, parser):
    values = [
        parser(container.get("usage", {}).get(resource))
        for container in containers
    ]
    return sum(value for value in values if value is not None)


def pod_ready(status):
    return any(
        condition.get("type") == "Ready" and condition.get("status") == "True"
        for condition in status.get("conditions", [])
    )


def collect(args):
    selector = quote(args.selector, safe="")
    metrics = kubectl_json(
        [
            "get",
            "--raw",
            f"/apis/metrics.k8s.io/v1beta1/namespaces/{args.namespace}/pods"
            f"?labelSelector={selector}",
        ]
    )
    pods = kubectl_json(
        [
            "get",
            "pods",
            "-n",
            args.namespace,
            "-l",
            args.selector,
            "-o",
            "json",
        ]
    )
    deployment = kubectl_json(
        ["get", "deployment", args.deployment, "-n", args.namespace, "-o", "json"]
    )
    hpa = kubectl_json(
        ["get", "hpa", args.hpa, "-n", args.namespace, "-o", "json"],
        optional=True,
    )

    metric_by_pod = {
        item["metadata"]["name"]: item for item in metrics.get("items", [])
    }
    deployment_status = deployment.get("status", {})
    hpa_status = (hpa or {}).get("status", {})
    current_cpu_utilization = None
    for metric in hpa_status.get("currentMetrics", []):
        resource = metric.get("resource", {})
        if resource.get("name") == "cpu":
            current_cpu_utilization = resource.get("current", {}).get(
                "averageUtilization"
            )

    common = {
        "deployment_desired_replicas": deployment.get("spec", {}).get("replicas"),
        "deployment_ready_replicas": deployment_status.get("readyReplicas", 0),
        "hpa_current_replicas": hpa_status.get("currentReplicas"),
        "hpa_desired_replicas": hpa_status.get("desiredReplicas"),
        "hpa_cpu_utilization_pct": current_cpu_utilization,
    }

    rows = []
    for pod in pods.get("items", []):
        name = pod["metadata"]["name"]
        status = pod.get("status", {})
        container_statuses = status.get("containerStatuses", [])
        pod_metrics = metric_by_pod.get(name, {})
        containers = pod_metrics.get("containers", [])
        rows.append(
            {
                "pod": name,
                "cpu_mcores": sum_container_usage(containers, "cpu", cpu_mcores),
                "memory_mib": sum_container_usage(
                    containers, "memory", memory_mib
                ),
                "ready": int(pod_ready(status)),
                "restart_count": sum(
                    item.get("restartCount", 0) for item in container_statuses
                ),
                "phase": status.get("phase"),
                "node": pod.get("spec", {}).get("nodeName"),
                **common,
            }
        )

    if not rows:
        rows.append(
            {
                "pod": "",
                "cpu_mcores": None,
                "memory_mib": None,
                "ready": 0,
                "restart_count": 0,
                "phase": "",
                "node": "",
                **common,
            }
        )
    return rows


def handle_signal(signum, frame):
    del signum, frame
    global STOP
    STOP = True


def main():
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "timestamp",
        "elapsed_s",
        "pod",
        "cpu_mcores",
        "memory_mib",
        "ready",
        "restart_count",
        "phase",
        "node",
        "deployment_desired_replicas",
        "deployment_ready_replicas",
        "hpa_current_replicas",
        "hpa_desired_replicas",
        "hpa_cpu_utilization_pct",
    ]

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)
    started = time.monotonic()
    next_sample = started

    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        print(f"Collecting Kubernetes metrics into {output}")

        while not STOP:
            elapsed = time.monotonic() - started
            if args.duration and elapsed >= args.duration:
                break

            timestamp = datetime.now(timezone.utc).isoformat()
            try:
                rows = collect(args)
                for row in rows:
                    writer.writerow(
                        {
                            "timestamp": timestamp,
                            "elapsed_s": f"{elapsed:.3f}",
                            **row,
                        }
                    )
                handle.flush()
                total_cpu = sum(
                    row["cpu_mcores"] or 0 for row in rows if row["pod"]
                )
                ready = max(
                    (row["deployment_ready_replicas"] or 0 for row in rows),
                    default=0,
                )
                print(
                    f"{timestamp} pods={len([r for r in rows if r['pod']])} "
                    f"ready={ready} cpu={total_cpu:.1f}m"
                )
            except Exception as error:
                print(f"WARN: {timestamp} {error}", file=sys.stderr)

            next_sample += args.interval
            time.sleep(max(0, next_sample - time.monotonic()))

    print("Collector stopped")


if __name__ == "__main__":
    main()
