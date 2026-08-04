"""Part B: the scripted baseline policy — deliberately unglamorous.

Game plan (per journal): read true cylinder poses once per pick (perfect
eyesight — declared assumption), skip tipped cylinders entirely (their episodes
fail honestly), take upright cylinders nearest-to-hand first, and for each:
hover above -> descend -> close -> lift -> carry over target -> descend to the
layer height -> open -> retreat. Then park clear of the stack for the judge.

Open-loop between waypoints; no retries, no recovery. Grasping is REAL contact
physics for now (Decision 2: timeboxed attempt before any weld fallback).
"""

from dataclasses import dataclass, field

import numpy as np
import mujoco

import scene
import ik

GRIPPER_OPEN = 0.0
# Narrow the fingers convincingly but stay clear of a 30 mm part — with the
# weld carrying the load, pad contact fights the constraint (measured: ctrl 128
# already shoves the part 3 mm; 100 leaves ~20 mm clearance).
GRIPPER_CLOSED = 100.0

# Kinematic-grasp fallback (packet's grasping rule, taken after a timeboxed
# real-physics attempt — see journal). On close, the nearest capturable
# cylinder is frozen into the gripper frame and follows it exactly until open.
# (A MjSpec weld equality was tried first: the constraint solver yanked the
# part toward a subtly wrong stored pose, destroying finished stacks.)
# CAPTURE_RADIUS is the honesty knob: the pinch must genuinely be at the part
# or the grasp still fails.
CAPTURE_RADIUS = 0.020  # m, pinch-to-cylinder-center distance to capture

HOVER_Z = 0.20  # travel height for the pinch site
APPROACH_Z = 0.10  # staging height: makes the final descend short and vertical
                   # (a single long descend bows sideways and clips the part)
GRASP_Z = 0.030  # pinch at cylinder center height when grasping

# The policy's BELIEFS about part geometry — deliberately frozen at nominal
# (not read from scene constants) so the part-scale perturbation experiment
# measures an unmodified policy meeting different parts.
BELIEF_HALF_HEIGHT = 0.030
BELIEF_RADIUS = 0.015
BELIEF_LAYER_SPACING = 0.060
LIFT_Z = 0.22
PLACE_CLEARANCE = 0.004  # release with this much air under the cylinder
PARK = (0.15, -0.30, 0.35)

WAYPOINT_TOL = 0.008  # m
GRASP_TOL = 0.003  # m — tighter for the grasp descend; off-center closes shove
WAYPOINT_TIMEOUT = 4.0  # s per waypoint
# Grip changes are commanded instantly. A ramped close was tried and abandoned:
# ramping a position servo keeps its tracking error (hence force) tiny, so the
# fingers creep and never reach the part in time — 0 pad contacts vs 11 with an
# instant command. The squeeze-shove an instant close can cause is contained by
# the tight GRASP_TOL approach; the in-grip ride-up is measured and corrected
# at placement (grip_dz).
GRIP_WAIT = 1.0  # s to let fingers travel (~0.3 s) and the grasp settle

EPISODE_TIME_LIMIT = 60.0  # s, generous; harness records actual duration


@dataclass
class EpisodeTrace:
    """What the policy did — feeds the per-episode record in Part C."""

    picks_attempted: int = 0
    picks_lifted: int = 0  # cylinder actually left the table in our hand
    skipped_tipped: list = field(default_factory=list)
    events: list = field(default_factory=list)  # (sim_time, message)
    timed_out: bool = False


