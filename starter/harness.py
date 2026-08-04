"""Part C: the evaluation harness.

run_eval(...) plays n seeded episodes (reset -> policy -> judge), writing one
record per episode: everything a teammate needs to triage a failure without
re-running it — seed, initial poses/states, verdict, mechanism category,
policy trace, timings, final poses, and a snapshot of the final state.

Failure taxonomy: deterministic rules over (judge verdict + policy trace),
priority-ordered so each episode lands in exactly one mechanism bucket.

Uncertainty: Wilson 95% interval — well-behaved at small n and extreme rates,
unlike the naive normal approximation.
"""

import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np
import mujoco
from PIL import Image

import scene
import episodes
import baseline
import judge
import render_episode

SNAP_W, SNAP_H = 480, 360  # report thumbnails


def wilson_interval(k: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = (z / denom) * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (max(0.0, center - half), min(1.0, center + half))


def classify(verdict: judge.Verdict, trace: baseline.EpisodeTrace) -> str:
    """Mechanism category for the taxonomy. Priority-ordered, deterministic."""
    if verdict.success:
        return "success"
    if trace.timed_out:
        return "timeout"
    if trace.skipped_tipped:
        # A skipped tipped part makes a 3-stack impossible regardless of the
        # rest of the episode — it is the root cause.
        return "tipped_part_skipped"
    if trace.picks_lifted < trace.picks_attempted:
        return "grasp_miss"
    if verdict.stack_height == 2:
        return "top_placement_failed"
    if verdict.stack_height == 1:
        return "stack_collapse"
    return "base_misplaced"  # height 0 with all parts lifted and placed


CATEGORY_ORDER = [
    "tipped_part_skipped",
    "grasp_miss",
    "top_placement_failed",
    "stack_collapse",
    "base_misplaced",
    "timeout",
]

CATEGORY_BLURBS = {
    "tipped_part_skipped": "a cylinder spawned lying down; the policy has no strategy for tipped parts and skipped it",
    "grasp_miss": "the gripper closed but captured nothing (approach missed the part)",
    "top_placement_failed": "two stacked cleanly; the third placement failed or knocked itself off",
    "stack_collapse": "placements destroyed the stack — one cylinder left standing at best",
    "base_misplaced": "everything was lifted and placed, but no cylinder ended within tolerance of the target",
    "timeout": "the episode hit its time limit before finishing",
}


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=Path(__file__).parent,
        ).stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def run_eval(
    n: int,
    seed_start: int = 0,
    tip_probability: float = episodes.TIP_PROBABILITY,
    out_dir: str | Path = "runs/latest",
    policy_factory=None,
    snapshots: bool = True,
    command: str | None = None,
) -> dict:
    """Run n episodes; write records.jsonl, meta.json, snapshots/. Returns meta."""
    out = Path(out_dir)
    (out / "snapshots").mkdir(parents=True, exist_ok=True)

    model = scene.make_model()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(
        model, height=render_episode.HEIGHT, width=render_episode.WIDTH
    )
    cam = render_episode.make_camera()
    if policy_factory is None:
        policy_factory = baseline.BaselinePolicy

    records = []
    t_start = time.monotonic()
    with open(out / "records.jsonl", "w") as fh:
        for i in range(n):
            seed = seed_start + i
            wall0 = time.monotonic()
            init = episodes.reset_episode(model, data, seed, tip_probability)
            policy = policy_factory(model)
            if hasattr(policy, "set_episode_seed"):
                policy.set_episode_seed(seed)  # noisy variants: seeded noise
            trace = policy.run(data)
            sim_end = data.time
            verdict = judge.judge(model, data)
            wall = time.monotonic() - wall0

            snap_name = None
            if snapshots:
                renderer.update_scene(data, camera=cam)
                img = Image.fromarray(renderer.render())
                img = img.resize((SNAP_W, SNAP_H), Image.LANCZOS)
                snap_name = f"ep_{seed:04d}.jpg"
                img.save(out / "snapshots" / snap_name, quality=70)

            rec = {
                "episode": i,
                "seed": seed,
                "init": {
                    name: {
                        "pos": [round(v, 4) for v in init.settled_qpos[name][:3]],
                        "state": init.spawn_states[name],
                    }
                    for name in scene.CYLINDER_NAMES
                },
                "outcome": {
                    "success": verdict.success,
                    "stack_height": verdict.stack_height,
                    "failure_reason": verdict.failure_reason,
                },
                "category": classify(verdict, trace),
                "policy": {
                    "picks_attempted": trace.picks_attempted,
                    "picks_lifted": trace.picks_lifted,
                    "skipped_tipped": trace.skipped_tipped,
                    "timed_out": trace.timed_out,
                    "events": trace.events,
                },
                "final": {
                    name: {
                        "pos": [round(v, 4) for v in
                                (verdict.details["cylinders"][name]["x"],
                                 verdict.details["cylinders"][name]["y"],
                                 verdict.details["cylinders"][name]["z_mm"] / 1000)],
                        "tilt_deg": verdict.details["cylinders"][name]["tilt_deg"],
                    }
                    for name in scene.CYLINDER_NAMES
                },
                "timing": {"sim_s": round(sim_end, 1), "wall_s": round(wall, 1)},
                "snapshot": snap_name,
            }
            records.append(rec)
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            tag = "OK " if verdict.success else "fail"
            print(
                f"[{i + 1:3d}/{n}] seed {seed}: {tag} h={verdict.stack_height} "
                f"{rec['category']:22s} ({wall:.1f}s)"
            )

    k = sum(r["outcome"]["success"] for r in records)
    lo, hi = wilson_interval(k, n)
    heights = [0, 0, 0, 0]
    for r in records:
        heights[r["outcome"]["stack_height"]] += 1
    taxonomy = {}
    for r in records:
        if r["category"] != "success":
            taxonomy[r["category"]] = taxonomy.get(r["category"], 0) + 1

    meta = {
        "n": n,
        "seed_start": seed_start,
        "tip_probability": tip_probability,
        "successes": k,
        "success_rate": k / n,
        "wilson95": [round(lo, 4), round(hi, 4)],
        "stack_heights": heights,  # index = height, value = episode count
        "taxonomy": dict(
            sorted(taxonomy.items(), key=lambda kv: -kv[1])
        ),
        "wall_total_s": round(time.monotonic() - t_start, 1),
        "policy": policy_factory.__name__,
        "mujoco": mujoco.__version__,
        "git_commit": _git_commit(),
        # The literal invocation when available (run_eval.py passes argv);
        # the reconstruction below misses flags run_eval() never sees
        # (--policy, --perception-noise, --part-scale).
        "command": command or (
            f"python run_eval.py --n {n} --seed-start {seed_start} "
            f"--tip-probability {tip_probability} --out {out}"
        ),
    }
    with open(out / "meta.json", "w") as fh:
        json.dump(meta, fh, indent=2)
    print(
        f"\n{k}/{n} success = {k / n:.1%}  (95% Wilson: {lo:.1%}-{hi:.1%})  "
        f"wall {meta['wall_total_s']}s"
    )
    return meta
