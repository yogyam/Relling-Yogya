"""Part A, half 2: the success judge.

`judge(model, data)` inspects the world at the end of an episode and returns a
Verdict. Success means: after a 2 s settling wait, all three cylinders form a
single upright tower whose base sits on the target — and everything is at rest.

Design notes (defended in the memo):
- The judge settles the world itself (steps physics for JUDGE_SETTLE_TIME) so a
  tower propped by the gripper, or teetering, is exposed. Assumption: the caller
  has parked the arm clear of the stack first; the judge never moves the robot.
- Partial stacks are reported via `stack_height` (0-3) — never blended into the
  boolean `success`.
- At-rest thresholds were calibrated against the measured jitter floor of a
  settled scene (speed 3.1e-4 m/s, spin 1.9e-2 rad/s at timestep 0.002):
  thresholds sit ~30x above the hum, orders of magnitude below real motion.
- Stacked layers sink slightly into each other (soft contacts): a hand-built
  perfect stack settles at 29.6/89.3/149.1 mm vs nominal 30/90/150. The
  +/-10 mm layer tolerance absorbs this with margin.
"""

from dataclasses import dataclass, field

import numpy as np
import mujoco

import scene

JUDGE_SETTLE_TIME = 2.0  # seconds of physics before judging

# Geometry tolerances.
# Layer heights derive from the TRUE part size at judge time (h, 3h, 5h), so
# the judge stays fair under the part-scale perturbation experiment.
LAYER_TOL = 0.010  # m, on center height


def _layer_heights() -> tuple:
    h = scene.CYLINDER_HALF_HEIGHT
    return (h, 3 * h, 5 * h)
ALIGN_TOL = 0.010  # m, horizontal offset between a cylinder and the one below
TARGET_TOL = 0.025  # m, horizontal offset of the base cylinder from the target
TILT_TOL_DEG = 10.0  # max lean from vertical

# At-rest thresholds (see calibration note above).
SPEED_TOL = 0.01  # m/s
SPIN_TOL = 0.5  # rad/s


@dataclass
class Verdict:
    success: bool
    stack_height: int  # 0-3: length of the upright chain based at the target
    failure_reason: str | None  # None on success
    details: dict = field(default_factory=dict)  # measured numbers for triage


def _tilt_deg(qpos7) -> float:
    """Angle of the cylinder's axis from vertical, degrees."""
    w, x, y, z = qpos7[3:7]
    axis_z = 1.0 - 2.0 * (x * x + y * y)  # z-component of rotated local z axis
    return float(np.degrees(np.arccos(np.clip(abs(axis_z), -1.0, 1.0))))


def judge(model: mujoco.MjModel, data: mujoco.MjData) -> Verdict:
    for _ in range(int(JUDGE_SETTLE_TIME / model.opt.timestep)):
        mujoco.mj_step(model, data)

    tx, ty = scene.TARGET_POS[0], scene.TARGET_POS[1]
    cyl = {}
    for name in scene.CYLINDER_NAMES:
        j = data.joint(f"{name}_free")
        q, v = j.qpos, j.qvel
        cyl[name] = {
            "x": float(q[0]),
            "y": float(q[1]),
            "z_mm": float(q[2] * 1000),
            "tilt_deg": round(_tilt_deg(q), 2),
            "speed": float(np.linalg.norm(v[:3])),
            "spin": float(np.linalg.norm(v[3:])),
        }

    moving = [
        n for n, c in cyl.items() if c["speed"] > SPEED_TOL or c["spin"] > SPIN_TOL
    ]

    # Build the chain: base = upright cylinder at layer-1 height on the target;
    # each next layer = upright cylinder at the right height, aligned with the
    # one below. Ties broken by smallest offset.
    chain = []
    remaining = set(cyl)
    for layer, z_nom in enumerate(_layer_heights()):
        candidates = []
        for n in remaining:
            c = cyl[n]
            if c["tilt_deg"] > TILT_TOL_DEG:
                continue
            if abs(c["z_mm"] / 1000 - z_nom) > LAYER_TOL:
                continue
            if layer == 0:
                off = float(np.hypot(c["x"] - tx, c["y"] - ty))
                if off > TARGET_TOL:
                    continue
            else:
                below = cyl[chain[-1]]
                off = float(np.hypot(c["x"] - below["x"], c["y"] - below["y"]))
                if off > ALIGN_TOL:
                    continue
            candidates.append((off, n))
        if not candidates:
            break
        _, best = min(candidates)
        chain.append(best)
        remaining.discard(best)

    stack_height = len(chain)
    details = {
        "cylinders": cyl,
        "chain": chain,
        "settle_time_s": JUDGE_SETTLE_TIME,
    }

    if moving:
        return Verdict(False, stack_height, "not_at_rest", details)
    if stack_height == 3:
        return Verdict(True, 3, None, details)
    reason = {
        0: "no_base_at_target",
        1: "partial_stack_1",
        2: "partial_stack_2",
    }[stack_height]
    return Verdict(False, stack_height, reason, details)