class BaselinePolicy:
    def __init__(self, model: mujoco.MjModel):
        self.model = model
        self.arm = ik.ArmController(model)
        self.grip_act = model.actuator(scene.GRIPPER_ACTUATOR).id
        self.grip_body = model.body("2f85/base").id
        self.held = None  # (cylinder name, rel_pos, rel_quat) while carrying

    # -- primitives ---------------------------------------------------------
    # v1 keeps the original 60 s (it never hit it — freeze intact); v2 does
    # 10-15 s of legitimate extra work per flip and needs the headroom.
    TIME_LIMIT = EPISODE_TIME_LIMIT

    def _time_up(self, data) -> bool:
        return data.time - self.t0 > self.TIME_LIMIT

    def _step(self, data) -> None:
        """One physics step; a held cylinder is pinned to the gripper frame."""
        mujoco.mj_step(self.model, data)
        if self.held is not None:
            name, rel_p, rel_q = self.held
            p1, q1 = data.xpos[self.grip_body], data.xquat[self.grip_body]
            wp = np.empty(3)
            mujoco.mju_rotVecQuat(wp, rel_p, q1)
            wq = np.empty(4)
            mujoco.mju_mulQuat(wq, q1, rel_q)
            j = data.joint(f"{name}_free")
            j.qpos[:3] = p1 + wp
            j.qpos[3:7] = wq
            j.qvel[:] = 0.0

    def _goto(self, data, target, trace, tol=WAYPOINT_TOL, R=None, rot_tol=0.12) -> bool:
        """Drive the pinch site to target (optionally with tool rotation R).

        Completion requires orientation convergence only when a non-default R
        is requested — the default path is identical to v1 (frozen fixture).
        """
        deadline = data.time + WAYPOINT_TIMEOUT
        while data.time < deadline and not self._time_up(data):
            perr, rerr = self.arm.step_toward(data, target, R)
            self._step(data)
            if perr < tol and (R is None or rerr < rot_tol):
                return True
        trace.events.append(
            (round(data.time - self.t0, 2), f"waypoint timeout -> {np.round(target, 3)}")
        )
        if self.resync_on_timeout:
            # A blocked waypoint leaves the integrated joint target saturated
            # far from the real arm — every later waypoint then stalls too
            # (observed cascade). Resync target to reality and move on.
            self.arm.q_target = data.qpos[self.arm.qpos_ids].copy()
        return False

    def _grip(self, data, ctrl) -> str | None:
        """Command the fingers; capture/release the load. Returns captured name."""
        if ctrl > GRIPPER_OPEN:
            self._capture_nearest(data)
        else:
            self.held = None
        data.ctrl[self.grip_act] = ctrl
        end = data.time + GRIP_WAIT
        while data.time < end:
            self._step(data)
        return self.held[0] if self.held else None

    def _axis_distance(self, data, name, point) -> float:
        """Distance from a point to the cylinder's center-line segment — a
        grasp anywhere along the body is a genuine grasp (needed for the v2
        end-grasp; identical to center distance for v1's center grasps)."""
        c = self._true_pos(data, name)
        a = self._cyl_axis(data, name)
        t = float(np.clip(np.dot(point - c, a), -scene.CYLINDER_HALF_HEIGHT,
                          scene.CYLINDER_HALF_HEIGHT))
        return float(np.linalg.norm(point - (c + t * a)))

    def _capture_nearest(self, data) -> None:
        """Freeze the nearest capturable cylinder into the gripper frame."""
        pinch = self.arm.pinch_pos(data)
        best, best_d = None, CAPTURE_RADIUS
        for n in scene.CYLINDER_NAMES:
            d = self._axis_distance(data, n, pinch)
            if d < best_d:
                best, best_d = n, d
        if best is None:
            self.held = None
            return
        b2 = self.model.body(best).id
        p1, q1 = data.xpos[self.grip_body], data.xquat[self.grip_body]
        p2, q2 = data.xpos[b2], data.xquat[b2]
        q1c = np.array([q1[0], -q1[1], -q1[2], -q1[3]])
        rel_q = np.empty(4)
        mujoco.mju_mulQuat(rel_q, q1c, q2)
        rel_p = np.empty(3)
        mujoco.mju_rotVecQuat(rel_p, p2 - p1, q1c)
        self.held = (best, rel_p, rel_q)

    def _true_pos(self, data, name) -> np.ndarray:
        """Ground-truth position — used by PHYSICS (capture), never noised."""
        return data.joint(f"{name}_free").qpos[:3].copy()

    def _cyl_pos(self, data, name) -> np.ndarray:
        """PERCEIVED position — what the policy aims at. The degraded variant
        overrides this one; the capture check stays on _true_pos so noisy
        eyes cannot create physically impossible grasps."""
        return self._true_pos(data, name)

    def _upright(self, data, name) -> bool:
        w, x, y, z = data.joint(f"{name}_free").qpos[3:7]
        return abs(1.0 - 2.0 * (x * x + y * y)) > 0.95

    # -- v2: stand a tipped cylinder up (Strategy B) ------------------------
    TIPPED_GRASP_Z = 0.020  # pinch height when grabbing a lying part: center
    # is at 15 mm; grabbing 5 mm high keeps fingertips off the floor and stays
    # well inside the 20 mm capture radius.
    ROTATE_Z = 0.25  # do the 90° reorient up here, far from everything
    GRASP_AXIAL_OFF = 0.020  # m along the part's axis: grab near the end so
    # the part hangs below the hand after the tilt (wrist clears the table)

    def _dof_axis(self, data, jname) -> np.ndarray:
        """World-frame rotation axis of an arm joint at the current pose."""
        jid = self.model.joint(jname).id
        return data.xaxis[self.model.jnt_dofadr[jid]].copy()

    def _ramp_joint(self, data, jname, delta, duration=1.2) -> float:
        """Joint-space move: ramp ONE joint's target by delta. No IK involved.
        Returns the delta actually applied (may be clipped by joint limits)."""
        i = scene.ARM_JOINTS.index(jname)
        arm = self.arm
        start = arm.q_target[i]
        end = float(np.clip(start + delta, arm.q_lo[i], arm.q_hi[i]))
        steps = max(1, int(duration / self.model.opt.timestep))
        per = (end - start) / steps
        for _ in range(steps):
            arm.q_target[i] += per
            for k, aid in enumerate(arm.act_ids):
                data.ctrl[aid] = arm.q_target[k]
            self._step(data)
        settle = data.time + 0.3
        while data.time < settle:
            self._step(data)
        return end - start

    def _cyl_axis(self, data, name) -> np.ndarray:
        q = data.joint(f"{name}_free").qpos
        return np.array(
            [
                2 * (q[4] * q[6] + q[3] * q[5]),
                2 * (q[5] * q[6] - q[3] * q[4]),
                1 - 2 * (q[4] * q[4] + q[5] * q[5]),
            ]
        )

    def _stand_up(self, data, name, trace) -> None:
        """Grab a lying cylinder, rotate it vertical in open air, set it down
        upright in place, release. After this it is a normal upright pick.

        The approach is the PROVEN straight-down one — no yawed grasp (a
        yaw-aligned approach made the IK swing the base 120° into a contorted
        pose; with kinematic capture, finger-vs-axis alignment doesn't affect
        the grasp — noted in the honesty ledger). The 90° reorient is done in
        JOINT space — two single-hinge moves that cannot be planned wrong:
        (1) spin wrist_3 until the part's axis is perpendicular to the tilt
        hinge's axis, (2) turn that hinge exactly 90°. Task-space IK never
        plans a rotation (three earlier attempts stalled/pretzeled/collided —
        journal); afterwards it only TRANSLATES while holding the tilted
        orientation, starting from zero orientation error.
        """
        q = data.joint(f"{name}_free").qpos
        x, y = float(q[0]), float(q[1])

        t = round(data.time - self.t0, 2)
        trace.events.append((t, f"stand-up {name} at ({x:.3f},{y:.3f})"))
        self._goto(data, (x, y, HOVER_Z), trace)

        # Align the finger gap PERPENDICULAR to the lying part's axis before
        # descending — without this the open fingers land on the part and kick
        # it away (measured: capture misses on seed 12). Joint-space spin of
        # wrist_3 (pinch stays put), then IK merely HOLDS the yawed rotation.
        pr = data.geom_xpos[self.model.geom("2f85/right_pad1").id]
        pl = data.geom_xpos[self.model.geom("2f85/left_pad1").id]
        gap = pr - pl
        gap_ang = float(np.arctan2(gap[1], gap[0]))
        a0 = self._cyl_axis(data, name)
        want_ang = float(np.arctan2(a0[0], -a0[1]))  # perpendicular to axis
        psi = ((want_ang - gap_ang + np.pi / 2) % np.pi) - np.pi / 2
        s3 = np.sign(self._dof_axis(data, "wrist_3_joint")[2]) or 1.0
        self._ramp_joint(data, "wrist_3_joint", psi * s3, duration=0.8)
        R_grasp = data.site_xmat[self.arm.site_id].reshape(3, 3).copy()

        # Grasp near the END of the part (bottle-by-the-neck): after the tilt
        # the part hangs BELOW the hand, so the wrist stays clear of the table
        # at set-down. A center grip put the wrist at 3 cm height — physically
        # blocked, waypoint stalled (journal).
        ah = a0.copy()
        ah[2] = 0.0
        ah /= np.linalg.norm(ah)
        gx = x + self.GRASP_AXIAL_OFF * float(ah[0])
        gy = y + self.GRASP_AXIAL_OFF * float(ah[1])

        self._goto(data, (gx, gy, APPROACH_Z), trace, R=R_grasp)
        self._goto(data, (gx, gy, self.TIPPED_GRASP_Z), trace, tol=GRASP_TOL, R=R_grasp)
        if self._grip(data, GRIPPER_CLOSED) != name:
            trace.events.append(
                (round(data.time - self.t0, 2), f"stand-up capture miss {name}")
            )
            self._grip(data, GRIPPER_OPEN)
            self._goto(data, (x, y, HOVER_Z), trace)
            return
        self._goto(data, (gx, gy, self.ROTATE_Z), trace, R=R_grasp)

        # -- joint-space reorient ------------------------------------------
        # Tilt hinge: whichever wrist hinge currently has the most horizontal
        # axis (queried live, not assumed from the home pose).
        tilt_joint = max(
            ("wrist_1_joint", "wrist_2_joint"),
            key=lambda j: 1.0 - abs(self._dof_axis(data, j)[2]),
        )
        w = self._dof_axis(data, tilt_joint)
        w[2] = 0.0
        w /= np.linalg.norm(w)

        # Spin wrist_3 so the part's axis is perpendicular to the tilt axis:
        # then the 90° tilt sweeps it exactly into vertical.
        a = self._cyl_axis(data, name)
        d = np.cross(w, [0.0, 0.0, 1.0])  # horizontal, perpendicular to w
        phi = np.arctan2(d[1], d[0]) - np.arctan2(a[1], a[0])
        phi = ((phi + np.pi / 2) % np.pi) - np.pi / 2  # 180°-symmetric part
        # wrist_3's axis points DOWN (tool z), so a positive joint move spins
        # the part the opposite way — measured, not assumed (journal).
        s3 = np.sign(self._dof_axis(data, "wrist_3_joint")[2]) or 1.0
        self._ramp_joint(data, "wrist_3_joint", phi * s3)

        # Tilt 90° — choose the direction that puts the GRIPPED END UP, so the
        # part hangs below the hand (see end-grasp note). Rodrigues: after the
        # spin the axis lies along ±d; tilting by -sign(a·d)·90° maps it to
        # +z-hat, i.e. gripped end up. Joint limits may veto — then we accept
        # end-down and the set-down will likely fail honestly.
        a_spun = self._cyl_axis(data, name)
        adot = float(np.dot(a_spun[:2], d[:2]))
        i = scene.ARM_JOINTS.index(tilt_joint)
        want = -np.sign(adot) * np.pi / 2 if adot else np.pi / 2
        lo, hi = self.arm.q_lo[i], self.arm.q_hi[i]
        if not (lo <= self.arm.q_target[i] + want <= hi):
            want = -want
            trace.events.append(
                (round(data.time - self.t0, 2), f"tilt sign forced on {name}")
            )
        applied = self._ramp_joint(data, tilt_joint, want)
        if abs(abs(applied) - np.pi / 2) > 0.1:
            trace.events.append(
                (round(data.time - self.t0, 2), f"tilt clipped on {name}")
            )

        # Fine-trim: a part released even ~15° off vertical lands on its rim
        # and topples (observed: every stand-up tipped on landing with a lax
        # 26° acceptance). Nudge the tilt hinge until lean < ~3°.
        for _ in range(3):
            axis = self._cyl_axis(data, name)
            lean = float(np.arccos(np.clip(abs(axis[2]), -1.0, 1.0)))
            if lean < 0.05:
                break
            before = lean
            self._ramp_joint(data, tilt_joint, lean, duration=0.4)
            axis = self._cyl_axis(data, name)
            if float(np.arccos(np.clip(abs(axis[2]), -1.0, 1.0))) > before:
                self._ramp_joint(data, tilt_joint, -2 * lean, duration=0.6)

        upright_now = abs(self._cyl_axis(data, name)[2]) > 0.9986  # < ~3° lean
        if not upright_now:
            trace.events.append(
                (round(data.time - self.t0, 2), f"reorient failed {name}")
            )
            # set it back down flat-ish where it came from, honestly
        # From here IK only TRANSLATES, holding the current (tilted) rotation.
        R_hold = data.site_xmat[self.arm.site_id].reshape(3, 3).copy()
        off = self._cyl_pos(data, name) - self.arm.pinch_pos(data)
        drop_z = (
            BELIEF_HALF_HEIGHT + PLACE_CLEARANCE
            if upright_now
            else BELIEF_RADIUS + PLACE_CLEARANCE
        )
        tgt = np.array([x, y, drop_z]) - off
        self._goto(data, tgt, trace, tol=GRASP_TOL, R=R_hold)
        self._grip(data, GRIPPER_OPEN)
        self._goto(data, tgt + [0.0, 0.0, 0.15], trace, R=R_hold)
        # Clear out laterally + high BEFORE rewinding: the un-tilt swings the
        # hand through a wide arc, and doing it next to the freshly stood-up
        # part sweeps the part over (observed: every stand-up "succeeded" yet
        # ended tipped).
        self._goto(
            data,
            (x + 0.14 * float(ah[0]), y + 0.14 * float(ah[1]), self.ROTATE_Z),
            trace,
            R=R_hold,
        )

        # Rewind the reorient exactly (joint space), then re-assert hover.
        self._ramp_joint(data, tilt_joint, -applied)
        self._ramp_joint(data, "wrist_3_joint", -phi)
        self._goto(data, (x, y, HOVER_Z), trace)

    # -- the episode --------------------------------------------------------
    handle_tipped = False  # v1 frozen; BaselinePolicyV2 flips this
    resync_on_timeout = False  # v2 only — changing this would unfreeze v1

    def run(self, data: mujoco.MjData) -> EpisodeTrace:
        """Assumes the world was just reset (episodes.reset_episode)."""
        trace = EpisodeTrace()
        self.arm.reset(data)
        self.t0 = data.time
        data.ctrl[self.grip_act] = GRIPPER_OPEN

        if self.handle_tipped:
            # Two passes: anything still lying after pass one gets ONE retry
            # (a failed flip often leaves the part capturable again).
            for attempt in range(2):
                still_down = [
                    n for n in scene.CYLINDER_NAMES if not self._upright(data, n)
                ]
                if not still_down:
                    break
                for name in still_down:
                    if self._time_up(data):
                        break
                    if attempt:
                        trace.events.append(
                            (round(data.time - self.t0, 2), f"stand-up retry {name}")
                        )
                    self._stand_up(data, name, trace)

        todo = []
        for name in scene.CYLINDER_NAMES:
            if self._upright(data, name):
                todo.append(name)
            else:
                trace.skipped_tipped.append(name)
        if trace.skipped_tipped:
            trace.events.append((0.0, f"skipping tipped: {trace.skipped_tipped}"))

        tx, ty = scene.TARGET_POS[0], scene.TARGET_POS[1]
        layer = 0
        while todo and not self._time_up(data):
            # nearest upright cylinder to the hand, measured fresh each pick
            hand = self.arm.pinch_pos(data)
            todo.sort(key=lambda n: np.linalg.norm(self._cyl_pos(data, n)[:2] - hand[:2]))
            name = todo.pop(0)
            x, y, _ = self._cyl_pos(data, name)  # perception happens here, once
            trace.picks_attempted += 1
            t = round(data.time - self.t0, 2)
            trace.events.append((t, f"pick {name} at ({x:.3f},{y:.3f}) -> layer {layer}"))

            self._goto(data, (x, y, HOVER_Z), trace)
            self._goto(data, (x, y, APPROACH_Z), trace)
            self._goto(data, (x, y, GRASP_Z), trace, tol=GRASP_TOL)
            self._grip(data, GRIPPER_CLOSED)
            self._goto(data, (x, y, LIFT_Z), trace)

            if self._cyl_pos(data, name)[2] > 0.10:  # did it come with us?
                trace.picks_lifted += 1
                # The cylinder rides in the grip wherever it ended up, not
                # where we planned (observed slips of +/-13 mm vertically and
                # tens of mm laterally). Measure the pinch->cylinder offset
                # and aim the placement so the CYLINDER (not the pinch site)
                # arrives over the target at the layer height.
                grip_off = self.arm.pinch_pos(data) - self._cyl_pos(data, name)
                place = np.array(
                    [
                        tx + grip_off[0],
                        ty + grip_off[1],
                        BELIEF_HALF_HEIGHT
                        + BELIEF_LAYER_SPACING * layer
                        + PLACE_CLEARANCE
                        + grip_off[2],
                    ]
                )
                self._goto(data, (place[0], place[1], LIFT_Z), trace)
                self._goto(data, (place[0], place[1], place[2] + 0.08), trace)
                self._goto(data, place, trace, tol=GRASP_TOL)
                self._grip(data, GRIPPER_OPEN)
                self._goto(data, (place[0], place[1], LIFT_Z), trace)
                layer += 1
            else:
                trace.events.append(
                    (round(data.time - self.t0, 2), f"grasp failed on {name}")
                )
                self._grip(data, GRIPPER_OPEN)
                self._goto(data, (x, y, HOVER_Z), trace)

        trace.timed_out = self._time_up(data)
        self._goto(data, PARK, trace)
        return trace


