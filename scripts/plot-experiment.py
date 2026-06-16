#!/usr/bin/env python3
"""Build knee and synchronized timeline charts from k6 JSON and Kubernetes CSV."""

import argparse
import csv
import json
import math
import shutil
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = {
    "blue": "#2878B5",
    "orange": "#F28E2B",
    "red": "#D9534F",
    "green": "#59A14F",
    "purple": "#AF7AA1",
    "grid": "#D9DEE7",
    "text": "#20242A",
}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--k6", required=True, help="k6 JSON output from --out json=...")
    parser.add_argument("--k8s", required=True, help="CSV from collect-k8s-metrics.py")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--label", default="Experiment")
    parser.add_argument("--window", type=int, default=10)
    parser.add_argument("--http-p95-threshold", type=float, default=550)
    parser.add_argument("--error-threshold", type=float, default=1)
    args = parser.parse_args()
    if args.window <= 0:
        parser.error("--window must be positive")
    return args


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def percentile(values, value):
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(value / 100 * len(ordered)) - 1)
    return ordered[rank]


def read_k6(path):
    points = []
    skipped = 0
    with Path(path).open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            if record.get("type") != "Point":
                continue
            data = record.get("data", {})
            metric = record.get("metric") or data.get("metric")
            time_value = data.get("time")
            value = data.get("value")
            if metric is None or time_value is None or value is None:
                skipped += 1
                continue
            points.append(
                {
                    "metric": metric,
                    "time": timestamp(time_value),
                    "value": float(value),
                    "tags": data.get("tags", {}),
                }
            )
    if not points:
        raise ValueError(
            "The k6 file contains no usable Point records. "
            "Expected JSON output created with: k6 run --out json=FILE"
        )
    if skipped:
        print(f"WARN: skipped {skipped} malformed or incomplete k6 records")
    return points


def optional_number(value):
    if value in ("", None):
        return None
    return float(value)


def read_k8s(path):
    rows = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append(
                {
                    **row,
                    "time": timestamp(row["timestamp"]),
                    "cpu_mcores": optional_number(row["cpu_mcores"]),
                    "ready": optional_number(row["ready"]) or 0,
                    "restart_count": optional_number(row["restart_count"]) or 0,
                    "deployment_ready_replicas": optional_number(
                        row["deployment_ready_replicas"]
                    ),
                    "deployment_desired_replicas": optional_number(
                        row["deployment_desired_replicas"]
                    ),
                    "hpa_desired_replicas": optional_number(
                        row["hpa_desired_replicas"]
                    ),
                }
            )
    return rows


def summarize_levels(points):
    groups = defaultdict(lambda: defaultdict(list))
    for point in points:
        level = point["tags"].get("load_level")
        if level is None:
            continue
        groups[int(level)][point["metric"]].append(point["value"])

    rows = []
    for level in sorted(groups):
        metrics = groups[level]
        durations = (
            metrics["successful_http_req_duration"]
            or metrics["http_req_duration"]
        )
        failures = metrics["http_req_failed"]
        requests = metrics["http_reqs"]
        elapsed = level_elapsed_seconds(points, level)
        rows.append(
            {
                "offered_rps": level,
                "samples": len(durations),
                "achieved_rps": sum(requests) / elapsed if elapsed else None,
                "http_avg_ms": sum(durations) / len(durations) if durations else None,
                "http_p50_ms": percentile(durations, 50),
                "http_p95_ms": percentile(durations, 95),
                "http_p99_ms": percentile(durations, 99),
                "error_rate_pct": (
                    100 * sum(failures) / len(failures) if failures else None
                ),
                "render_p95_ms": percentile(
                    metrics["invoice_processing_time"], 95
                ),
                "dropped_iterations": sum(metrics["dropped_iterations"]),
            }
        )
    return rows


