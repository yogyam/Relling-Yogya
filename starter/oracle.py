"""Calibrated reference policy ("oracle") for the Part D gate audit.

NOT a robot: a statistics instrument that travels through the real pipeline.
Per episode (seeded), it succeeds with dialed-in probability p — by directly
arranging a proper stack on the target — or deliberately botches in a seeded
random flavor. The arm never moves; the REAL judge rules the REAL final state
and the harness records a normal episode.

Why it exists (journaled in full): our real policies live at 2–10%, the gate's
error zone lives near 90%, and the packet demands demonstration over quoting.
The gate only ever sees 50 pass/fails, so a policy with known p is a valid
probe of the RULE — bridged to real robots by the independence check run on
real-policy data.

Declared loudly: this is our methodological invention, not a packet
requirement; the memo labels it a calibrated reference policy.
"""

import numpy as np
import mujoco

import scene
import baseline

_UP = [1.0, 0.0, 0.0, 0.0]
_TIPPED = [np.cos(np.pi / 4), 0.0, np.sin(np.pi / 4), 0.0]
_SETTLE = 0.5  # s — let the arranged state become physical before judging


def make_oracle(p: float):
    class OraclePolicy:
        P = p

        def __init__(self, model: mujoco.MjModel):
            self.model = model
            self.rng = None

        def set_episode_seed(self, seed: int) -> None:
            self.rng = np.random.default_rng([seed, 990131, round(p * 10000)])

        def _place(self, data, name, x, y, z, quat) -> None:
            j = data.joint(f"{name}_free")
            j.qpos[:] = [x, y, z, *quat]
            j.qvel[:] = 0.0

        def run(self, data: mujoco.MjData) -> baseline.EpisodeTrace:
            assert self.rng is not None, "set_episode_seed() before run()"
            trace = baseline.EpisodeTrace()
            tx, ty = scene.TARGET_POS[0], scene.TARGET_POS[1]
            names = list(scene.CYLINDER_NAMES)

            if self.rng.random() < p:
                for i, n in enumerate(names):
                    self._place(data, n, tx, ty, 0.03 + 0.06 * i, _UP)
                trace.picks_attempted = trace.picks_lifted = 3
            else:
                flavor = self.rng.choice(["untouched", "two_stack", "toppled"])
                if flavor == "two_stack":
                    self._place(data, names[0], tx, ty, 0.03, _UP)
                    self._place(data, names[1], tx, ty, 0.09, _UP)
                    trace.picks_attempted = trace.picks_lifted = 2
                elif flavor == "toppled":
                    self._place(data, names[0], tx, ty, 0.03, _UP)
                    self._place(data, names[1], tx + 0.05, ty + 0.02, 0.015, _TIPPED)
                    self._place(data, names[2], tx - 0.04, ty + 0.05, 0.015, _TIPPED)
                    trace.picks_attempted = trace.picks_lifted = 3
                # "untouched": leave the spawn as-is; a natural total failure.

            mujoco.mj_forward(self.model, data)
            for _ in range(int(_SETTLE / self.model.opt.timestep)):
                mujoco.mj_step(self.model, data)
            return trace

    OraclePolicy.__name__ = f"Oracle_p{round(p * 1000):03d}"
    return OraclePolicy
