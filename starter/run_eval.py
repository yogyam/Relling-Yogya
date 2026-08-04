"""Part C entry point: one command -> one artifact.

    python run_eval.py --n 50 --out runs/baseline_n50

Runs n seeded episodes and writes runs/<name>/report.html (plus records.jsonl,
meta.json, snapshots/ for anything deeper than the 60-second read).
"""

import argparse
import sys
from pathlib import Path

import baseline
import episodes
import harness
import report

POLICIES = {
    "v1": baseline.BaselinePolicy,
    "v2": baseline.BaselinePolicyV2,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--seed-start", type=int, default=0)
    ap.add_argument(
        "--tip-probability", type=float, default=episodes.TIP_PROBABILITY
    )
    ap.add_argument("--policy", choices=sorted(POLICIES), default="v1")
    ap.add_argument(
        "--perception-noise",
        type=float,
        default=0.0,
        help="sigma (meters) of per-episode perception offset; v1 only",
    )
    ap.add_argument(
        "--part-scale",
        type=float,
        default=1.0,
        help="scale true part geometry (held-out perturbation stretch)",
    )
    ap.add_argument("--out", default="runs/latest")
    args = ap.parse_args()

    if args.part_scale != 1.0:
        import scene

        scene.apply_part_scale(args.part_scale)

    factory = POLICIES[args.policy]
    if args.perception_noise > 0:
        if args.policy != "v1":
            raise SystemExit("--perception-noise degrades v1 only")
        import baseline as _b

        factory = _b.make_noisy_policy(args.perception_noise)

    harness.run_eval(
        n=args.n,
        seed_start=args.seed_start,
        tip_probability=args.tip_probability,
        out_dir=args.out,
        policy_factory=factory,
        command=" ".join(["python", Path(sys.argv[0]).name, *sys.argv[1:]]),
    )
    report.build_report(args.out)


if __name__ == "__main__":
    main()
