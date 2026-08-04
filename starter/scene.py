"""Composed scene for the Relling take-home: UR5e + Robotiq 2F-85 + three cylinders.

Scaffolding only — the spawn randomization, success judge, baseline policy, and
evaluation harness are yours. `make_spec()` returns a live MjSpec so you can
modify the scene programmatically before compiling.
"""

from pathlib import Path

import mujoco

MENAGERIE = Path(__file__).parent / "third_party" / "mujoco_menagerie"

NOMINAL_RADIUS = 0.015
NOMINAL_HALF_HEIGHT = 0.03
CYLINDER_RADIUS = NOMINAL_RADIUS
CYLINDER_HALF_HEIGHT = NOMINAL_HALF_HEIGHT


def apply_part_scale(scale: float) -> None:
    """Held-out perturbation (stretch): scale the true part geometry.

    The world and judge follow these constants at call time; the baseline
    policy deliberately does NOT — it keeps nominal-part beliefs, which is
    the point of the experiment. Call before make_model().
    """
    global CYLINDER_RADIUS, CYLINDER_HALF_HEIGHT
    CYLINDER_RADIUS = NOMINAL_RADIUS * scale
    CYLINDER_HALF_HEIGHT = NOMINAL_HALF_HEIGHT * scale
CYLINDER_NAMES = ("cyl0", "cyl1", "cyl2")
CYLINDER_SPAWN = ((0.45, -0.15), (0.55, 0.0), (0.45, 0.15))
TARGET_POS = (0.35, 0.35, 0.0)

HOME_QPOS_ARM = (-1.5708, -1.5708, 1.5708, -1.5708, -1.5708, 0.0)
ARM_JOINTS = (
    "shoulder_pan_joint",
    "shoulder_lift_joint",
    "elbow_joint",
    "wrist_1_joint",
    "wrist_2_joint",
    "wrist_3_joint",
)
GRIPPER_ACTUATOR = "2f85/fingers_actuator"  # ctrl range 0 (open) .. 255 (closed)


def make_spec() -> mujoco.MjSpec:
    arm = mujoco.MjSpec.from_file(str(MENAGERIE / "universal_robots_ur5e" / "ur5e.xml"))
    gripper = mujoco.MjSpec.from_file(str(MENAGERIE / "robotiq_2f85" / "2f85.xml"))

    # The 2F-85 model relies on these solver settings for stable grasp contact;
    # attach() would otherwise silently keep the arm model's defaults.
    arm.option.impratio = gripper.option.impratio
    arm.option.cone = gripper.option.cone

    arm.site("attachment_site").attach_body(gripper.body("base_mount"), "2f85/", "")

    # The arm model's home keyframe predates the attach; rebuild state via reset_home().
    for key in list(arm.keys):
        arm.delete(key)

    # Offscreen framebuffer large enough for render_episode.py snapshots
    # (MuJoCo's default is 640x480).
    arm.visual.global_.offwidth = 1280
    arm.visual.global_.offheight = 960

    world = arm.worldbody
    world.add_light(pos=[0, 0, 2.5], dir=[0, 0, -1])
    world.add_geom(
        name="floor",
        type=mujoco.mjtGeom.mjGEOM_PLANE,
        size=[1.5, 1.5, 0.05],
        rgba=[0.92, 0.92, 0.94, 1.0],
    )

    for name, (x, y) in zip(CYLINDER_NAMES, CYLINDER_SPAWN):
        body = world.add_body(name=name, pos=[x, y, CYLINDER_HALF_HEIGHT])
        body.add_freejoint(name=f"{name}_free")
        # condim 6 + rolling friction: MuJoCo's default (condim 3) has no
        # rolling resistance, so a tipped cylinder rolls forever — observed
        # rolling clean off the table. NO priority here: the gripper pads carry
        # priority=1 with tuned contact params that grasping depends on — a
        # cylinder priority would tie and dilute them (observed: 0 lifts).
        # Floor contact still mixes to condim 6 + max friction, which is all
        # rolling resistance needs.
        body.add_geom(
            name=f"{name}_geom",
            type=mujoco.mjtGeom.mjGEOM_CYLINDER,
            size=[CYLINDER_RADIUS, CYLINDER_HALF_HEIGHT, 0],
            rgba=[0.75, 0.22, 0.17, 1.0],
            condim=6,
            friction=[1.0, 0.005, 0.001],
        )

    world.add_site(
        name="target",
        pos=list(TARGET_POS),
        type=mujoco.mjtGeom.mjGEOM_CYLINDER,
        size=[0.05, 0.001, 0],
        rgba=[0.18, 0.43, 0.31, 0.35],
    )
    return arm


def make_model() -> mujoco.MjModel:
    return make_spec().compile()


def reset_home(model: mujoco.MjModel, data: mujoco.MjData) -> None:
    """Arm to the ready pose, gripper open, cylinders at their spawn positions."""
    mujoco.mj_resetData(model, data)
    for joint, q in zip(ARM_JOINTS, HOME_QPOS_ARM):
        data.joint(joint).qpos[0] = q
        data.actuator(joint.removesuffix("_joint")).ctrl[0] = q
    for name, (x, y) in zip(CYLINDER_NAMES, CYLINDER_SPAWN):
        data.joint(f"{name}_free").qpos[:] = [x, y, CYLINDER_HALF_HEIGHT, 1, 0, 0, 0]
    mujoco.mj_forward(model, data)
