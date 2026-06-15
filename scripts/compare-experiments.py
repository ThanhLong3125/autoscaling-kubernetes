#!/usr/bin/env python3
"""Compare repeated experiment summaries at the same offered request rate."""

import argparse
import csv
import math
import shutil
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path
from xml.sax.saxutils import escape


COLORS = ["#2878B5", "#F28E2B", "#59A14F", "#AF7AA1", "#D9534F"]
GRID = "#D9DEE7"
TEXT = "#20242A"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run",
        action="append",
        required=True,
        metavar="LABEL=SUMMARY_CSV",
        help="Repeat for every run; labels may repeat",
    )
    parser.add_argument("--level", required=True, type=int)
    parser.add_argument("--output", required=True)
    parser.add_argument("--title", default="So sánh các cấu hình")
    return parser.parse_args()


def load_value(path, level):
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if int(row["offered_rps"]) == level:
                return {
                    "http_p95_ms": float(row["http_p95_ms"]),
                    "error_rate_pct": float(row["error_rate_pct"]),
                    "achieved_rps": float(row["achieved_rps"]),
                }
    raise ValueError(f"{path} does not contain offered_rps={level}")


def text(x, y, value, cls="tick", anchor="start"):
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" class="{cls}" '
        f'text-anchor="{anchor}">{escape(str(value))}</text>'
    )


def line(x1, y1, x2, y2, color=GRID, width=1):
    return (
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
        f'stroke="{color}" stroke-width="{width}"/>'
    )


def save(parts, path):
    path.write_text("\n".join([*parts, "</svg>"]), encoding="utf-8")
    converter = shutil.which("rsvg-convert")
    if converter:
        subprocess.run(
            [converter, str(path), "-o", str(path.with_suffix(".png"))],
            check=True,
        )


def main():
    args = parse_args()
    groups = defaultdict(list)
    for specification in args.run:
        if "=" not in specification:
            raise ValueError("--run must use LABEL=SUMMARY_CSV")
        label, path = specification.split("=", 1)
        groups[label].append(load_value(path, args.level))

    labels = list(groups)
    metrics = [
        ("http_p95_ms", "HTTP p95 (ms)"),
        ("error_rate_pct", "Error rate (%)"),
        ("achieved_rps", "Achieved RPS"),
    ]
    width, height = 1450, 920
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        "<style>",
        "text { font-family: 'DejaVu Sans', sans-serif; fill: #20242A; }",
        ".title { font-size: 25px; font-weight: 600; }",
        ".axis { font-size: 15px; } .tick { font-size: 13px; }",
        ".note { font-size: 13px; fill: #555B65; }",
        "</style>",
        '<rect width="100%" height="100%" fill="white"/>',
        text(width / 2, 42, args.title, "title", "middle"),
        text(
            width / 2,
            72,
            f"Median, min-max và từng lần chạy tại offered load {args.level} request/s",
            "note",
            "middle",
        ),
    ]

    panel_width = 410
    panel_gap = 45
    panel_lefts = [85 + index * (panel_width + panel_gap) for index in range(3)]
    top, bottom = 130, 730

    for metric_index, (metric, metric_label) in enumerate(metrics):
        left = panel_lefts[metric_index]
        right = left + panel_width
        all_values = [
            run[metric] for label in labels for run in groups[label]
        ]
        maximum = max([1, *all_values]) * 1.15
        y = lambda value: bottom - value / maximum * (bottom - top)
        centers = [
            left + (index + 0.5) * panel_width / len(labels)
            for index in range(len(labels))
        ]
        parts.append(text((left + right) / 2, 108, metric_label, "axis", "middle"))

        for grid_index in range(6):
            value = maximum * grid_index / 5
            yy = y(value)
            parts += [
                line(left, yy, right, yy),
                text(left - 10, yy + 5, f"{value:.1f}", "tick", "end"),
            ]

        for label_index, label in enumerate(labels):
            values = [run[metric] for run in groups[label]]
            center = centers[label_index]
            low, high = min(values), max(values)
            median = statistics.median(values)
            color = COLORS[label_index % len(COLORS)]
            parts += [
                line(center, y(low), center, y(high), color, 4),
                line(center - 16, y(low), center + 16, y(low), color, 3),
                line(center - 16, y(high), center + 16, y(high), color, 3),
                line(center - 25, y(median), center + 25, y(median), TEXT, 4),
                text(center, bottom + 28, label, "tick", "middle"),
            ]
            for point_index, value in enumerate(values):
                offset = (point_index - (len(values) - 1) / 2) * 9
                parts.append(
                    f'<circle cx="{center + offset:.1f}" cy="{y(value):.1f}" '
                    f'r="5" fill="{color}" opacity="0.85"/>'
                )

        parts += [
            line(left, top, left, bottom, TEXT, 1.5),
            line(left, bottom, right, bottom, TEXT, 1.5),
        ]

    summary_y = 805
    for index, label in enumerate(labels):
        count = len(groups[label])
        parts += [
            f'<circle cx="{270 + index * 320}" cy="{summary_y}" r="7" fill="{COLORS[index % len(COLORS)]}"/>',
            text(286 + index * 320, summary_y + 5, f"{label}: n={count}", "axis"),
        ]
    parts.append(
        text(
            width / 2,
            870,
            "Đường đen: median; thanh màu: min-max; chấm: từng lần chạy",
            "note",
            "middle",
        )
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    save(parts, output)
    print(f"Wrote {output}")


if __name__ == "__main__":
    main()
