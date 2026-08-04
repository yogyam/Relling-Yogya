"""Differential IK for the UR5e arm (Decision 1, Option A).

Every control step: compare where the pinch site is vs. where we want it,
compute the small joint nudge that closes the gap (damped least squares on the
site Jacobian), and feed the nudged target to the position actuators. The
gripper is kept pointing straight down at all times; yaw is held fixed (grasp
yaw is irrelevant for symmetric cylinders — declared assumption).

Deliberately simple: no collision avoidance, no joint-limit finesse beyond
clamping, no retries. Its imperfections become honest episode failures.
"""

import numpy as np
import mujoco

import scene

# Default tool orientation: z-axis straight down, x-axis along world x.
# step_toward accepts any target rotation; v1 waypoints all use this default,
# so v1 trajectories are bit-identical to the pre-orientation-support code.
R_DOWN = np.array([[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0]]).T

_DAMPING = 1e-4  # least-squares damping (keeps solutions sane near singularities)
_MAX_DQ = 0.004  # rad per control step (500 Hz -> ~2 rad/s max joint speed)
_ROT_WEIGHT = 0.5  # orientation error weight relative to position


class ArmController:
    def __init__(self, model: mujoco.MjModel):
        self.model = model
        self.site_id = model.site("2f85/pinch").id
        self.dof_ids = [model.joint(j).dofadr[0] for j in scene.ARM_JOINTS]
        self.qpos_ids = [model.joint(j).qposadr[0] for j in scene.ARM_JOINTS]
        acts = [j.removesuffix("_joint") for j in scene.ARM_JOINTS]
        self.act_ids = [model.actuator(a).id for a in acts]
        lo = model.jnt_range[:, 0]
        hi = model.jnt_range[:, 1]
        jids = [model.joint(j).id for j in scene.ARM_JOINTS]
        self.q_lo, self.q_hi = lo[jids], hi[jids]
        self.q_target = None  # integrated joint-space target, init at reset

    def reset(self, data: mujoco.MjData) -> None:
        """Call after the world is reset, before the first step_toward."""
        self.q_target = data.qpos[self.qpos_ids].copy()

    def pinch_pos(self, data: mujoco.MjData) -> np.ndarray:
        return data.site_xpos[self.site_id].copy()

    def step_toward(self, data: mujoco.MjData, target_pos, target_R=None) -> tuple:
        """One control step toward target_pos with tool rotation target_R
        (default: pointing straight down).

        Sets arm actuator targets; caller steps the physics. Returns
        (position error m, orientation error rad-ish).
        """
        Rd = R_DOWN if target_R is None else target_R
        pos = data.site_xpos[self.site_id]
        R = data.site_xmat[self.site_id].reshape(3, 3)
        err_p = np.asarray(target_pos, dtype=float) - pos
        err_r = 0.5 * (
            np.cross(R[:, 0], Rd[:, 0])
            + np.cross(R[:, 1], Rd[:, 1])
            + np.cross(R[:, 2], Rd[:, 2])
        )
        err = np.concatenate([err_p, _ROT_WEIGHT * err_r])

        jacp = np.zeros((3, self.model.nv))
        jacr = np.zeros((3, self.model.nv))
        mujoco.mj_jacSite(self.model, data, jacp, jacr, self.site_id)
        J = np.vstack([jacp, jacr])[:, self.dof_ids]

        dq = J.T @ np.linalg.solve(J @ J.T + _DAMPING * np.eye(6), err)
        worst = np.abs(dq).max()
        if worst > _MAX_DQ:
            dq *= _MAX_DQ / worst

        self.q_target = np.clip(self.q_target + dq, self.q_lo, self.q_hi)
        for i, aid in enumerate(self.act_ids):
            data.ctrl[aid] = self.q_target[i]
        return float(np.linalg.norm(err_p)), float(np.linalg.norm(err_r))
