"""Headless episode snapshot — works with plain python (no mjpython needed).

    python render_episode.py 42            -> renders/episode_042.png
    python render_episode.py 42 7 13       -> one PNG per seed

Renders the settled initial state of each seeded episode from a fixed camera.
Exists because the interactive viewer requires mjpython, which is broken in
this environment (macOS + conda python); offscreen rendering sidesteps the GUI
entirely. Also the basis for failure snapshots in the run report later.
"""

import sys
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image

import scene
import episodes

OUT_DIR = Path(__file__).parent / "renders"
WIDTH, HEIGHT = 960, 720


def make_camera() -> mujoco.MjvCamera:
    cam = mujoco.MjvCamera()
    cam.lookat[:] = [0.45, 0.05, 0.10]  # center of the work area
    cam.distance = 1.4
    cam.azimuth = 160  # looking from in front / slightly left of the arm
    cam.elevation = -35
    return cam


def render_seed(model, data, renderer, cam, seed: int) -> Path:
    episodes.reset_episode(model, data, seed)
    renderer.update_scene(data, camera=cam)
    pixels = renderer.render()
    OUT_DIR.mkdir(exist_ok=True)
    path = OUT_DIR / f"episode_{seed:03d}.png"
    Image.fromarray(pixels).save(path)
    return path


def main() -> None:
    seeds = [int(a) for a in sys.argv[1:]] or [42]
    model = scene.make_model()
    data = mujoco.MjData(model)
    renderer = mujoco.Renderer(model, height=HEIGHT, width=WIDTH)
    cam = make_camera()
    for seed in seeds:
        path = render_seed(model, data, renderer, cam, seed)
        print(f"seed {seed}: {path}")
    renderer.close()


if __name__ == "__main__":
    main()
