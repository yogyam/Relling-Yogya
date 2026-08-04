"""One command for every derived number in the memo's findings 5 and
recommendation: the gate design menu, sequential early-stopping savings, and
the real-variant gate blocks + independence check.

    python gate_design.py

No simulation here — the design menu and early-stop numbers are exact
binomial arithmetic (closed form / dynamic programming), and the gate-block
section reads the committed n=1000 run records. The memo's "42–47 episodes"
and "~6 episodes" claims come from the EARLY STOPPING table below.
"""

from pathlib import Path

import gate

P_LEVELS = (0.80, 0.85, 0.88, 0.90, 0.92, 0.95)
DESIGNS = (
    ("current  >=45/50", 50, 45),
    ("margin   >=47/50", 50, 47),
    ("n=100    >=90   ", 100, 90),
    ("n=100    >=93   ", 100, 93),
)
TRUE_RUNS = ("true_v1", "true_v2", "true_mild", "true_heavy")


def expected_episodes(p: float, n: int, threshold: int) -> float:
    """Exact E[episodes] under sequential early stopping.

    Stop the moment the verdict is decided: `threshold` successes = pass,
    n - threshold + 1 failures = fail. Dynamic programming over
    (successes, failures) states; no randomness involved.
    """
    max_f = n - threshold + 1
    E = [[0.0] * (max_f + 1) for _ in range(threshold + 1)]
    for s in range(threshold - 1, -1, -1):
        for f in range(max_f - 1, -1, -1):
            E[s][f] = 1.0 + p * E[s + 1][f] + (1.0 - p) * E[s][f + 1]
    return E[0][0]


def main() -> None:
    print("DESIGN MENU — P(gate passes | true rate), exact binomial")
    header = "  ".join(f"p={p:.2f}" for p in P_LEVELS)
    print(f"  {'design':18s} {header}")
    for name, n, t in DESIGNS:
        row = "  ".join(
            f"{100 * gate.binom_pass_prob(p, n, t):5.1f}%" for p in P_LEVELS
        )
        print(f"  {name:18s} {row}")
    print(
        "  (memo: 88% false-pass 43.5% -> 13.5% at >=47/50; "
        "92% true-pass 79.2% -> 42.5%)"
    )

    print("\nEARLY STOPPING — expected episodes, current gate (>=45/50)")
    print("  verdicts are identical to the full 50; only the count changes")
    for p in (0.05, 0.10, 0.30, 0.50) + P_LEVELS:
        tag = "clearly bad" if p <= 0.5 else "near spec"
        print(f"  true rate {p:.2f} ({tag:11s}): {expected_episodes(p, 50, 45):5.1f}")

    print("\nREAL-VARIANT GATE BLOCKS + INDEPENDENCE (from n=1000 records)")
    runs = Path(__file__).parent / "runs"
    for name in TRUE_RUNS:
        path = runs / name / "records.jsonl"
        if not path.exists():
            print(f"  {name}: {path} missing — run the Finding 1/3 commands first")
            continue
        blocks = gate.blocks_from_records(path)
        disp = gate.dispersion_check(blocks)
        passes = sum(b["pass"] for b in blocks)
        ks = [b["successes"] for b in blocks]
        print(
            f"  {name:10s} gate passes {passes}/{len(blocks)} | block successes "
            f"{min(ks)}-{max(ks)}/50 | dispersion ratio {disp['ratio']:.2f}"
        )
    print("  (ratio ~1 = episodes behave like independent coin flips)")


if __name__ == "__main__":
    main()
