"""Verification for episodes.py — run `python check_episodes.py`.

Checks the properties the harness depends on:
1. Replayability: same seed -> bit-identical world state (full qpos compared).
2. Variation: different seeds -> different states.
3. Sanity over many seeds: every cylinder settles into a clean stable state
   (upright at 30 mm or tipped at 15 mm), inside the region (with slack),
   separated; the observed tip rate matches TIP_PROBABILITY; and
   tip_probability=0 reproduces the all-upright world.
"""

import numpy as np
import mujoco

import scene
import episodes

N_SEEDS = 200


def full_state(model, data, seed, **kw):
    episodes.reset_episode(model, data, seed, **kw)
    return data.qpos.copy()


def main() -> None:
    model = scene.make_model()
    data = mujoco.MjData(model)

    # 1. Replayability — bitwise, not approximately.
    a = full_state(model, data, seed=42)
    b = full_state(model, data, seed=42)
    assert np.array_equal(a, b), "same seed produced different states"
    print("replayability: seed 42 twice -> bit-identical qpos")

    # 2. Variation.
    c = full_state(model, data, seed=43)
    assert not np.array_equal(a, c), "different seeds produced identical states"
    print("variation: seeds 42 vs 43 differ")

    # 3. Sanity across many seeds.
    n_tipped = 0
    n_cyl = 0
    retries = 0
    for seed in range(N_SEEDS):
        init = episodes.reset_episode(model, data, seed)
        retries += init.world_tries - 1
        for name, q in init.settled_qpos.items():
            state = episodes.classify(q)
            assert state in ("upright", "tipped"), (
                f"seed {seed}: {name} in unrecognized state (qpos={q})"
            )
            assert state == init.spawn_states[name]
            n_cyl += 1
            n_tipped += state == "tipped"
            x, y = q[0], q[1]
            sl = episodes.REGION_SLACK
            assert episodes.SPAWN_X[0] - sl <= x <= episodes.SPAWN_X[1] + sl
            assert episodes.SPAWN_Y[0] - sl <= y <= episodes.SPAWN_Y[1] + sl
        xy = [(q[0], q[1]) for q in init.settled_qpos.values()]
        for i in range(len(xy)):
            for j in range(i + 1, len(xy)):
                d = float(np.hypot(xy[i][0] - xy[j][0], xy[i][1] - xy[j][1]))
                assert d >= episodes.SEPARATION_FLOOR, (
                    f"seed {seed}: separation {d:.3f} below floor"
                )

    rate = n_tipped / n_cyl
    # 600 Bernoulli(0.2) draws: expect ~120 tipped, 3-sigma band ≈ ±30.
    lo, hi = 0.15, 0.25
    assert lo <= rate <= hi, f"tip rate {rate:.3f} outside [{lo}, {hi}] — sampler suspect"
    print(
        f"sanity: {N_SEEDS} seeds OK — tip rate {rate:.1%} "
        f"({n_tipped}/{n_cyl}), {retries} world redraws total"
    )

    # 4. tip_probability=0 gives an all-upright world (Part D lever).
    init0 = episodes.reset_episode(model, data, seed=42, tip_probability=0.0)
    assert all(s == "upright" for s in init0.spawn_states.values())
    print("tip_probability=0: all upright (initial-condition scheme lever works)")

    print("CHECK EPISODES OK")


if __name__ == "__main__":
    main()
