"""Part D driver: oracle calibration + near-threshold gate sweep.

    python gate_experiments.py --out runs/gate_oracle

Produces runs/gate_oracle/results.json with, per p-level:
- pipeline gate repetitions (full reset->oracle->judge blocks of 50)
- fast Bernoulli repetitions (dense cross-check)
- the exact binomial theory number
plus a large-n calibration measurement of the oracle instrument itself.

Seed layout: calibration uses seeds 100000+; sweep level i uses seeds
200000 + i*20000 (disjoint from everything else in the project).
"""

import argparse
import json
import time
from pathlib import Path

import gate
import oracle

P_LEVELS = [0.80, 0.85, 0.88, 0.90, 0.92, 0.95]
PIPELINE_REPS = 200
BERNOULLI_REPS = 20000
CALIBRATION_P = 0.88
CALIBRATION_N = 3000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="runs/gate_oracle")
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()

    # 1. Calibrate the instrument: dial p, measure p back at large n.
    print(f"calibration: oracle p={CALIBRATION_P} over n={CALIBRATION_N}")
    outcomes = gate.run_episode_block(
        oracle.make_oracle(CALIBRATION_P), seed_start=100000, n=CALIBRATION_N
    )
    measured = sum(outcomes) / len(outcomes)
    lo_hi = None
    try:
        from harness import wilson_interval

        lo_hi = wilson_interval(sum(outcomes), len(outcomes))
    except Exception:
        pass
    calibration = {
        "dialed_p": CALIBRATION_P,
        "n": CALIBRATION_N,
        "measured": measured,
        "wilson95": lo_hi,
    }
    print(f"  measured {measured:.4f} (dialed {CALIBRATION_P})")

    # 2. Sweep the gate near the threshold, three ways per level.
    sweep = []
    for i, p in enumerate(P_LEVELS):
        print(f"sweep p={p}: {PIPELINE_REPS} pipeline gate reps...")
        pipeline = gate.run_gate_reps(
            oracle.make_oracle(p),
            reps=PIPELINE_REPS,
            seed_start=200000 + i * 20000,
            log_every=50,
        )
        bern = gate.bernoulli_gate_reps(p, BERNOULLI_REPS, seed=i)
        level = {
            "p": p,
            "pipeline_reps": PIPELINE_REPS,
            "pipeline_pass_rate": sum(r["pass"] for r in pipeline) / PIPELINE_REPS,
            "pipeline_successes": [r["successes"] for r in pipeline],
            "pipeline_pass": [bool(r["pass"]) for r in pipeline],
            "bernoulli_reps": BERNOULLI_REPS,
            "bernoulli_pass_rate": sum(r["pass"] for r in bern) / BERNOULLI_REPS,
            "theory_pass_prob": gate.binom_pass_prob(p),
            "dispersion": gate.dispersion_check(pipeline),
        }
        sweep.append(level)
        print(
            f"  p={p}: pipeline {level['pipeline_pass_rate']:.3f} | "
            f"bernoulli {level['bernoulli_pass_rate']:.3f} | "
            f"theory {level['theory_pass_prob']:.3f}"
        )

    results = {
        "calibration": calibration,
        "gate": {"n": gate.GATE_N, "threshold": gate.GATE_THRESHOLD},
        "sweep": sweep,
        "wall_s": round(time.monotonic() - t0, 1),
    }
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nwrote {out / 'results.json'}  ({results['wall_s']}s)")


if __name__ == "__main__":
    main()
