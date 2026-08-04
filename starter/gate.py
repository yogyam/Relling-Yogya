"""Part D gate machinery: run Relling's gate (>=45 of 50) on repeat and
measure its error rates three independent ways.

- run_gate_reps: the REAL thing — disjoint 50-seed blocks through the full
  pipeline (reset -> policy -> judge), one gate verdict per block.
- blocks_from_records: reuse an existing run's records.jsonl as gate blocks
  (the n=1000 true-rate runs double as 20 gate repetitions — free data).
- bernoulli_gate_reps: fast synthetic repetitions from pure coin flips, for
  dense curves; cross-validated against the pipeline reps where they overlap.
- binom_pass_prob: the EXACT theory number (no simulation), for the
  measured-vs-theory comparison the packet asks for.
"""

import json
from math import comb
from pathlib import Path

import numpy as np
import mujoco

import scene
import episodes
import judge

GATE_N = 50
GATE_THRESHOLD = 45  # pass = at least this many successes


def gate_pass(successes: int, threshold: int = GATE_THRESHOLD) -> bool:
    return successes >= threshold


def run_episode_block(
    policy_factory,
    seed_start: int,
    n: int = GATE_N,
    tip_probability: float = episodes.TIP_PROBABILITY,
    model=None,
    data=None,
) -> list:
    """n episodes through the full pipeline; returns per-episode success bools."""
    if model is None:
        model = scene.make_model()
        data = mujoco.MjData(model)
    out = []
    for i in range(n):
        seed = seed_start + i
        episodes.reset_episode(model, data, seed, tip_probability)
        policy = policy_factory(model)
        if hasattr(policy, "set_episode_seed"):
            policy.set_episode_seed(seed)
        policy.run(data)
        out.append(bool(judge.judge(model, data).success))
    return out


def run_gate_reps(
    policy_factory,
    reps: int,
    seed_start: int = 0,
    n: int = GATE_N,
    threshold: int = GATE_THRESHOLD,
    tip_probability: float = episodes.TIP_PROBABILITY,
    log_every: int = 10,
) -> list:
    """Disjoint seed blocks -> one gate verdict per repetition."""
    model = scene.make_model()
    data = mujoco.MjData(model)
    results = []
    for r in range(reps):
        s0 = seed_start + r * n
        outcomes = run_episode_block(
            policy_factory, s0, n, tip_probability, model, data
        )
        k = sum(outcomes)
        results.append(
            {
                "rep": r,
                "seed_start": s0,
                "successes": k,
                "pass": gate_pass(k, threshold),
                "outcomes": [int(o) for o in outcomes],
            }
        )
        if log_every and (r + 1) % log_every == 0:
            passes = sum(x["pass"] for x in results)
            print(f"  rep {r + 1}/{reps}: {passes} gate passes so far")
    return results


def blocks_from_records(records_path: str | Path, n: int = GATE_N) -> list:
    """Chunk an existing run's episodes into gate repetitions (seed order)."""
    recs = [json.loads(l) for l in Path(records_path).read_text().splitlines()]
    recs.sort(key=lambda r: r["seed"])
    results = []
    for r, i in enumerate(range(0, len(recs) - n + 1, n)):
        block = recs[i : i + n]
        k = sum(b["outcome"]["success"] for b in block)
        results.append(
            {
                "rep": r,
                "seed_start": block[0]["seed"],
                "successes": k,
                "pass": gate_pass(k),
                "outcomes": [int(b["outcome"]["success"]) for b in block],
            }
        )
    return results


def bernoulli_gate_reps(
    p: float, reps: int, n: int = GATE_N, threshold: int = GATE_THRESHOLD, seed: int = 0
) -> list:
    """Pure coin-flip gate repetitions (fast, millions if wanted)."""
    rng = np.random.default_rng([seed, round(p * 10000)])
    ks = rng.binomial(n, p, size=reps)
    return [
        {"rep": r, "successes": int(k), "pass": gate_pass(int(k), threshold)}
        for r, k in enumerate(ks)
    ]


def binom_pass_prob(p: float, n: int = GATE_N, threshold: int = GATE_THRESHOLD) -> float:
    """EXACT P(gate passes | true rate p) — theory, zero simulation."""
    return float(
        sum(comb(n, k) * p**k * (1 - p) ** (n - k) for k in range(threshold, n + 1))
    )


def dispersion_check(results: list, n: int = GATE_N) -> dict:
    """Independence check: do per-block success counts scatter like binomial?

    Returns observed vs expected (binomial) variance of block successes and
    their ratio. Ratio ~1 supports independent-episode ("coin flip") behavior;
    >1 suggests positive correlation (episodes clump), <1 negative.
    """
    ks = np.array([r["successes"] for r in results], dtype=float)
    p_hat = ks.mean() / n
    observed = float(ks.var(ddof=1)) if len(ks) > 1 else float("nan")
    expected = float(n * p_hat * (1 - p_hat))
    return {
        "blocks": len(ks),
        "p_hat": p_hat,
        "observed_var": observed,
        "binomial_var": expected,
        "ratio": observed / expected if expected > 0 else float("nan"),
    }
