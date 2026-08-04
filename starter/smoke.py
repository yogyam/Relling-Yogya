"""Headless sanity check: compiles the scene, steps 2 simulated seconds, verifies sanity."""

import numpy as np
import mujoco

import scene


def main() -> None:
    model = scene.make_model()
    data = mujoco.MjData(model)
    scene.reset_home(model, data)

    print(
        f"mujoco {mujoco.__version__} | nq={model.nq} nu={model.nu} nbody={model.nbody}"
    )
    print("actuators:", [model.actuator(i).name for i in range(model.nu)])

    steps = int(2.0 / model.opt.timestep)
    for _ in range(steps):
        mujoco.mj_step(model, data)

    assert not np.isnan(data.qpos).any(), "NaN in qpos — simulation blew up"
    for name in scene.CYLINDER_NAMES:
        z = data.joint(f"{name}_free").qpos[2]
        assert abs(z - scene.CYLINDER_HALF_HEIGHT) < 0.02, (
            f"{name} not resting on the floor (z={z:.4f})"
        )
        print(f"{name}: settled at z={z:.4f}")

    print("SMOKE OK")


if __name__ == "__main__":
    main()
