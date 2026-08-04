"""Part A, half 1: seeded episode initialization with randomized poses.

One integer seed fully determines the initial world state. All randomness flows
from a single `np.random.default_rng(seed)`, so any episode is exactly replayable.

Orientation randomization: each cylinder independently spawns tipped over
(lying on its side, random heading) with probability TIP_PROBABILITY, else
upright with random yaw. Upright yaw is physically near-meaningless for a
symmetric cylinder but is sampled and recorded anyway. The tip probability is
a declared distribution parameter — part of the initial-condition scheme the
gate analysis (Part D) can vary.

The episode's official initial condition is the *settled* pose (1 s of physics),
not the sampled pose. If settling produces an invalid world (a cylinder rolled
out of region / into a neighbor / into a non-stable state), the layout is
redrawn from the same generator — determinism is preserved.
"""

from dataclasses import dataclass

import numpy as np
import mujoco

import scene

# Spawn region: a rectangle on the work surface in front of the arm.
# Chosen to sit well inside UR5e reach (~0.85 m) and clear of the target
# disc at (0.35, 0.35, r=0.05).
SPAWN_X = (0.35, 0.60)
SPAWN_Y = (-0.25, 0.25)

# Minimum center-to-center distance at sample time. The 2F-85's open fingers
# span ~85 mm; closer than this and a neighbor can block the grasp. Settling
# (esp. rolling tipped cylinders) may shrink it slightly — SEPARATION_FLOOR is
# the post-settle minimum we accept.
MIN_SEPARATION = 0.08
SEPARATION_FLOOR = 0.05

TIP_PROBABILITY = 0.2  # per-cylinder chance of spawning on its side

MAX_SAMPLE_TRIES = 200  # per-cylinder position rejection
MAX_WORLD_TRIES = 20  # whole-layout redraws if settling goes bad
SETTLE_TIME = 1.0  # seconds of physics before the state counts as "initial"
REGION_SLACK = 0.05  # meters a cylinder may drift/roll outside the region

# Settled-state classification thresholds (|world z-component of cylinder axis|).
_UPRIGHT_AXIS_Z = 0.95
_FLAT_AXIS_Z = 0.10
_HEIGHT_TOL = 0.005


@dataclass
class EpisodeInit:
    """Everything needed to describe (and replay) an episode's starting state."""

    seed: int
    tip_probability: float
    sampled_poses: list  # per cylinder: [x, y, yaw, tipped(bool)] as drawn
    settled_qpos: dict  # per cylinder: 7-dof free-joint qpos after settling
    spawn_states: dict  # per cylinder: "upright" | "tipped"
    world_tries: int  # how many layout redraws settling forced (1 = first try)


def _quat_upright(yaw: float) -> list:
    return [np.cos(yaw / 2.0), 0.0, 0.0, np.sin(yaw / 2.0)]


def _quat_tipped(heading: float) -> list:
    """Cylinder axis horizontal, pointing along `heading` in the xy plane."""
    pitch = np.array([np.cos(np.pi / 4), 0.0, np.sin(np.pi / 4), 0.0])  # 90° about y
    yaw_q = np.array([np.cos(heading / 2.0), 0.0, 0.0, np.sin(heading / 2.0)])
    out = np.empty(4)
    mujoco.mju_mulQuat(out, yaw_q, pitch)
    return out.tolist()


def _axis_z(qpos7) -> float:
    """|world z-component| of the cylinder's own axis (local z) — 1 upright, 0 flat."""
    w, x, y, z = qpos7[3:7]
    # third column of the rotation matrix, z entry:
    return abs(1.0 - 2.0 * (x * x + y * y))


def classify(qpos7) -> str | None:
    """'upright' | 'tipped' if the pose is a clean stable state, else None."""
    az = _axis_z(qpos7)
    height = qpos7[2]
    if az > _UPRIGHT_AXIS_Z and abs(height - scene.CYLINDER_HALF_HEIGHT) < _HEIGHT_TOL:
        return "upright"
    if az < _FLAT_AXIS_Z and abs(height - scene.CYLINDER_RADIUS) < _HEIGHT_TOL:
        return "tipped"
    return None


def sample_spawns(rng: np.random.Generator, tip_probability: float) -> list:
    """Draw [x, y, yaw, tipped] per cylinder; rejection-sample separation."""
    placed = []
    for _ in scene.CYLINDER_NAMES:
        for _ in range(MAX_SAMPLE_TRIES):
            x = rng.uniform(*SPAWN_X)
            y = rng.uniform(*SPAWN_Y)
            if all(np.hypot(x - p[0], y - p[1]) >= MIN_SEPARATION for p in placed):
                yaw = rng.uniform(0.0, 2.0 * np.pi)
                tipped = bool(rng.random() < tip_probability)
                placed.append((x, y, yaw, tipped))
                break
        else:
            raise RuntimeError(
                f"could not place cylinder after {MAX_SAMPLE_TRIES} tries "
                f"(region too small for MIN_SEPARATION={MIN_SEPARATION})"
            )
    return placed


def _validate_settled(settled: dict) -> bool:
    """Settled world is acceptable: stable states, in region, separated."""
    xy = []
    for q in settled.values():
        if classify(q) is None:
            return False
        x, y = q[0], q[1]
        if not (SPAWN_X[0] - REGION_SLACK <= x <= SPAWN_X[1] + REGION_SLACK):
            return False
        if not (SPAWN_Y[0] - REGION_SLACK <= y <= SPAWN_Y[1] + REGION_SLACK):
            return False
        xy.append((x, y))
    for i in range(len(xy)):
        for j in range(i + 1, len(xy)):
            if np.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1]) < SEPARATION_FLOOR:
                return False
    return True


def reset_episode(
    model: mujoco.MjModel,
    data: mujoco.MjData,
    seed: int,
    tip_probability: float = TIP_PROBABILITY,
) -> EpisodeInit:
    """Reset to home, place cylinders per `seed`, settle, validate, report."""
    rng = np.random.default_rng(seed)
    for attempt in range(1, MAX_WORLD_TRIES + 1):
        scene.reset_home(model, data)
        spawns = sample_spawns(rng, tip_probability)

        for name, (x, y, yaw, tipped) in zip(scene.CYLINDER_NAMES, spawns):
            if tipped:
                z = scene.CYLINDER_RADIUS
                quat = _quat_tipped(yaw)
            else:
                z = scene.CYLINDER_HALF_HEIGHT
                quat = _quat_upright(yaw)
            joint = data.joint(f"{name}_free")
            joint.qpos[:] = [x, y, z, *quat]
            joint.qvel[:] = 0.0
        mujoco.mj_forward(model, data)

        for _ in range(int(SETTLE_TIME / model.opt.timestep)):
            mujoco.mj_step(model, data)

        settled = {
            name: data.joint(f"{name}_free").qpos.copy().tolist()
            for name in scene.CYLINDER_NAMES
        }
        if _validate_settled(settled):
            return EpisodeInit(
                seed=seed,
                tip_probability=tip_probability,
                sampled_poses=[list(s) for s in spawns],
                settled_qpos=settled,
                spawn_states={name: classify(q) for name, q in settled.items()},
                world_tries=attempt,
            )
    raise RuntimeError(f"seed {seed}: no valid settled world in {MAX_WORLD_TRIES} tries")