def summarize_phases(points):
    groups = defaultdict(lambda: defaultdict(list))
    offered_rps = {}
    for point in points:
        phase = point["tags"].get("phase")
        level = point["tags"].get("load_level")
        if phase is None or level is None:
            continue
        groups[phase][point["metric"]].append(point["value"])
        offered_rps[phase] = int(level)

    rows = []
    for phase in sorted(groups):
        metrics = groups[phase]
        durations = (
            metrics["successful_http_req_duration"]
            or metrics["http_req_duration"]
        )
        failures = metrics["http_req_failed"]
        requests = metrics["http_reqs"]
        elapsed = phase_elapsed_seconds(points, phase)
        rows.append(
            {
                "phase": phase,
                "offered_rps": offered_rps[phase],
                "samples": len(durations),
                "achieved_rps": sum(requests) / elapsed if elapsed else None,
                "http_avg_ms": sum(durations) / len(durations) if durations else None,
                "http_p50_ms": percentile(durations, 50),
                "http_p95_ms": percentile(durations, 95),
                "http_p99_ms": percentile(durations, 99),
                "error_rate_pct": (
                    100 * sum(failures) / len(failures) if failures else None
                ),
                "render_p95_ms": percentile(
                    metrics["invoice_processing_time"], 95
                ),
                "dropped_iterations": sum(metrics["dropped_iterations"]),
            }
        )
    return rows


def level_elapsed_seconds(points, level):
    times = [
        point["time"]
        for point in points
        if point["tags"].get("load_level") == str(level)
        and point["metric"] in ("http_reqs", "dropped_iterations")
    ]
    if len(times) < 2:
        return None
    return max(times) - min(times) + 1


def phase_elapsed_seconds(points, phase):
    times = [
        point["time"]
        for point in points
        if point["tags"].get("phase") == phase
        and point["metric"] in ("http_reqs", "dropped_iterations")
    ]
    if len(times) < 2:
        return None
    return max(times) - min(times) + 1


def build_timeline(points, k8s_rows, window):
    start = min(point["time"] for point in points)
    end = max(point["time"] for point in points)
    buckets = []
    cursor = start

    while cursor <= end:
        next_cursor = cursor + window
        selected = [
            point for point in points if cursor <= point["time"] < next_cursor
        ]
        successful_durations = [
            point["value"]
            for point in selected
            if point["metric"] == "successful_http_req_duration"
        ]
        durations = successful_durations or [
            point["value"]
            for point in selected
            if point["metric"] == "http_req_duration"
        ]
        requests = [
            point["value"]
            for point in selected
            if point["metric"] == "http_reqs"
        ]
        failures = [
            point["value"]
            for point in selected
            if point["metric"] == "http_req_failed"
        ]
        levels = [
            int(point["tags"]["load_level"])
            for point in selected
            if point["tags"].get("load_level")
        ]
        buckets.append(
            {
                "elapsed_s": cursor - start + window / 2,
                "offered_rps": Counter(levels).most_common(1)[0][0] if levels else 0,
                "achieved_rps": sum(requests) / window,
                "p95_ms": percentile(durations, 95),
                "error_pct": (
                    100 * sum(failures) / len(failures) if failures else 0
                ),
            }
        )
        cursor = next_cursor

    samples = defaultdict(list)
    for row in k8s_rows:
        if start - window <= row["time"] <= end + window:
            samples[row["timestamp"]].append(row)

    k8s_series = []
    previous_restarts = {}
    cumulative_restarts = 0
    ordered_samples = sorted(
        samples.values(),
        key=lambda sample_rows: sample_rows[0]["time"],
    )
    for sample_rows in ordered_samples:
        sample_time = sample_rows[0]["time"]
        hpa_desired = next(
            (
                row["hpa_desired_replicas"]
                for row in sample_rows
                if row["hpa_desired_replicas"] is not None
            ),
            None,
        )
        deployment_desired = next(
            (
                row["deployment_desired_replicas"]
                for row in sample_rows
                if row["deployment_desired_replicas"] is not None
            ),
            None,
        )
        ready = next(
            (
                row["deployment_ready_replicas"]
                for row in sample_rows
                if row["deployment_ready_replicas"] is not None
            ),
            0,
        )
        for row in sample_rows:
            pod = row["pod"]
            if not pod:
                continue
            current = row["restart_count"]
            previous = previous_restarts.get(pod, current)
            if current > previous:
                cumulative_restarts += current - previous
            previous_restarts[pod] = current
        k8s_series.append(
            {
                "elapsed_s": sample_time - start,
                "cpu_mcores": sum(row["cpu_mcores"] or 0 for row in sample_rows),
                "ready_replicas": ready,
                "desired_replicas": (
                    hpa_desired
                    if hpa_desired is not None
                    else deployment_desired if deployment_desired is not None else ready
                ),
                "restarts": cumulative_restarts,
            }
        )
    return buckets, sorted(k8s_series, key=lambda item: item["elapsed_s"])


