#!/usr/bin/env python3
"""Create and optionally run baseline/Bingo Scarab jobs."""

import argparse
import csv
import shutil
import subprocess
from pathlib import Path


COMMON_OVERRIDES = [
    "--pref_framework_on", "1",
    "--pref_ul1_on", "1",
    "--pref_ghb_on", "0",
    "--pref_stride_on", "0",
    "--pref_stridepc_on", "0",
    "--pref_phase_on", "0",
    "--pref_2dc_on", "0",
    "--pref_markov_on", "0",
    "--pref_stream_on", "0",
    "--stream_prefetch_on", "0",
    "--l2l1pref_on", "0",
    "--l2way_pref", "0",
    "--l2markv_pref_on", "0",
    "--l2next_pref_on", "0",
    "--l2hit_stream_pref_on", "0",
    "--victim_cache_enable", "0",
]

CONFIGS = {
    "baseline_no_data_prefetch": ["--pref_bingo_on", "0"],
    "bingo": ["--pref_bingo_on", "1"],
}


def load_benchmarks(path):
    with open(path, newline="") as fp:
        reader = csv.DictReader(fp)
        rows = list(reader)
    missing = {"benchmark", "trace"} - set(reader.fieldnames or [])
    if missing:
        raise SystemExit(f"Missing required CSV columns: {', '.join(sorted(missing))}")
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scarab", default="scarab/src/build/lab3-memtrace/scarab")
    parser.add_argument("--params", default="scarab/src/PARAMS.kaby_lake")
    parser.add_argument("--benchmarks", default="benchmarks.csv")
    parser.add_argument("--results", default="results_bingo")
    parser.add_argument("--warmup", default="10000000")
    parser.add_argument("--inst-limit", default="20000000")
    parser.add_argument("--roi-begin", default="1")
    parser.add_argument("--roi-end", default="20000000")
    parser.add_argument("--only", help="Comma-separated benchmark names to run")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path.cwd()
    scarab = (root / args.scarab).resolve()
    params = (root / args.params).resolve()
    results = (root / args.results).resolve()

    selected = set(args.only.split(",")) if args.only else None
    for bench in load_benchmarks(root / args.benchmarks):
        if selected and bench["benchmark"] not in selected:
            continue
        for config_name, overrides in CONFIGS.items():
            run_dir = results / bench["benchmark"] / config_name
            cmd = [
                str(scarab),
                "--frontend", "memtrace",
                "--cbp_trace_r0", bench["trace"],
                "--memtrace_roi_begin", args.roi_begin,
                "--memtrace_roi_end", args.roi_end,
                "--inst_limit", args.inst_limit,
                "--full_warmup", args.warmup,
                "--use_fetched_count", "0",
                *COMMON_OVERRIDES,
                *overrides,
            ]

            print(f"[{bench['benchmark']}:{config_name}]")
            print(" ".join(cmd))
            if args.dry_run:
                continue

            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(params, run_dir / "PARAMS.in")
            with open(run_dir / "run.log", "w") as log:
                subprocess.run(cmd, cwd=run_dir, stdout=log, stderr=subprocess.STDOUT, check=True)


if __name__ == "__main__":
    main()
