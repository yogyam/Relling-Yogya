"""The judge's exam — run `python check_judge.py`.

Hand-built world states with known correct verdicts. Each fixture teleports
cylinders into a configuration, runs the judge (which settles 2 s first), and
asserts the ruling a sensible human would give. Every fixture's *post-settle*
state — the state the verdict actually applied to — is rendered to
renders/judge_fixtures/ for visual audit.
"""

from pathlib import Path

import numpy as np
import mujoco
from PIL import Image

import scene
import judge
import render_episode

OUT = Path(__file__).parent / "renders" / "judge_fixtures"

UP = [1.0, 0.0, 0.0, 0.0]
TIPPED = [np.cos(np.pi / 4), 0.0, np.sin(np.pi / 4), 0.0]  # axis horizontal
TX, TY = scene.TARGET_POS[0], scene.TARGET_POS[1]


def set_world(model, data, poses, vels=None):
    """poses: {name: (x, y, z, quat)}; vels: {name: linear-velocity 3-vector}."""
    scene.reset_home(model, data)
    for name, (x, y, z, quat) in poses.items():
        j = data.joint(f"{name}_free")
        j.qpos[:] = [x, y, z, *quat]
        j.qvel[:] = 0.0
    if vels:
        for name, v in vels.items():
            data.joint(f"{name}_free").qvel[:3] = v
    mujoco.mj_forward(model, data)


def stack(dx0=0.0, dy0=0.0, dx1=0.0, dy1=0.0, dx2=0.0, dy2=0.0):
    """A 3-stack based at the target with per-layer horizontal offsets."""
    return {
        "cyl0": (TX + dx0, TY + dy0, 0.03, UP),
        "cyl1": (TX + dx0 + dx1, TY + dy0 + dy1, 0.09, UP),
        "cyl2": (TX + dx0 + dx1 + dx2, TY + dy0 + dy1 + dy2, 0.15, UP),
    }


FIXTURES = [
    # (name, poses, vels, expect_success, expect_height, expect_reason-or-None)
    ("perfect_stack", stack(), None, True, 3, None),
    # 4 mm alternating offsets: sloppy but a human calls it stacked.
    ("sloppy_stack", stack(dx1=0.004, dx2=-0.004), None, True, 3, None),
    # Right tower, wrong address: 60 mm from target (> 25 mm tol).
    ("stack_off_target", stack(dx0=0.06), None, False, 0, "no_base_at_target"),
    # Two on target, one loose elsewhere.
    (
        "two_stack_plus_loose",
        {
            "cyl0": (TX, TY, 0.03, UP),
            "cyl1": (TX, TY, 0.09, UP),
            "cyl2": (0.50, 0.00, 0.03, UP),
        },
        None,
        False,
        2,
        "partial_stack_2",
    ),
    # Three scattered uprights, none at the target.
    (
        "scattered",
        {
            "cyl0": (0.45, -0.15, 0.03, UP),
            "cyl1": (0.55, 0.00, 0.03, UP),
            "cyl2": (0.45, 0.15, 0.03, UP),
        },
        None,
        False,
        0,
        "no_base_at_target",
    ),
    # All lying on their sides.
    (
        "all_tipped",
        {
            "cyl0": (0.45, -0.10, 0.015, TIPPED),
            "cyl1": (0.55, 0.00, 0.015, TIPPED),
            "cyl2": (0.45, 0.10, 0.015, TIPPED),
        },
        None,
        False,
        0,
        "no_base_at_target",
    ),
    # Top cylinder half off the edge (15 mm = its radius): must fail — either
    # physics topples it during the settle or alignment (10 mm) rejects it.
    ("top_half_off", stack(dx2=0.015), None, False, None, None),
    # THE STAR WITNESS: geometry is a perfect stack at t=0, but the top is
    # flying off sideways. A judge without the settle wait would pass this
    # frozen photo. Ours must watch it fall and rule fail. (1.0 m/s: friction
    # stops anything below ~0.54 m/s within the 15 mm rim — measured: a
    # 0.3 m/s kick slides only 4.8 mm and the stack legitimately survives.)
    ("top_flying_off", stack(), {"cyl2": [1.0, 0.0, 0.0]}, False, None, None),
    # Thresholds must bind: base 27 mm from target (> 25 mm tol).
    ("base_just_outside", stack(dx0=0.027), None, False, 0, "no_base_at_target"),
    # Mid cylinder 12 mm off (> 10 mm align tol) but physically stable.
    ("mid_misaligned_12mm", stack(dx1=0.012), None, False, 1, "partial_stack_1"),
]


def main() -> None:
    model = scene.make_model()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(
        model, height=render_episode.HEIGHT, width=render_episode.WIDTH
    )
    cam = render_episode.make_camera()
    cam.lookat[:] = [scene.TARGET_POS[0], scene.TARGET_POS[1], 0.10]
    cam.distance = 1.0
    OUT.mkdir(parents=True, exist_ok=True)

    failures = []
    for name, poses, vels, want_success, want_height, want_reason in FIXTURES:
        set_world(model, data, poses, vels)
        v = judge.judge(model, data)

        renderer.update_scene(data, camera=cam)
        Image.fromarray(renderer.render()).save(OUT / f"{name}.png")

        problems = []
        if v.success != want_success:
            problems.append(f"success={v.success}, wanted {want_success}")
        if want_height is not None and v.stack_height != want_height:
            problems.append(f"height={v.stack_height}, wanted {want_height}")
        if want_reason is not None and v.failure_reason != want_reason:
            problems.append(f"reason={v.failure_reason}, wanted {want_reason}")
        status = "ok" if not problems else "FAIL: " + "; ".join(problems)
        print(
            f"{name:22s} -> success={v.success!s:5s} height={v.stack_height} "
            f"reason={v.failure_reason}   [{status}]"
        )
        if problems:
            failures.append(name)

    renderer.close()
    if failures:
        raise SystemExit(f"\nJUDGE EXAM FAILED: {failures}")
    print(f"\nrenders in {OUT}")
    print("CHECK JUDGE OK")


if __name__ == "__main__":
    main()