def write_summary(rows, path, include_phase=False):
    fields = []
    if include_phase:
        fields.append("phase")
    fields.extend([
        "offered_rps",
        "samples",
        "achieved_rps",
        "http_avg_ms",
        "http_p50_ms",
        "http_p95_ms",
        "http_p99_ms",
        "error_rate_pct",
        "render_p95_ms",
        "dropped_iterations",
    ])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def svg_header(width, height):
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        "text { font-family: 'DejaVu Sans', sans-serif; fill: #20242A; }",
        ".title { font-size: 25px; font-weight: 600; }",
        ".axis { font-size: 15px; } .tick { font-size: 13px; }",
        ".note { font-size: 13px; fill: #555B65; }",
        "</style>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]


def text(x, y, value, cls="tick", anchor="start"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" '
        f'text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def line(x1, y1, x2, y2, color=None, width=1, dash=None):
    color = color or COLORS["grid"]
    extra = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="{width}"{extra}/>'
    )


def polyline(points, color, width=3):
    valid = [(x, y) for x, y in points if y is not None]
    coords = " ".join(f"{x:.1f},{y:.1f}" for x, y in valid)
    return (
        f'<polyline points="{coords}" fill="none" stroke="{color}" '
        f'stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>'
    )


def save_svg(parts, path):
    path.write_text("\n".join([*parts, "</svg>"]), encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter:
        subprocess.run(
            [converter, str(path), "-o", str(path.with_suffix(".png"))],
            check=True,
        )


def draw_knee(rows, path, label, p95_threshold, error_threshold):
    width, height = 1400, 1050
    left, right, top, bottom = 105, 1290, 105, 610
    plot_width, plot_height = right - left, bottom - top
    rates = [row["offered_rps"] for row in rows]
    max_rate = max(rates) if rates else 1
    max_latency = max(
        [p95_threshold * 1.2, *[row["http_p95_ms"] or 0 for row in rows]]
    )
    max_error = max(
        [error_threshold * 2, *[row["error_rate_pct"] or 0 for row in rows]]
    )
    x = lambda value: left + value / max_rate * plot_width
    y_latency = lambda value: bottom - value / max_latency * plot_height
    y_error = lambda value: bottom - value / max_error * plot_height
    parts = svg_header(width, height)
    parts += [
        text(width / 2, 42, f"Knee curve: {label}", "title", "middle"),
        text(
            width / 2,
            72,
            "Knee xuất hiện khi p95/error tăng nhanh hoặc achieved RPS tách khỏi offered RPS",
            "note",
            "middle",
        ),
    ]

    for index in range(6):
        latency = max_latency * index / 5
        yy = y_latency(latency)
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, f"{latency:.0f}", "tick", "end"),
            text(
                right + 12,
                yy + 5,
                f"{max_error * index / 5:.1f}",
                "tick",
            ),
        ]
    for rate in rates:
        parts += [
            line(x(rate), top, x(rate), bottom, "#EEF0F4"),
            text(x(rate), bottom + 28, rate, "tick", "middle"),
        ]

    parts += [
        line(left, y_latency(p95_threshold), right, y_latency(p95_threshold), COLORS["green"], 2, "8 5"),
        line(left, y_error(error_threshold), right, y_error(error_threshold), COLORS["red"], 2, "8 5"),
        polyline(
            [
                (x(row["offered_rps"]), y_latency(row["http_p95_ms"]))
                for row in rows
                if row["http_p95_ms"] is not None
            ],
            COLORS["blue"],
        ),
        polyline(
            [
                (x(row["offered_rps"]), y_error(row["error_rate_pct"]))
                for row in rows
                if row["error_rate_pct"] is not None
            ],
            COLORS["red"],
        ),
    ]
    for row in rows:
        for value, mapper, color in [
            (row["http_p95_ms"], y_latency, COLORS["blue"]),
            (row["error_rate_pct"], y_error, COLORS["red"]),
        ]:
            if value is not None:
                parts.append(
                    f'<circle cx="{x(row["offered_rps"]):.1f}" cy="{mapper(value):.1f}" r="5" fill="{color}"/>'
                )

    parts += [
        line(left, bottom, right, bottom, COLORS["text"], 1.5),
        line(left, top, left, bottom, COLORS["text"], 1.5),
        line(right, top, right, bottom, COLORS["text"], 1.5),
        text(20, 360, "HTTP p95 (ms)", "axis"),
        text(1305, 360, "Error rate (%)", "axis"),
        line(420, 650, 455, 650, COLORS["blue"], 4),
        text(465, 655, "HTTP p95", "axis"),
        line(635, 650, 670, 650, COLORS["red"], 4),
        text(680, 655, "Error rate", "axis"),
        line(865, 650, 900, 650, COLORS["green"], 3, "8 5"),
        text(910, 655, "Ngưỡng p95", "axis"),
    ]

    throughput_top, throughput_bottom = 720, 920
    throughput_max = max(
        [max_rate, *[row["achieved_rps"] or 0 for row in rows]]
    ) * 1.1
    y_throughput = lambda value: (
        throughput_bottom
        - value / throughput_max * (throughput_bottom - throughput_top)
    )
    parts.append(
        text(left, throughput_top - 18, "Offered RPS so với achieved RPS", "axis")
    )
    for index in range(5):
        value = throughput_max * index / 4
        yy = y_throughput(value)
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, f"{value:.1f}", "tick", "end"),
        ]
    parts += [
        polyline(
            [(x(row["offered_rps"]), y_throughput(row["offered_rps"])) for row in rows],
            COLORS["orange"],
        ),
        polyline(
            [
                (x(row["offered_rps"]), y_throughput(row["achieved_rps"]))
                for row in rows
                if row["achieved_rps"] is not None
            ],
            COLORS["blue"],
        ),
        line(left, throughput_top, left, throughput_bottom, COLORS["text"], 1.5),
        line(left, throughput_bottom, right, throughput_bottom, COLORS["text"], 1.5),
        line(470, 965, 505, 965, COLORS["orange"], 4),
        text(515, 970, "Offered RPS", "axis"),
        line(710, 965, 745, 965, COLORS["blue"], 4),
        text(755, 970, "Achieved RPS", "axis"),
        text(width / 2, 1015, "Offered load (request/s)", "axis", "middle"),
    ]
    save_svg(parts, path)


