"""Interactive viewer. macOS: `mjpython view.py` — Linux: `python view.py`.

Optional seed argument shows that episode's randomized initial state:
    mjpython view.py 42
"""

import sys

import mujoco
import mujoco.viewer

import scene
import episodes

model = scene.make_model()
data = mujoco.MjData(model)
if len(sys.argv) > 1:
    seed = int(sys.argv[1])
    episodes.reset_episode(model, data, seed)
    print(f"showing episode seed={seed}")
else:
    scene.reset_home(model, data)
mujoco.viewer.launch(model, data)
