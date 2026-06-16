#!/usr/bin/env python3
"""Plot aggregate knee and HPA candidate analysis from repeated fixed runs."""

import argparse
import csv
import math
import shutil
import subprocess
from pathlib import Path
from xml.sax.saxutils import escape


BLUE = "#2878B5"
ORANGE = "#F28E2B"
RED = "#D9534F"
GREEN = "#59A14F"
PURPLE = "#AF7AA1"
GRID = "#D9DEE7"
TEXT = "#20242A"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aggregate", required=True)
    parser.add_argument("--cpu", required=True)
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args()


def read_csv(path):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        return [
            {
                key: float(value) if key != "offered_rps" else int(value)
                for key, value in row.items()
            }
            for row in csv.DictReader(handle)
        ]


def text(x, y, value, css_class="tick", anchor="start"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{css_class}" '
        f'text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def line(x1, y1, x2, y2, color=GRID, width=1, dash=None):
    dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="{width}"{dash_attr}/>'
    )


def polyline(points, color, width=3):
    coordinates = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    return (
        f'<polyline points="{coordinates}" fill="none" stroke="{color}" '
        f'stroke-width="{width}" stroke-linejoin="round"/>'
    )


def header(width, height):
    return [
        (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
            f'height="{height}" viewBox="0 0 {width} {height}">'
        ),
        "<style>",
        "text { font-family: 'DejaVu Sans', sans-serif; fill: #20242A; }",
        ".title { font-size: 27px; font-weight: 600; }",
        ".axis { font-size: 17px; }",
        ".tick { font-size: 14px; }",
        ".note { font-size: 14px; fill: #555B65; }",
        "</style>",
        '<rect width="100%" height="100%" fill="white"/>',
    ]


def save(parts, path):
    path.write_text("\n".join([*parts, "</svg>"]), encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter:
        subprocess.run(
            [converter, str(path), "-o", str(path.with_suffix(".png"))],
            check=True,
        )


def draw_knee(rows, output):
    width, height = 1400, 850
    left, right, top, bottom = 115, 1280, 120, 710
    max_p95 = max(row["max_http_p95_ms"] for row in rows) * 1.1
    max_error = max(row["max_error_rate_pct"] for row in rows) * 1.15
    x = lambda value: left + (value - 10) / 10 * (right - left)
    y_p95 = lambda value: bottom - value / max_p95 * (bottom - top)
    y_error = lambda value: bottom - value / max_error * (bottom - top)

    parts = header(width, height)
    parts += [
        text(width / 2, 42, "Knee của cấu hình 2 Pod qua ba lần chạy", "title", "middle"),
        text(
            width / 2,
            72,
            "Đường: median; thanh dọc: min-max giữa ba lần chạy",
            "note",
            "middle",
        ),
    ]
    for index in range(6):
        yy = top + index * (bottom - top) / 5
        p95_value = max_p95 * (5 - index) / 5
        error_value = max_error * (5 - index) / 5
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, f"{p95_value:.0f}", "tick", "end"),
            text(right + 12, yy + 5, f"{error_value:.1f}", "tick"),
        ]
    for rps in range(10, 21, 2):
        xx = x(rps)
        parts += [
            line(xx, top, xx, bottom),
            text(xx, bottom + 30, rps, "tick", "middle"),
        ]

    parts += [
        line(left, y_p95(550), right, y_p95(550), GREEN, 2, "8 6"),
        line(left, y_error(1), right, y_error(1), RED, 2, "8 6"),
        polyline([(x(row["offered_rps"]), y_p95(row["median_http_p95_ms"])) for row in rows], BLUE),
        polyline([(x(row["offered_rps"]), y_error(row["median_error_rate_pct"])) for row in rows], RED),
    ]
    for row in rows:
        xx = x(row["offered_rps"])
        for low, high, scale, color in [
            ("min_http_p95_ms", "max_http_p95_ms", y_p95, BLUE),
            ("min_error_rate_pct", "max_error_rate_pct", y_error, RED),
        ]:
            parts += [
                line(xx, scale(row[low]), xx, scale(row[high]), color, 3),
                line(xx - 8, scale(row[low]), xx + 8, scale(row[low]), color, 2),
                line(xx - 8, scale(row[high]), xx + 8, scale(row[high]), color, 2),
            ]
        parts += [
            f'<circle cx="{xx:.1f}" cy="{y_p95(row["median_http_p95_ms"]):.1f}" r="5" fill="{BLUE}"/>',
            f'<circle cx="{xx:.1f}" cy="{y_error(row["median_error_rate_pct"]):.1f}" r="5" fill="{RED}"/>',
        ]

    parts += [
        line(left, top, left, bottom, TEXT, 1.5),
        line(right, top, right, bottom, TEXT, 1.5),
        line(left, bottom, right, bottom, TEXT, 1.5),
        text((left + right) / 2, bottom + 65, "Offered load (request/s)", "axis", "middle"),
        text(left, top - 18, "HTTP p95 (ms)", "axis"),
        text(right, top - 18, "Error rate (%)", "axis", "end"),
        line(390, 785, 445, 785, BLUE, 4),
        text(455, 790, "HTTP p95", "axis"),
        line(610, 785, 665, 785, RED, 4),
        text(675, 790, "Error rate", "axis"),
        line(865, 785, 920, 785, GREEN, 2, "8 6"),
        text(930, 790, "Nguong p95 550 ms", "axis"),
    ]
    save(parts, output)


