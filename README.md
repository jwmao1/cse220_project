# CSE220 Final Project: Bingo Spatial Data Prefetcher

This repository reproduces the Bingo spatial data prefetcher in Scarab for the
CSE220 final project. The implementation is adapted from the public
[Bingo ChampSim reference implementation](https://github.com/bakhshalipour/Bingo).

## Scarab Integration

`scarab-overlay/` contains the files to copy over a Scarab checkout. Bingo is
attached to Scarab's unified `L1` path, which is the Scarab counterpart of the
LLC hook used by the reference ChampSim implementation. Demand accesses train
the prefetcher through Scarab's existing hardware-prefetcher framework.
Predictions are submitted through `pref_addto_ul1req_queue_set()`, and unified
cache evictions end region generations and train the pattern-history table.

The implementation retains the reference defaults:

- 2 KiB memory regions.
- A 64-entry fully-associative filter table.
- A 128-entry fully-associative accumulation table.
- A 16K-entry, 16-way pattern-history table.
- Accurate `PC+Address` lookup followed by `PC+Offset` voting.
- A 20% vote threshold for the coverage-oriented fallback lookup.

## Apply And Build

Clone Scarab and copy the overlay into its root:

```bash
git clone https://github.com/litz-lab/scarab.git
cd scarab
git checkout 4a1223f95cb2b7306a9abd05b3b9532152a3bfb2
cd ..
cp -a scarab-overlay/. scarab/

cd scarab/src
SCARAB_ENABLE_PT_MEMTRACE=1 cmake -S . -B build/bingo \
  -DCMAKE_BUILD_TYPE=SCARABOPT \
  -DSCARAB_ENABLE_LTO=OFF \
  -DCMAKE_ASM_COMPILER=as
SCARAB_ENABLE_PT_MEMTRACE=1 cmake --build build/bingo --target scarab -j4
```

The pinned Scarab commit is the Lab-2-compatible course base used for the
formal experiment inside the course Docker image. The current Scarab `main`
branch expects newer trace metadata and is not compatible with the provided
course SPEC traces.

## Reproduce The Experiment

The baseline explicitly disables all data prefetchers. The Bingo configuration
changes only `--pref_bingo_on`.

```bash
cp benchmarks.example.csv benchmarks.csv

python3 scripts/run_bingo_spec.py \
  --scarab scarab/src/build/bingo/scarab \
  --params scarab/src/PARAMS.kaby_lake \
  --benchmarks benchmarks.csv \
  --results results_bingo

python3 scripts/plot_bingo_results.py \
  --results results_bingo \
  --out figures

```

The checked-in metrics and plot are generated from 10 SPEC workloads, two
configurations per workload, a 20M-instruction trace window, and a
10M-instruction full-warmup interval.

## Results

| Metric | Result |
| --- | ---: |
| Geometric-mean IPC speedup | 1.0437 |
| Unified L1 demand misses, baseline | 633,345 |
| Unified L1 demand misses, Bingo | 229,697 |
| Unified L1 demand-miss reduction | 63.73% |
| Useful prefetch hits | 418,703 |
| Queued Bingo predictions | 1,067,480 |

The largest speedup is 1.2849 on `523.xalancbmk_r`. Two workloads show small
slowdowns: `502.gcc_r` reaches 0.9975 speedup and `557.xz_r` reaches 0.9868.

## Repository Contents

- `scarab-overlay/`: Scarab-native Bingo module and integration files.
- `scripts/`: SPEC runner, metrics plotter, and PDF report renderer.
- `figures/`: generated metrics and publication-quality PDF/PNG summary plots.

This is a Scarab mechanism reproduction, not a bit-identical replay of the
paper's ChampSim experiments. Simulator timing, cache attachment point, trace
set, and simulation length differ from the original paper.
