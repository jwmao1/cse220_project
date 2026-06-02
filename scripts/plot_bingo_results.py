#!/usr/bin/env python3
"""Summarize Scarab baseline/Bingo jobs and plot IPC speedup."""

import argparse
import csv
import math
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter


CONFIGS = ("baseline_no_data_prefetch", "bingo")


def parse_stats(run_dir):
    stats = {}
    for path in sorted(run_dir.glob("*.stat.0.csv")):
        with open(path, errors="ignore", newline="") as fp:
            for row in csv.reader(fp):
                if len(row) < 3:
                    continue
                try:
                    stats[row[0].strip()] = float(row[2].strip())
                except ValueError:
                    pass
    return stats


def stat(stats, name):
    return stats.get(name, stats.get(f"{name}_count", 0.0))


def collect(results_dir):
    rows = []
    for bench_dir in sorted(Path(results_dir).iterdir()):
        if not bench_dir.is_dir():
            continue
        for config in CONFIGS:
            run_dir = bench_dir / config
            if not run_dir.exists():
                continue
            stats = parse_stats(run_dir)
            cycles = stat(stats, "Periodic_Cycles") or stat(stats, "NODE_CYCLE")
            insts = stat(stats, "Periodic_Instructions") or stat(stats, "NODE_INST_COUNT")
            rows.append(
                {
                    "benchmark": bench_dir.name,
                    "config": config,
                    "ipc": insts / cycles if cycles else 0.0,
                    "l1_demand_misses": stat(stats, "L1_DEMAND_MISS"),
                    "l1_prefetch_hits": stat(stats, "L1_PREF_HIT"),
                    "bingo_requested": stat(stats, "BINGO_PREF_REQUESTED"),
                    "bingo_queued": stat(stats, "BINGO_PREF_QUEUED"),
                    "bingo_queue_rejected": stat(stats, "BINGO_PREF_QUEUE_REJECTED"),
                    "bingo_pc_address_hits": stat(stats, "BINGO_PHT_PC_ADDRESS_HIT"),
                    "bingo_pc_offset_hits": stat(stats, "BINGO_PHT_PC_OFFSET_HIT"),
                }
            )
    return rows


def add_speedup(rows):
    baseline = {row["benchmark"]: row["ipc"] for row in rows if row["config"] == CONFIGS[0]}
    for row in rows:
        base_ipc = baseline.get(row["benchmark"], 0.0)
        row["speedup"] = row["ipc"] / base_ipc if base_ipc else 0.0


def plot_summary(rows, out_prefix):
    bingo = [row for row in rows if row["config"] == "bingo"]
    baseline = {row["benchmark"]: row for row in rows if row["config"] == CONFIGS[0]}
    labels = [row["benchmark"].split(".", 1)[-1].removesuffix("_r") for row in bingo]
    speedups = [row["speedup"] for row in bingo]
    geomean = math.exp(sum(math.log(speedup) for speedup in speedups) / len(speedups))

    miss_reductions = []
    total_baseline_misses = 0.0
    total_bingo_misses = 0.0
    for row in bingo:
        baseline_misses = baseline[row["benchmark"]]["l1_demand_misses"]
        bingo_misses = row["l1_demand_misses"]
        total_baseline_misses += baseline_misses
        total_bingo_misses += bingo_misses
        miss_reductions.append(
            (baseline_misses - bingo_misses) / baseline_misses if baseline_misses else 0.0
        )
    total_reduction = (total_baseline_misses - total_bingo_misses) / total_baseline_misses

    plt.rcParams.update(
        {
            "font.family": "serif",
            "pdf.use14corefonts": True,
            "ps.useafm": True,
            "font.size": 8,
            "axes.labelsize": 8,
            "axes.titlesize": 9,
            "xtick.labelsize": 7,
            "ytick.labelsize": 7,
            "legend.fontsize": 7,
        }
    )
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.45), constrained_layout=True)

    perf_labels = labels + ["GMEAN"]
    perf_values = speedups + [geomean]
    perf_colors = ["#D55E00" if value < 1.0 else "#0072B2" for value in speedups] + ["#2B2B2B"]
    axes[0].bar(perf_labels, perf_values, color=perf_colors, width=0.72)
    axes[0].axhline(1.0, color="#555555", linewidth=0.8)
    axes[0].set_ylim(0.96, 1.31)
    axes[0].set_ylabel("IPC speedup")
    axes[0].set_title("(a) Performance over no-data-prefetch baseline")
    axes[0].grid(axis="y", color="#D0D0D0", linewidth=0.5)
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].text(
        len(labels),
        geomean + 0.008,
        f"{geomean:.3f}x",
        ha="center",
        va="bottom",
        fontsize=7,
        fontweight="bold",
    )

    miss_labels = labels + ["TOTAL"]
    miss_values = miss_reductions + [total_reduction]
    miss_colors = ["#009E73"] * len(labels) + ["#2B2B2B"]
    axes[1].bar(miss_labels, miss_values, color=miss_colors, width=0.72)
    axes[1].axhline(0.0, color="#555555", linewidth=0.8)
    axes[1].set_ylim(0.0, 1.0)
    axes[1].yaxis.set_major_formatter(PercentFormatter(1.0))
    axes[1].set_ylabel("Demand-miss reduction")
    axes[1].set_title("(b) Unified L1 demand-miss reduction")
    axes[1].grid(axis="y", color="#D0D0D0", linewidth=0.5)
    axes[1].tick_params(axis="x", rotation=45)
    axes[1].text(
        len(labels),
        total_reduction + 0.025,
        f"{total_reduction:.1%}",
        ha="center",
        va="bottom",
        fontsize=7,
        fontweight="bold",
    )
    exchange_index = labels.index("exchange2")
    axes[1].text(exchange_index, 0.025, "N/A", ha="center", va="bottom", fontsize=6, rotation=90)

    for axis in axes:
        axis.set_axisbelow(True)
        axis.spines["top"].set_visible(False)
        axis.spines["right"].set_visible(False)

    fig.savefig(out_prefix.with_suffix(".pdf"))
    fig.savefig(out_prefix.with_suffix(".png"), dpi=300)
    plt.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", default="results_bingo")
    parser.add_argument("--out", default="figures_bingo")
    args = parser.parse_args()

    rows = collect(args.results)
    if not rows:
        raise SystemExit("No Scarab stat files found. Run simulations first.")
    add_speedup(rows)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "bingo_metrics.csv", "w", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    plot_summary(rows, out_dir / "bingo_summary")


if __name__ == "__main__":
    main()