def desired_replicas(total_cpu, cpu_per_pod, target, current=2):
    ratio = cpu_per_pod / target
    if 0.9 <= ratio <= 1.1:
        return current
    return math.ceil(total_cpu / target)


def draw_cpu_measurements(rows, output):
    width, height = 1400, 820
    left, right, top, bottom = 120, 1280, 120, 680
    x = lambda value: left + (value - 10) / 10 * (right - left)
    y = lambda value: bottom - value / 1000 * (bottom - top)

    parts = header(width, height)
    parts += [
        text(
            width / 2,
            42,
            "CPU của cấu hình 2 Pod theo từng mức tải",
            "title",
            "middle",
        ),
        text(
            width / 2,
            72,
            "Chấm: từng lần chạy; đường: median tổng CPU của ba lần chạy",
            "note",
            "middle",
        ),
    ]
    for value in range(0, 1001, 200):
        yy = y(value)
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, value, "tick", "end"),
        ]
    for row in rows:
        xx = x(row["offered_rps"])
        parts += [
            line(xx, top, xx, bottom),
            text(xx, bottom + 30, row["offered_rps"], "tick", "middle"),
        ]

    median_points = [
        (x(row["offered_rps"]), y(row["median_total_cpu_mcores"]))
        for row in rows
    ]
    parts.append(polyline(median_points, PURPLE, 4))

    run_keys = [
        "run1_total_cpu_median",
        "run2_total_cpu_median",
        "run3_total_cpu_median",
    ]
    offsets = [-9, 0, 9]
    run_colors = [BLUE, ORANGE, GREEN]
    for row in rows:
        xx = x(row["offered_rps"])
        parts.append(
            f'<circle cx="{xx:.1f}" cy="{y(row["median_total_cpu_mcores"]):.1f}" '
            f'r="7" fill="{PURPLE}"/>'
        )
        for key, offset, color in zip(run_keys, offsets, run_colors):
            parts.append(
                f'<circle cx="{xx + offset:.1f}" cy="{y(row[key]):.1f}" '
                f'r="5" fill="{color}" opacity="0.9"/>'
            )

    parts += [
        line(left, top, left, bottom, TEXT, 1.5),
        line(left, bottom, right, bottom, TEXT, 1.5),
        text(left, top - 18, "Tổng CPU của 2 Pod (mCPU)", "axis"),
        text(
            (left + right) / 2,
            bottom + 65,
            "Offered load (request/s)",
            "axis",
            "middle",
        ),
        f'<circle cx="395" cy="770" r="6" fill="{BLUE}"/>',
        text(410, 775, "Run 1", "axis"),
        f'<circle cx="530" cy="770" r="6" fill="{ORANGE}"/>',
        text(545, 775, "Run 2", "axis"),
        f'<circle cx="665" cy="770" r="6" fill="{GREEN}"/>',
        text(680, 775, "Run 3", "axis"),
        line(810, 770, 865, 770, PURPLE, 4),
        text(875, 775, "Median", "axis"),
    ]
    save(parts, output)


