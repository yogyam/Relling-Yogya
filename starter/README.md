# Relling take-home — starter sandbox

Scaffolding only. This gets you a working UR5e + Robotiq 2F-85 in MuJoCo with three
cylinders on the work surface, so your first hour goes to the task, not to MJCF plumbing.
Nothing in here is the answer to anything we grade: the randomization, the success
judge, the baseline policy, and the evaluation harness are yours.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # or: uv venv && source .venv/bin/activate
pip install -r requirements.txt                     # or: uv pip install -r requirements.txt
./fetch_assets.sh                                   # sparse-clones mujoco_menagerie (pinned commit)
python smoke.py                                     # headless: compiles, steps physics, prints SMOKE OK
```

Interactive viewer (macOS needs `mjpython`, Linux plain `python`):

```bash
mjpython view.py    # macOS
python view.py      # Linux
```

## What's in the box

| File | What it does |
|---|---|
| `scene.py` | `make_spec()` / `make_model()` — composes UR5e + 2F-85 (menagerie models, gripper attached at the flange, gripper solver settings preserved), a table, three cylinders, a target site |
| `smoke.py` | Loads the model, steps 2 simulated seconds, sanity-prints actuators and cylinder heights |
| `view.py` | Opens the interactive viewer on the composed scene |
| `fetch_assets.sh` | Pins `mujoco_menagerie` at commit `71f066ad` so your numbers and ours come from the same physics |

## Notes you'll want later

- The arm's 6 joints + the gripper (`2f85/fingers_actuator`, 0=open, 255=closed) are position-actuated.
  The home keyframe is a reasonable ready pose.
- Cylinders are free bodies named `cyl0..cyl2` (30 mm diameter, 60 mm tall, default density).
  Where the packet is silent on physical parameters, the choice — and the stated assumption — is yours.
- The composed scene keeps the gripper model's `impratio` and elliptic friction cone. If you change
  solver options, know why.
- `scene.py` returns a live `MjSpec`, so you can modify the scene programmatically (cylinder poses,
  extra sensors/sites) before compiling — likely useful for your harness.
