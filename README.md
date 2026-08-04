# Relling take-home — stack, measure, and question the gate

Simulated UR5e + Robotiq 2F-85 stacking cell (MuJoCo), a deliberately simple
baseline policy, an evaluation harness, and an empirical audit of the
production gate ("ship at ≥45/50"). **Read these in order:**

| What | Where |
|---|---|
| The run report (open this first) | [reports/final_report.html](reports/final_report.html) |
| The gate memo (≤2 pages) | [MEMO.md](MEMO.md) |
| The decision journal | [JOURNAL.md](JOURNAL.md) |
| All code | [starter/](starter/) |

## Setup (fresh clone → working sim, ~5 minutes)

```bash
cd starter
python3 -m venv .venv && source .venv/bin/activate   # python 3.11 used here
pip install -r requirements.txt
./fetch_assets.sh          # pins mujoco_menagerie at commit 71f066ad
python smoke.py            # prints SMOKE OK
python check_all.py        # all verification suites -> CHECK ALL OK
```

All commands below assume `starter/` as working directory with the venv
active. Everything is seeded; per-machine floating point may shift borderline
episodes slightly across OS/CPU, but on one machine results are exactly
reproducible (bit-identical resets, verified in `check_episodes.py`).

## Regenerate every number in the memo

**Finding 1 — baseline 10% at n=50 (CI 4–21%), and its true rate 5.3%:**
```bash
python run_eval.py --n 50  --out runs/baseline_n50    # 5/50 = 10.0%, ~1 min
python run_eval.py --n 1000 --out runs/true_v1        # 53/1000 = 5.3%, ~20 min
```

**Finding 2 — the gate sweep (calibration 88.4%, the measured-vs-theory
table):** ~2 h; writes `runs/gate_oracle/results.json`.
```bash
python gate_experiments.py --out runs/gate_oracle
```

**Finding 3 — v2 ties v1 at gate size (10% at n=50, different taxonomy),
and the variant true rates (v2 6.6%, mild 5.7%, heavy 1.7%):**
```bash
python run_eval.py --n 50   --policy v2 --out runs/v2_n50              # 5/50, ~2 min
python run_eval.py --n 1000 --policy v2 --out runs/true_v2             # ~45 min
python run_eval.py --n 1000 --perception-noise 0.002 --out runs/true_mild
python run_eval.py --n 1000 --perception-noise 0.005 --out runs/true_heavy
```
The report's "small-sample measured" cells for mild/heavy (6%, 2%) come from
the n=100 calibration sweeps that picked the noise tiers:
```bash
python run_eval.py --n 100 --perception-noise 0.002 --out runs/calib_0.002  # 6/100
python run_eval.py --n 100 --perception-noise 0.005 --out runs/calib_5mm    # 2/100
```

**Finding 4 — same policy, different conditions (10% vs 22%):**
```bash
python run_eval.py --n 50 --tip-probability 0 --out runs/v1_tip0_n50   # 11/50
```

**Finding 5 + the recommendation — gate design menu, early-stopping episode
counts, real gate blocks (0/20 everywhere), independence ratios:**
```bash
python gate_design.py      # exact arithmetic + reads the Finding 1/3 records
```

**Stretch — 10% larger parts (0/200, taxonomy shift):**
```bash
python run_eval.py --n 200 --part-scale 1.1 --out runs/perturb_110
```

**The report artifact (renders from the runs above):**
```bash
python final_report.py     # writes ../reports/final_report.html
```

## Triage tools

```bash
python render_episode.py 42          # PNG snapshot of any seeded episode
python render_video.py 45 --policy v1   # full episode MP4 (needs ffmpeg)
```
Any episode is exactly replayable from its seed. The interactive viewer
(`mjpython view.py`) requires mjpython, which is broken on some macOS/conda
setups (journaled); the headless tools above cover everything.

## Declared assumptions and blind spots (details in MEMO.md)

- Grasping is a kinematic attach within 20 mm (packet's sanctioned fallback,
  taken after a timeboxed real-contact attempt): grasp-slip and
  drop-in-transit failures cannot occur in this evaluation.
- Cylinders spawn tipped with probability 0.2 each (my reading of
  "randomized orientations"); `--tip-probability` changes it.
- Judge tolerances (25 mm target, 10 mm alignment, 10° tilt, 2 s settle) are
  mine, calibrated against measured simulator behavior, not a customer spec.
- Physical parameters where the packet is silent: cylinder mass 42 g
  (simulator default density), slide friction 1.0 (default) with rolling
  friction 0.001 (chosen to stop endless rolling), an infinite floor plane
  rather than a bounded table, spawn region x 0.35–0.60 / y ±0.25 m with
  ≥8 cm part separation, and episode time limits of 60 s (v1) / 120 s (v2)
  — the source of the "timeout" failure category.

## Starter modifications (per packet: "say so if you do")

`scene.py`: offscreen framebuffer 1280×960; cylinders get condim 6 + rolling
friction (default contact lets tipped parts roll forever — measured);
part-scale hook. `view.py`: optional seed argument. `requirements.txt`:
pillow added. Everything else in `starter/` beyond the original scaffold
(episodes, judge, baseline, harness, reports, gate machinery) is new work.