def draw_hpa(rows, output):
    rows = [row for row in rows if row["offered_rps"] <= 16]
    width, height = 1400, 970
    left, right = 120, 1280
    top1, bottom1 = 130, 520
    top2, bottom2 = 650, 830
    x = lambda value: left + (value - 10) / 6 * (right - left)
    y_cpu = lambda value: bottom1 - value / 450 * (bottom1 - top1)
    y_replica = lambda value: bottom2 - (value - 2) / 2 * (bottom2 - top2)

    parts = header(width, height)
    parts += [
        text(width / 2, 42, "Liên hệ CPU trước knee với target và replica HPA", "title", "middle"),
        text(
            width / 2,
            72,
            "Target là phần trăm của CPU request 100m; tolerance scale-up mặc định là 10%",
            "note",
            "middle",
        ),
    ]
    for value in [0, 100, 200, 300, 400]:
        yy = y_cpu(value)
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, value, "tick", "end"),
        ]
    for row in rows:
        xx = x(row["offered_rps"])
        parts += [
            line(xx, top1, xx, bottom2),
            text(xx, bottom2 + 32, row["offered_rps"], "tick", "middle"),
        ]

    cpu_points = [
        (x(row["offered_rps"]), y_cpu(row["median_cpu_per_pod_mcores"]))
        for row in rows
    ]
    parts += [
        polyline(cpu_points, PURPLE, 4),
        line(left, y_cpu(250), right, y_cpu(250), ORANGE, 2, "9 6"),
        line(left, y_cpu(275), right, y_cpu(275), ORANGE, 3),
        line(left, y_cpu(300), right, y_cpu(300), BLUE, 2, "9 6"),
        line(left, y_cpu(330), right, y_cpu(330), BLUE, 3),
        text(right - 5, y_cpu(250) - 7, "Target 250% = 250m", "note", "end"),
        text(right - 5, y_cpu(275) - 7, "Scale-up khi CPU/Pod > 275m", "note", "end"),
        text(right - 5, y_cpu(300) - 7, "Target 300% = 300m", "note", "end"),
        text(right - 5, y_cpu(330) - 7, "Scale-up khi CPU/Pod > 330m", "note", "end"),
        text(left, top1 - 18, "CPU trung bình mỗi Pod (mCPU)", "axis"),
    ]
    for xx, yy in cpu_points:
        parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="6" fill="{PURPLE}"/>')

    for replica in [2, 3, 4]:
        yy = y_replica(replica)
        parts += [
            line(left, yy, right, yy),
            text(left - 12, yy + 5, replica, "tick", "end"),
        ]
    replica_300 = [
        (
            x(row["offered_rps"]),
            y_replica(
                desired_replicas(
                    row["median_total_cpu_mcores"],
                    row["median_cpu_per_pod_mcores"],
                    300,
                )
            ),
        )
        for row in rows
    ]
    replica_250 = [
        (
            x(row["offered_rps"]),
            y_replica(
                desired_replicas(
                    row["median_total_cpu_mcores"],
                    row["median_cpu_per_pod_mcores"],
                    250,
                )
            ),
        )
        for row in rows
    ]
    parts += [
        polyline(replica_300, BLUE, 4),
        polyline(replica_250, ORANGE, 4),
        text(left, top2 - 18, "Replica dự kiến từ 2 Pod hiện tại", "axis"),
        text((left + right) / 2, bottom2 + 55, "Offered load (request/s)", "axis", "middle"),
        line(500, 930, 555, 930, BLUE, 4),
        text(565, 935, "Target 300%", "axis"),
        line(760, 930, 815, 930, ORANGE, 4),
        text(825, 935, "Target 250%", "axis"),
    ]
    for points, color in [(replica_300, BLUE), (replica_250, ORANGE)]:
        for xx, yy in points:
            parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="6" fill="{color}"/>')
    save(parts, output)


def main():
    args = parse_args()
    aggregate = read_csv(args.aggregate)
    cpu = read_csv(args.cpu)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    draw_knee(aggregate, output / "fixed-capacity-knee.svg")
    draw_cpu_measurements(cpu, output / "fixed-capacity-cpu.svg")
    draw_hpa(cpu, output / "hpa-target-analysis.svg")
    print(f"Wrote charts to {output}")


if __name__ == "__main__":
    main()