def draw_timeline(buckets, k8s, path, label):
    width, height = 1400, 1320
    left, right = 105, 1290
    top, panel_height, gap = 105, 175, 45
    max_time = max(
        [1, *[row["elapsed_s"] for row in buckets], *[row["elapsed_s"] for row in k8s]]
    )
    x = lambda value: left + max(0, value) / max_time * (right - left)
    parts = svg_header(width, height)
    parts += [
        text(width / 2, 42, f"Timeline đồng bộ: {label}", "title", "middle"),
        text(
            width / 2,
            72,
            "k6 và Kubernetes được căn theo timestamp UTC; mỗi điểm k6 là một cửa sổ thời gian",
            "note",
            "middle",
        ),
    ]

    panels = [
        (
            "Offered / achieved RPS",
            buckets,
            [("offered_rps", COLORS["orange"]), ("achieved_rps", COLORS["blue"])],
        ),
        (
            "HTTP p95 (ms)",
            buckets,
            [("p95_ms", COLORS["blue"])],
        ),
        (
            "Error rate (%)",
            buckets,
            [("error_pct", COLORS["red"])],
        ),
        (
            "Tổng CPU của Deployment (mCPU)",
            k8s,
            [("cpu_mcores", COLORS["purple"])],
        ),
        (
            "Ready / desired replicas và tổng restart",
            k8s,
            [
                ("ready_replicas", COLORS["green"]),
                ("desired_replicas", COLORS["orange"]),
                ("restarts", COLORS["red"]),
            ],
        ),
    ]

    for panel_index, (title_value, data, series) in enumerate(panels):
        panel_top = top + panel_index * (panel_height + gap)
        panel_bottom = panel_top + panel_height
        values = [
            row[key]
            for row in data
            for key, color in series
            if row.get(key) is not None
        ]
        maximum = max([1, *values]) * 1.1
        y = lambda value: panel_bottom - value / maximum * panel_height
        parts.append(text(left, panel_top - 12, title_value, "axis"))
        for grid_index in range(5):
            value = maximum * grid_index / 4
            yy = y(value)
            parts += [
                line(left, yy, right, yy),
                text(left - 12, yy + 5, f"{value:.0f}", "tick", "end"),
            ]
        for key, color in series:
            parts.append(
                polyline(
                    [(x(row["elapsed_s"]), y(row[key])) for row in data if row.get(key) is not None],
                    color,
                )
            )
        legend_x = right - 185 * len(series)
        for index, (key, color) in enumerate(series):
            lx = legend_x + index * 185
            parts += [
                line(lx, panel_top - 17, lx + 28, panel_top - 17, color, 4),
                text(lx + 36, panel_top - 12, key, "note"),
            ]
        parts += [
            line(left, panel_top, left, panel_bottom, COLORS["text"], 1.5),
            line(left, panel_bottom, right, panel_bottom, COLORS["text"], 1.5),
        ]

    last_bottom = top + 4 * (panel_height + gap) + panel_height
    for minute in range(0, math.ceil(max_time / 60) + 1):
        xx = x(minute * 60)
        parts += [
            line(xx, last_bottom, xx, last_bottom + 7, COLORS["text"]),
            text(xx, last_bottom + 27, minute, "tick", "middle"),
        ]
    parts.append(
        text(width / 2, last_bottom + 62, "Thời gian từ lúc k6 bắt đầu (phút)", "axis", "middle")
    )
    save_svg(parts, path)


def main():
    args = parse_args()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    points = read_k6(args.k6)
    k8s_rows = read_k8s(args.k8s)
    rows = summarize_levels(points)
    phase_rows = summarize_phases(points)
    buckets, k8s_series = build_timeline(points, k8s_rows, args.window)

    write_summary(rows, output / "level-summary.csv")
    write_summary(
        phase_rows,
        output / "phase-summary.csv",
        include_phase=True,
    )
    draw_knee(
        rows,
        output / "knee.svg",
        args.label,
        args.http_p95_threshold,
        args.error_threshold,
    )
    draw_timeline(buckets, k8s_series, output / "timeline.svg", args.label)
    print(f"Wrote {output / 'level-summary.csv'}")
    print(f"Wrote {output / 'phase-summary.csv'}")
    print(f"Wrote {output / 'knee.svg'}")
    print(f"Wrote {output / 'timeline.svg'}")


if __name__ == "__main__":
    main()
