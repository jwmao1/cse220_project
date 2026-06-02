#!/usr/bin/env python3
"""Summarize Scarab baseline/Bingo jobs and plot IPC speedup."""

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt


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


def plot_speedup(rows, out_path):
    bingo = [row for row in rows if row["config"] == "bingo"]
    plt.figure(figsize=(11, 4.8))
    plt.bar([row["benchmark"] for row in bingo], [row["speedup"] for row in bingo])
    plt.axhline(1.0, color="black", linewidth=1)
    plt.ylabel("IPC speedup over no data prefetcher")
    plt.xticks(rotation=35, ha="right")
    plt.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(out_path, dpi=200)
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
    plot_speedup(rows, out_dir / "bingo_ipc_speedup.png")


if __name__ == "__main__":
    main()