class BaselinePolicyV2(BaselinePolicy):
    """v2 variant: stands tipped cylinders up first, then stacks as usual."""

    handle_tipped = True
    resync_on_timeout = True
    TIME_LIMIT = 120.0


def make_noisy_policy(sigma: float):
    """Part D degraded variant: v1 with mis-calibrated perception.

    Model: one fixed xy offset per cylinder per episode, drawn from
    N(0, sigma) via a seeded rng — a camera with calibration error, not a
    flickering one. Chosen over per-read jitter because it is deterministic
    per seed (replayable), physically interpretable, and one clean knob.
    Only perception degrades: aiming uses the offset positions, while the
    capture check keeps ground truth, so a bad grasp is a genuinely missed
    grasp, not a physics cheat. z and orientation perception stay true
    (stated simplification).
    """

    class NoisyPolicy(BaselinePolicy):
        SIGMA = sigma

        def set_episode_seed(self, seed: int) -> None:
            rng = np.random.default_rng([seed, 20260731])
            self._offsets = {
                n: rng.normal(0.0, sigma, 2) for n in scene.CYLINDER_NAMES
            }

        def _cyl_pos(self, data, name) -> np.ndarray:
            p = self._true_pos(data, name)
            p[:2] += self._offsets[name]
            return p

    NoisyPolicy.__name__ = f"NoisyV1_{round(sigma * 1000)}mm"
    return NoisyPolicy
