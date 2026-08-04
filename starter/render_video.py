"""Headless end-to-end episode video — plain python, encodes via ffmpeg.

    python render_video.py 42          -> renders/episode_042.mp4
    python render_video.py 42 --speed 1  (realtime; default is 2x)

Runs the full pipeline on one seed — reset_episode -> BaselinePolicy.run ->
2 s settle -> judge — capturing frames throughout, and stamps sim time, the
latest policy event, and the final verdict on the video. Visualization only:
the extra settle frames mean the judge here sees ~2 s more rest than the
harness will, which cannot change a verdict on an at-rest scene.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import mujoco
import numpy as np
from PIL import Image, ImageDraw

import scene
import episodes
import baseline
import judge as judge_mod
from render_episode import make_camera, WIDTH, HEIGHT

OUT_DIR = Path(__file__).parent / "renders"
SIM_FPS = 25  # captured frames per sim-second


POLICIES = {"v1": baseline.BaselinePolicy, "v2": baseline.BaselinePolicyV2}


def make_recording_policy(base_cls, model, recorder):
    """Wrap any policy class with a frame tap in _step; behavior unchanged."""

    class RecordingPolicy(base_cls):
        def _step(self, data):
            super()._step(data)
            recorder.maybe_capture(data)

    return RecordingPolicy(model)


class Recorder:
    def __init__(self, model, ffmpeg_stdin):
        self.renderer = mujoco.Renderer(model, height=HEIGHT, width=WIDTH)
        self.cam = make_camera()
        self.out = ffmpeg_stdin
        self.frame_dt = 1.0 / SIM_FPS
        self.next_t = 0.0
        self.caption = ""
        self.frames = 0

    def maybe_capture(self, data):
        if data.time < self.next_t:
            return
        self.next_t = data.time + self.frame_dt
        self.renderer.update_scene(data, camera=self.cam)
        img = Image.fromarray(self.renderer.render())
        draw = ImageDraw.Draw(img)
        draw.text((12, 10), f"t = {data.time:6.2f} s", fill=(255, 255, 255))
        if self.caption:
            draw.text((12, 28), self.caption, fill=(255, 255, 255))
        self.out.write(img.tobytes())
        self.frames += 1
        self._last = img

    def hold(self, seconds, banner, color):
        """Repeat the last frame with a verdict banner."""
        draw = ImageDraw.Draw(self._last)
        draw.rectangle([8, HEIGHT - 46, 8 + 11 * len(banner), HEIGHT - 14], fill=color)
        draw.text((16, HEIGHT - 38), banner, fill=(255, 255, 255))
        for _ in range(int(seconds * SIM_FPS)):
            self.out.write(self._last.tobytes())
            self.frames += 1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("seed", type=int)
    ap.add_argument("--speed", type=float, default=2.0, help="playback speed vs realtime")
    ap.add_argument("--policy", choices=sorted(POLICIES), default="v1")
    args = ap.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"episode_{args.seed:03d}_{args.policy}.mp4"

    model = scene.make_model()
    data = mujoco.MjData(model)

    ffmpeg = subprocess.Popen(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{WIDTH}x{HEIGHT}", "-r", str(SIM_FPS * args.speed),
            "-i", "-",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "23",
            str(out_path),
        ],
        stdin=subprocess.PIPE,
    )

    rec = Recorder(model, ffmpeg.stdin)
    init = episodes.reset_episode(model, data, args.seed)
    rec.caption = f"seed {args.seed}"
    rec.maybe_capture(data)

    policy = make_recording_policy(POLICIES[args.policy], model, rec)
    trace = policy.run(data)

    rec.caption = f"seed {args.seed} | settling for judge"
    for _ in range(int(judge_mod.JUDGE_SETTLE_TIME / model.opt.timestep)):
        mujoco.mj_step(model, data)
        rec.maybe_capture(data)

    verdict = judge_mod.judge(model, data)
    if verdict.success:
        banner, color = "SUCCESS: stack of 3", (30, 110, 60)
    else:
        banner = f"FAIL: {verdict.failure_reason} (stack_height={verdict.stack_height})"
        color = (150, 40, 30)
    rec.hold(2.5 / args.speed, banner, color)

    ffmpeg.stdin.close()
    ffmpeg.wait()
    rec.renderer.close()

    print(f"seed {args.seed}: {out_path}  ({rec.frames} frames, {args.speed}x)")
    print(f"  verdict: success={verdict.success} stack_height={verdict.stack_height}"
          f" reason={verdict.failure_reason}")
    print(f"  trace: picks={trace.picks_attempted} lifted={trace.picks_lifted}"
          f" skipped_tipped={trace.skipped_tipped} timed_out={trace.timed_out}")
    for t, msg in trace.events:
        print(f"    [{t:7.2f}s] {msg}")


if __name__ == "__main__":
    main()
