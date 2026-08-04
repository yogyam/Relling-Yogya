#!/usr/bin/env bash
# Sparse-clone mujoco_menagerie (Apache-2.0) pinned to a known commit.
set -euo pipefail
cd "$(dirname "$0")"
PIN=71f066ad0be9cd271f7ed58c030243ef157af9f4
DEST=third_party/mujoco_menagerie
if [ -d "$DEST/.git" ]; then
  echo "menagerie already present at $DEST"
else
  mkdir -p third_party
  git clone --filter=blob:none --sparse https://github.com/google-deepmind/mujoco_menagerie.git "$DEST"
  git -C "$DEST" sparse-checkout set universal_robots_ur5e robotiq_2f85
fi
git -C "$DEST" fetch --depth 1 origin "$PIN" 2>/dev/null || true
git -C "$DEST" checkout "$PIN" 2>/dev/null || git -C "$DEST" checkout FETCH_HEAD
echo "menagerie pinned at $(git -C "$DEST" rev-parse --short HEAD)"
