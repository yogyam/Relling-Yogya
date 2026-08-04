# Decision journal

Running log, per the packet §2. Unpolished by design. Chronological, newest at
the bottom.

Standing division of labor, so I don't repeat it per entry: I keep the problem
decomposition, the design decisions, and the final call on every tradeoff;
Claude (AI agent) writes most of the code and runs the mechanical steps; every
delegated piece gets verified before I stand behind it — by running its checks,
reading its raw outputs, and looking at renders. Deviations from that split are
noted where they happen.

## 2026-07-31 — setup

- Read the packet + starter code. My read on the shape: the harness (Part C) and
  the gate analysis (Part D) are the graded core; the baseline (Part B) is
  deliberately a fixture, capped at ~half a day. Planning time accordingly.
- Delegated: environment setup (venv, pip install, fetch_assets.sh, smoke test).
  Verified by reading the smoke output: mujoco 3.11.0, 7 actuators (6 arm +
  gripper), cylinders settle at z≈0.030 m which matches the 30 mm half-height.
  Nothing surprising.
- Open questions at this point:
  - What "stable stack" means for the judge (settle time? tilt tolerance?
    distance to target?)
  - Spawn region bounds; can cylinders spawn touching each other?
  - Real grasp physics vs. the packet-sanctioned weld fallback — plan is to try
    real grasping first, timebox it, fall back consciously if it eats budget.

## Part A, half 1 — seeded spawn randomization (first version)

- **Decision (later reversed): cylinders spawn upright with random yaw only.**
  The packet says "positions and orientations"; for a symmetric upright cylinder
  the substantive question is whether they can spawn tipped over. First call:
  upright-only (story: parts arrive upright from a fixture/feeder), declared as
  an assumption, to be mentioned in the day-1 update rather than blocking on an
  email to Vidyut. Tradeoff accepted at the time: the evaluation cannot see
  tipped-part failures. Yaw still sampled + recorded so the schema would survive
  a scope change.
- Spawn region x∈[0.35,0.60], y∈[−0.25,0.25]; min separation 8 cm (2F-85 open
  finger span ~85 mm — a closer neighbor can block the grasp). Both stated
  choices, both movable later; note that region size directly tunes task
  difficulty, which matters again in Part D.
- The episode's official initial state is the *settled* pose, not the sampled
  pose — avoids the replay bug where the log says one pose and physics had
  another.
- Delegated: episodes.py + check_episodes.py. Verified by running the checks:
  same seed → bit-identical qpos (bitwise, not approx), different seeds differ,
  200 seeds all in-region/settled/separated, max settle drift 0.10 mm.

## Dead end: the interactive viewer on this machine

- Wanted to eyeball seeded episodes. `mjpython view.py` failed twice:
  (1) the shebang breaks because the project path contains a space ("Relling
  Takehome"); (2) even invoked explicitly via `.venv/bin/python
  .venv/bin/mjpython`, the viewer's C++ core throws "Caught an unknown
  exception" — some macOS + conda-python + mjpython incompatibility. Checked
  the obvious suspect (Rosetta/x86 conda on Apple Silicon): not it, everything
  is native arm64. Root cause never identified.
- **Decision: stopped digging.** GUI plumbing is exactly the time sink the
  packet warns about. Replaced with headless offscreen rendering
  (render_episode.py, plain python, no mjpython). So visual verification of
  half 1 happened via PNGs, not the live viewer: seeds 42/7/13 render as
  distinct layouts, upright cylinders, target disc visible. Bonus: this same
  machinery becomes the failure-snapshot generator for the run report.
- Starter modifications (declared): scene.py now sets the offscreen framebuffer
  to 1280x960 (MuJoCo default 640x480 was too small); pillow added to
  requirements.txt for PNG writing; view.py takes an optional seed argument
  (works on machines where mjpython works).

## Reversal: tipped spawns are IN (orientation randomization done properly)

- Stopped believing the upright-only reading. On re-reading, the packet
  explicitly says "positions and orientations," and yaw-only compliance is
  dodging the only orientation decision that means anything for a cylinder.
  (Discussion during working session — the push to take the requirement
  literally came from me; the "world sees it, robot may ignore it" framing
  came out of talking through what each option costs.)
- New scheme: each cylinder independently spawns lying on its side with
  p=TIP_PROBABILITY (0.2, stated, configurable), else upright with random yaw.
- **The baseline is NOT required to handle tipped parts.** Those episodes may
  fail honestly; the taxonomy will count them as their own category. That is
  the point: the evaluation can now *see* the tipped-part failure mode instead
  of the world pretending it doesn't exist. Known consequence, priced in: with
  p=0.2 per cylinder, ~49% of episodes contain at least one tipped cylinder, so
  the baseline's headline rate is capped near ~50% even if it is perfect on
  upright parts. That is the honest number and the memo will discuss it.
- tip_probability is deliberately a parameter: 0 recovers the all-upright
  world, which turns "what if the gate's initial-condition scheme changes?"
  into a runnable Part D experiment (the packet lists the initial-condition
  scheme as a gate lever).
- Settling now 1 s (up from 0.5 s — tipped cylinders can roll); if a rolled
  cylinder ends out-of-region/jammed, the whole layout is redrawn from the same
  rng, so determinism survives. Empirically: 0 redraws in 200 seeds —
  flat-placed cylinders barely roll.
- Verified: bitwise replay still holds; tip rate 21.3% (128/600 draws) vs 20%
  target; renders of seeds 2 (all tipped) and 3 (one tipped) match their
  recorded labels; raw settled heights confirm the physics (tipped centers at
  ~14.8 mm ≈ radius, upright at ~29.9 mm ≈ half-height — the sub-millimeter
  deficit is soft-contact sink, first sighting of a pattern that recurs below).

## Part A, half 2 — the success judge

- **Definition chosen** (to be defended in memo): after a 2 s settle with the
  arm parked, success = a single chain of three upright cylinders (tilt < 10°),
  centers at 30/90/150 mm (±10 mm), each within 10 mm horizontally of the one
  below, base within 25 mm of the target — and everything at rest. Partial
  stacks reported via stack_height (0–3), never blended into the pass bool.
  The verdict carries the failure reason + measured numbers, so Part C's
  failure taxonomy is largely born inside the judge.
- **Calibrated, not guessed:** measured the at-rest jitter floor of a settled
  stack *before* setting thresholds — max 3.1e-4 m/s speed, 1.9e-2 rad/s spin.
  At-rest thresholds (0.01 m/s, 0.5 rad/s) sit ~30x above the hum, orders of
  magnitude below real motion. Also measured that stacked layers sink to
  29.6/89.3/149.1 mm (soft contacts again) — the ±10 mm layer tolerance
  absorbs it with margin. Both measurements recorded in judge.py comments so
  the numbers travel with the code.
- Delegated: judge.py + check_judge.py (10 hand-built fixtures with asserted
  verdicts, incl. threshold boundary cases — base at 27 mm > 25 tol fails,
  mid-layer at 12 mm > 10 tol fails — and every fixture's post-settle state
  rendered for visual audit). Verified by running the exam and reading the
  renders myself.
- **Plausible-but-wrong output, caught — and it was mine:** my "top flying off
  at 0.3 m/s" fixture asserted the judge must fail it; the judge passed it.
  Investigated instead of "fixing" the judge: friction (μ≈1) stops a 0.3 m/s
  slide in ~v²/2μg ≈ 4.6 mm; measured slide 4.8 mm — inside tolerance, the
  tower legitimately survives, and a human watching would agree it's stacked.
  The *fixture expectation* was the wrong physics, not the judge. Kick raised
  to 1.0 m/s (needs >~0.54 m/s to clear the 15 mm rim); now the top visibly
  falls (render shows it lying next to a surviving 2-tower) and the judge rules
  partial_stack_2. Lesson: test-the-tester works — and when a test fails, the
  bug can be in the test.

## Things I was confused by, and what changed my mind (my own notes)

- Honestly the packet itself confused me at first read — I couldn't tell what
  was actually being graded. The thing that made it click: the robot is not the
  product here, the *measurement* is. The baseline exists to feed the harness,
  not the other way around. Once I had that, the weird budget advice ("let the
  baseline be ugly, cap it at half a day") stopped sounding weird. Also had to
  ask what a "readout call" even is — it's just presenting your results and
  defending them.
- The orientation requirement took me three rounds. First I accepted the
  upright-only-with-random-yaw plan (it had a tidy justification — parts arrive
  upright from a feeder). Then it kept nagging me that yaw on a symmetric
  cylinder is meaningless, so we were technically randomizing "orientations"
  while dodging the only version of it that matters. I asked why the robot
  couldn't just grab a tipped cylinder across its belly — turns out the grab is
  the easy part; the killer is the 90° mid-air flip to stand it back up, where
  the cylinder is held only by fingertip friction while gravity twists it. What
  finally convinced me: we don't have to choose between "tipped parts don't
  exist" and "robot handles them." The world can throw tipped parts and the
  robot can fail them *honestly*, with the failures counted in their own
  category. I'd rather show a ~50% success rate with the blind spot measured
  than a prettier number with the blind spot hidden. So I called it: tipped
  spawns are in.
- The "everything at rest" check confused me — how do you mathematically decide
  something is still? Answer: velocity magnitudes under a threshold. But the
  part I wouldn't have guessed: you can't check for exactly zero, because the
  simulator's soft contacts leave everything with a microscopic hum (~3e-4 m/s
  even for a stack that's been sitting for 2 seconds). What convinced me the
  thresholds were right was that we *measured* the hum first and put the
  cutoff ~30x above it, instead of picking a number that felt right.
- Watching our own test be wrong was the most instructive moment so far: the
  "top flying off at 0.3 m/s" fixture was supposed to prove the judge catches
  unstable stacks — instead the judge passed it, and the judge was *correct*,
  because friction stops that slide in under 5 mm and the tower survives. My
  takeaway: when a test and the code disagree, do the physics before deciding
  which one is broken.
- Small one: `mjpython` kept dying with "bad interpreter" and it turned out to
  be the *space in my folder name* breaking the shebang line. Then even after
  bypassing that, the viewer crashes for reasons we never found (some
  macOS/conda thing). Lesson I'm taking: name project folders without spaces,
  and don't sink hours into GUI plumbing when a headless render answers the
  same question.

## Part B — the baseline, and the day the timebox earned its keep

Decisions locked with Yogya up front: differential IK ("keep nudging"
calculator, ~60 lines, transparent), REAL contact grasping under an honest
timebox, tipped cylinders skipped (fail honestly), nearest-first, blind
open-loop waypoints.

What actually happened, in order — kept verbatim because the chain of
plausible-but-wrong physics here is the most instructive thing so far:

1. First full episode: all 3 grasps LIFTED with real contact physics — and then
   the placements flung two cylinders literally off the table (one ended 1.9 m
   away). Instrumented every grip event. Three root causes, all measured:
   (a) closing the fingers shoved the part 35–45 mm ("watermelon-seed" pop,
   from an off-center 8 mm approach + instant 0->255 slam); (b) the part rides
   up/down in the grip so releases dropped it 20–40 mm; (c) a tipped cylinder
   ROLLS FOREVER — MuJoCo condim 3 has no rolling friction. Watched cyl1's y
   coordinate march 0.38 -> 1.87 across the log.
2. Fix for (c): cylinder geoms get condim=6 + rolling friction (declared physics
   choice; verified a kicked cylinder now stops in 5 cm). First attempt included
   priority=1 — WRONG: the gripper pads carry priority=1 with tuned contact
   params, my priority tied them and MuJoCo's mixing diluted the pad tuning.
   Result: 0/3 lifts, silently. Exactly the packet's "solver settings that look
   right and behave wrong." Removed priority; pads win again; rolling fix keeps
   working via condim/friction mixing with the floor.
3. Fix attempt for (a): ramp the close gently. WRONG AGAIN, instructively: a
   position servo tracks a slow ramp with near-zero error => near-zero force =>
   the fingers crept and never reached the part (0 pad contacts vs 11 with an
   instant close). Reverted to instant close; the shove is contained by a tight
   3 mm approach instead (measured 0.6 mm part movement at close).
4. Real grasping verdict at timebox end: lifting reliable (3/3 most seeds), but
   the part dangles unpredictably in the pinch (+/-13 mm slips, dangling 43 mm
   off-axis observed) — precision STACKING out of a real pinch is the tuning pit
   the packet's grasping rule describes. Took the sanctioned fallback.
5. Fallback v1: MjSpec weld equality toggled at runtime. The constraint solver
   yanked a captured part 76 mm toward a subtly wrong stored pose and the swing
   demolished a finished 2-stack. Did not debug constraint internals — replaced
   with the transparent equivalent: kinematic carry (record the part's offset in
   the gripper frame at capture; pin it there every step until release).
   CAPTURE_RADIUS 20 mm keeps grasping honestly missable.
6. Approach knocks fixed with a staged descend (long descends bow sideways —
   measured the pinch 18 mm off-axis and BELOW grasp height mid-descend) and
   fingers closing to 100 not 128 (measured: 128 already brushes a 30 mm part).

Where it landed (10 probe seeds): 2 SUCCESS, 3 partial_stack_2, 4
partial_stack_1 / no_base, tipped episodes failing by design. Genuinely varied
outcomes — which is the fixture Part C needs. Stopping here ON PURPOSE: the
packet says a 40% baseline measured honestly beats an 80% one that ate the
instrumentation budget.

**What the kinematic fallback invalidated (for the memo):** grasp-slip,
in-grip pose drift, squeeze-ejection, and drop-in-transit failures no longer
exist in this world; every capture within 20 mm is a perfect grasp. The
evaluation still sees: approach knocks, placement drops, stack collapses, IK
misses, tipped-part blindness, timeouts.

## The fallback interrogated — legality, the honesty knob, and real life

Wrote this up after questioning whether the glue was even allowed, and what it
means outside the sim.

- **Packet legality — checked, not assumed.** Re-read the grasping rule box
  rather than trusting memory. It names our exact technique as its worked
  example: "kinematically attaching the cylinder to the gripper on close (a
  weld constraint) is an acceptable engineering decision, if you make it
  consciously." Its three conditions and our receipts: made consciously (real
  physics tried first under a timebox, retreat justified by measurements, all
  above); traded-away stated (the invalidation list above); "know what your
  fallback invalidated" (this section + memo). So: sanctioned, and we ran the
  rule's own playbook including the part it doesn't require — attempting the
  real thing first.
- **CAPTURE_RADIUS = 20 mm is the honesty knob, and it's a two-sided tradeoff:**
  too small (~2 mm) fails grasps the real 85 mm-span gripper would forgive —
  closing fingers self-center a slightly-off part, so a hair-trigger radius
  would punish errors the hardware absorbs. Too big (~100 mm) is a magic magnet
  that would delete approach accuracy from the evaluation on top of what the
  glue already deleted. 20 mm ~= "the part is genuinely between the fingers"
  (part is 30 mm wide; IK typically arrives within 2–3 mm). A stated
  assumption, not a truth.
- **Known quirk, kept deliberately:** the capture distance is 3D, so a
  just-knocked-over cylinder (center at 15 mm) is still capturable — the robot
  will carry it sideways and place it sideways. Observed on seed 42. Kept: it
  is a weird-but-real failure mode and the taxonomy wants variety.
- **Real-life context (for the readout, likely asked):** there is no glue on a
  real robot — fingers hold by friction, full stop. This shortcut is
  sim-only. Industry handles the same gap by: (1) not trusting sim for contact
  at all — sim tests choreography, real hardware validates the grip; Relling's
  own n=50-on-a-real-cell gate exists precisely because sim contact isn't
  trusted; (2) engineering grasp uncertainty away in hardware — suction cups
  (for which weld-on-contact is actually a near-faithful model), self-centering
  fingertips, part feeders; (3) closing the gap when required — system ID,
  domain randomization, real-data fine-tuning; (4) doing exactly what we did,
  knowingly: simplified sim + a written ledger of what the simplification
  cannot test.
- **The framing that ties the whole exercise together:** Part D asks what the
  gate is blind to at n=50; the grasping rule asks what our sim is blind to.
  Same question — "do you know what your measurement can't see?" — and the
  deliverables are us answering it in writing, repeatedly.

## Part C — harness + run report (the headline deliverable)

- Decisions (settled with Yogya): report is a single self-contained HTML file,
  lightly designed (the reader is an interviewer with a 60-second timer);
  flagship run at n=50 — re-checked the packet: it says "n episodes" (flexible
  machinery) but anchors the uncertainty question "at n=50", mirroring the
  gate. So: --n is a parameter, the committed example uses 50.
- Per-episode record schema (the "triage without re-running" test): seed,
  settled initial poses + upright/tipped per cylinder, verdict + stack height,
  mechanism category, policy trace (picks, lifts, skips, timeouts, events),
  final poses + tilts, sim/wall timings, and a final-state snapshot.
- Taxonomy: deterministic priority rules over judge verdict + policy trace.
  Priority matters: a skipped tipped part makes a 3-stack impossible, so it
  outranks whatever else went wrong in the episode.
- Uncertainty: Wilson 95% (naive normal approx misbehaves at small n / extreme
  p, which is exactly our regime). Implemented by hand — no scipy dependency.
- **Flagship n=50 result: 5/50 = 10%, Wilson 4.3%–21.4%.** Gate verdict: fails
  hard. Taxonomy: tipped_part_skipped 28, stack_collapse 6, grasp_miss 6,
  top_placement_failed 5. Heights: 5×3-stack, 15×2, 26×1, 4×0. The tipped
  count matches the prediction made when we chose p=0.2 (~49% of episodes
  contain ≥1 tipped part — priced in, now measured).
- Determinism spot-check across runs: seed 42 produced identical outcome
  (h=2, top_placement_failed) in the probe and the flagship run.
- Pleasant surprise: ~1 s wall per episode — n=50 costs under a minute, so
  Part D's hundreds-of-episodes experiments are cheap.
- Report contents: hero rate + CI + explicit gate verdict, stack-height
  distribution in its own tile (partial credit never blended into the headline
  — packet's hard rule), ranked taxonomy bars with plain-language blurbs,
  worst-episodes gallery (lowest stack first) with embedded snapshots + replay
  seeds, full per-episode table, and a Reproduce footer that also re-declares
  the grasp blind spot. runs/ is gitignored; the flagship report is copied to
  reports/baseline_n50.html and committed.

## Decision: un-skipping tipped parts (v2 variant) — reasoning reversal

- Yogya kept pushing on "why can't it just pick up the tipped ones?" — and on
  re-examination the honest answer changed. We skipped tipped parts because a
  friction grip would drop the part during a mid-air 90° reorient. The
  kinematic-glue fallback deleted that exact risk: a glued part cannot slip.
  The original justification has expired; what remains is steering work
  (parameterize IK orientation, align grasp yaw to the part's heading, add a
  reorient primitive), not physics gambling.
- Second driver: Part D needs a strong policy variant. Gate experiments are
  only informative near the 90% threshold; the 10% baseline can never get
  there, and tipped_part_skipped is the #1 failure bucket (28/45). Killing it
  is the largest single step toward a variant we can then degrade into
  just-below-the-gate contenders.
- **v1 stays frozen** as the honest fixture (its n=50 report is committed);
  tipped handling lands as a v2 variant selectable in the harness. Part D then
  compares genuine quality tiers instead of retroactively "improving" the
  fixture.
- Implementation strategy discussed before building: (A) carry sideways and
  place upright directly (one trip, but tool-horizontal poses + new collision
  geometry AT the stack) vs (B) stand the part up on open floor, release, then
  run the proven upright pipeline (extra step + one new honest failure mode —
  the stand-up drop — but the risky rotation happens away from the tower and
  ~90% of the path is already debugged at n=50). Recommended B; awaiting call.
- Foreseen risks, stated up front: wrist joint limits during the reorient
  (-> waypoint timeout -> honest failure), stand-up drops tipping the part,
  staging-spot selection near other cylinders, fingertip-floor proximity when
  pinching a lying part at 15 mm (mitigate: grasp a few mm high inside the
  20 mm capture radius).

## v2 stand-up: chose B, built it, and hit the real wall — the reorient itself

- Chose Strategy B over A: the risky rotation happens in open air away from
  the tower, and ~90% of the path reuses the pipeline already debugged at
  n=50. A's sole advantage (one trip per part) wasn't worth doing the novel
  maneuver next to the only thing we care about not destroying.
- Build findings, in order:
  1. Yaw-aligned grasp v1: IK stalled — commanding a tool yaw near 180° hits
     the antipodal singularity of the rotation-error formula (error vector
     collapses, steering freezes). Fixed by symmetry: nearest yaw in [-90°,90°].
  2. Yaw-aligned grasp v2: converged, but the IK achieved the yaw by swinging
     the BASE joint ~120° into a contorted pose that stalled everything after.
     With 6 joints and a 6-DOF task there is no spare freedom to prefer nice
     postures — the solver takes any solution, including awful ones.
     Abandoned yaw alignment entirely: with kinematic capture, finger-vs-axis
     alignment doesn't affect the grasp (added to the fallback's honesty
     ledger); approach now uses the proven straight-down path.
  3. Mid-air 90° rotation (Rodrigues about the axis that turns the part's
     measured heading vertical): the task-space rotation drove the arm through
     self-collision/table-collision configurations — seed 2's render shows the
     arm literally folded onto the table. The danger I attributed to Strategy A
     lives in the rotation itself, not in where it happens.
- Status: v2 currently makes things WORSE than v1 (stand-ups wreck episodes
  that upright-only play would have partially scored). Timebox spent. Options
  on the table: (a) kill v2, keep it as a documented dead end; (b) one more
  attempt via pure joint-space moves (spin wrist_3 to align, tilt wrist_1 90°
  — no task-space IK, but the tilt swings the tool position and placement
  still needs IK at a tilted orientation); (c) keep broken v2 as an honest
  "well-intentioned change that regressed" variant for Part D gate experiments.
- Key realization while stepping back: **Part D does not need a 90%-grade real
  policy.** The packet asks for baseline + degraded variants; near-threshold
  gate error rates can be demonstrated with synthetic controlled-rate policies
  (declared as instruments), while real v1-vs-degraded answers "what can the
  gate distinguish." The strongest argument for v2 was Part D; that argument
  just got weaker.

## v2 continued: Yogya called it worth the investment — the build log

Decision reversed again, this time by Yogya with a production argument I
accept: a real cell must handle tipped parts, and an evaluation whose robot
can't is measuring a smaller world. So we went back in, with the constraint
that rotations NEVER go through task-space IK planning (three failures were
enough). Everything below is joint-space single-hinge moves + IK that only
translates while holding an orientation.

The chain of bugs, each found by measurement:
1. Spin direction inverted — wrist_3's axis points DOWN, so +joint = -world
   yaw. Requested +36°, part rotated -35° (measured). Sign now read from the
   live axis, not assumed.
2. Capture misses on seed 12: without yaw alignment the open fingers descend
   ACROSS the lying part and physically kick it away before the close. So yaw
   alignment is required after all — but now done by ramping wrist_3 (joint
   space, pinch stays put) with IK merely HOLDING the result. Finger-gap
   direction measured from the actual pad positions, not assumed.
3. Set-down pose physically impossible with a belly grip: fingers at 3 cm
   height put the fist-sized wrist INTO the table — waypoint stalls forever.
   Fix: grasp near the END (bottle-by-the-neck, 20 mm axial offset) so the
   part hangs below the hand. Capture honesty metric generalized from
   distance-to-center to distance-to-axis-segment (identical for v1's center
   grasps — verified reasoning, and v1 re-run still pending as a check).
4. Timeout cascade: a blocked waypoint leaves the integrated joint target
   saturated far from the real arm; every later waypoint stalls. Fix: resync
   target to actual joint positions after any timeout — v2-gated so v1 stays
   frozen.
5. Release tipping: a part released ~15-25° off vertical lands on its rim and
   topples; my 'vertical' acceptance was 26°(!). Added a fine-trim loop on the
   tilt hinge (converge to <3° lean).
6. Rewind sweep: un-tilting the wrist next to the freshly stood part arcs the
   hand through it. Fix: retreat up and laterally before rewinding.

**Where v2 stands at n=50: 5/50 = 10.0% — the IDENTICAL headline to v1.** But
the taxonomy moved: tipped_part_skipped 28→17 (stand-ups genuinely resolve
parts), while collapses 6→8, top-placement 5→7, timeouts 0→6, and h=0
episodes 4→11 (stand-up chaos breaks scenes v1 would have left partially
scored). v2 trades one failure mode for others, netting zero.

**Why this is a gift for Part D:** two policies with genuinely different
mechanisms, indistinguishable by success rate at n=50 — the gate cannot tell
them apart, but the failure taxonomy can. That's the sharpest possible
demonstration of "what is the gate blind to," and it emerged from real
engineering, not a contrived example.

## v1 freeze audit after the capture-metric change

Re-ran v1 at n=50 after generalizing the capture metric to axis-segment
distance. Headline identical (5/50, same interval, same heights except one
episode). One borderline episode reclassified: a grasp that missed by
millimeters under the center metric now barely captures, then places badly —
grasp_miss -> base_misplaced. Documented instead of hidden; the committed
baseline report is refreshed to the current code's output so "we will run
them" reproduces exactly. Pre-change behavior recoverable at commit 7c1fa53.

## Decision: one more polish round on v2 before Part D (Yogya's call)

Scope: cheapest-first, with a built-in stopping rule.
1. Raise v2's episode time limit 60s -> 120s. The 60 was our own arbitrary
   number from Part B; v2 legitimately does 10-15s of extra work per flip and
   6/50 episodes ran out of clock mid-work. v2-gated (v1 keeps 60 and never
   hit it — freeze intact).
2. One retry for a failed stand-up if the part is still down. Attacks the
   biggest bucket (17 unresolved tipped) at its cheapest point. Ordered after
   #1 because retries burn clock.
3. Gentler placement (the 15 collapse/fumble episodes) explicitly DEFERRED
   pending data: if #1+#2 move the headline meaningfully we reconsider; if
   not, that is the diminishing-returns signal and we bank v2 and start
   Part D. Decision rule agreed before seeing the result, so the result can't
   argue us into scope creep.

## Polish round result: the stopping rule fired

Fixes worked exactly as designed and the headline did not move: 5/50 before,
5/50 after. Timeouts 6 -> 1 (the clock headroom did its job) — but the freed
episodes just revealed their underlying failures: unresolved-tipped rose
17 -> 21 (the retry rarely converts; a flip that failed once tends to fail
again), collapses 8 -> 9. Heights: zero-stack episodes rose 11 -> 14.

Reading: v2's remaining failures are not clock or retry problems — they are
placement dynamics and flip robustness, i.e., the expensive tuning tier we
pre-committed to defer. Per the agreed decision rule: bank v2 as-is, start
Part D. The v1-vs-v2 identical-headline / different-taxonomy finding stands
as Part D's opening exhibit.

## Decision ledger — the calls I made, and what I was weighing (my voice)

Consolidating my own decisions in one place so they don't get lost in the
build log. Each one: what I decided, what I was thinking, how it turned out.

1. **Tipped spawns are in (I overrode the initial recommendation).** The first
   plan was upright-only with a declared assumption. It kept nagging me: the
   PDF literally says "positions and orientations," and spinning a symmetric
   cylinder isn't really an orientation. I decided literal compliance beat a
   clever justification — if the graders wrote that word, I should honor the
   only meaning it can carry. Outcome: harder world, honest ~50% ceiling on
   the baseline, and the tipped-part failure bucket became our biggest and
   most interesting category.

2. **IK Option A — the transparent nudging calculator.** I picked it over the
   mocap trick and an external solver because I wanted something small enough
   that when it misbehaves we can see why. That paid off repeatedly: every IK
   failure in this project got diagnosed by reading measurements, not by
   staring at a black box.

3. **Timebox real grasping "honestly."** I didn't want to jump straight to
   the glue fallback without earning it — the packet permits the fallback but
   respects knowing what it costs. Giving real contact physics a bounded shot
   meant that when we did fall back, the journal had measured reasons, not
   vibes. I'd make the same call again.

4. **I asked to double-check the PDF before approving the Part B game plan —
   and again before the n=50 report, and again on whether the glue was even
   legal.** Pattern I want to keep: when a plan claims "the packet says X,"
   verify against the source, not memory. Each check either confirmed the
   plan or sharpened it (found the two-cylinder shrink option; found n=50
   anchoring; found the glue named as their own worked example).

5. **Lightly-designed report, flagship at n=50.** The reader is an
   interviewer with a 60-second timer, so design is function here, not
   polish. n=50 because that mirrors the gate we're auditing — after
   confirming the packet keeps n flexible for the machinery.

6. **The v2 tipped-handling investment (I overrode the stop recommendation).**
   The recommendation was to bank the dead end and move on. I pushed back
   because I couldn't accept an evaluation whose robot can't do something a
   production cell obviously must do — it felt like testing a smaller world
   than the one the gate protects. I knew (and was told) this was beyond the
   packet's asks and in the direction it warns about. Owning that: it WAS
   over-scope, and next time I'd budget it differently. But the outcome was
   real: v2 works, and the v1-vs-v2 result — identical 10% headline,
   completely different failure fingerprint — became the sharpest exhibit we
   have for Part D's "what is the gate blind to." The lesson I'm taking is
   not "never override the plan"; it's "override with eyes open, write it
   down, and pair it with a stopping rule."

7. **Strategy B for the flip (stand it up first, then re-use the proven
   pipeline).** I took the version that does the dangerous maneuver away from
   the tower and reuses code already tested at n=50, accepting an extra step
   and a new failure mode. Given how much the rotation fought us even in open
   air, doing it next to the stack (Strategy A) would have been strictly worse.

8. **One polish round before Part D, cheapest-first, with a pre-agreed
   stopping rule.** I wanted a little more from v2 but didn't want an
   open-ended tuning spiral, so we wrote the exit condition down BEFORE
   running: if the cheap fixes don't move the headline, bank it and start
   Part D. They didn't move it (5/50 -> 5/50), the rule fired, and we
   stopped. Deciding how to stop before seeing results is the single best
   process trick I'm taking from this project.

9. **Standing process demand: explain it to me simply before building.** I
   made a habit of not green-lighting anything I couldn't re-explain — the
   randomizer, the judge's five checks, the at-rest math, the glue's honesty
   knob, Part C's layers. Slowed us down some days; caught real issues other
   days (the orientation push in #1 came directly out of one of those
   explanations). It's also why I can defend this repo in a readout without
   notes.

## Part C closeout (before starting Part D)

Reviewed Part C against §4.3 one last time; three small closing moves:
- The report now answers the packet's uncertainty question in words, not just
  numbers: "n=50 cannot distinguish a 4% policy from a 21% one — a 17-point
  span." A stranger shouldn't have to interpret the interval themselves.
- "Fastest path to the worst episodes" is now literal: each worst-episode card
  carries `python render_video.py <seed> --policy <v1|v2>` — a one-command
  video replay of that exact episode. Verified on seed 45 (you can watch the
  collapse happen; video verdict matches the harness record) and seed 8 (clean
  success). The video tool itself was hand-added outside the main session;
  extended it with the --policy flag so v2 episodes replay under v2.
- check_all.py: one command runs all three verification suites (smoke,
  randomization properties, judge exam). For the "we will run them" moment.
- Deliberately NOT done: side-by-side variant comparison in the report — that
  is Part D's stated requirement and will be built with real gate-experiment
  content; and no cosmetic report work.

## Status before Part D

Done and verified: Part A (seeded world + calibrated, fixture-tested judge),
Part B (v1 frozen at 10%, fallback documented), v2 variant (10%, different
failure fingerprint), Part C (harness, taxonomy, Wilson uncertainty,
60-second report with video replay paths, check_all).
Not done, carried forward: Part D (experiments + gate memo — the centerpiece,
next); degraded policy variant (packet's explicit ask, cheap); README with
exact reproduction commands, tested from a fresh clone; day-1 update email to
Vidyut (due end of Monday — headline: 10% at n=50, CI 4–21%, taxonomy
attached); readout prep.

## Part D — the plan, agreed before any experiment runs

What Part D is: an empirical audit of Relling's gate (ship if >=45/50). The
two errors any such rule makes: false pass (a below-90% policy ships) and
false flunk (a genuine >=90% policy is rejected). We measure both with
experiments, then recommend changes (or defend the gate), costed in robot time.

Decisions made with Yogya up front (his calls, via structured Q&A):
- Degradation flavor: perception noise ONLY — seeded Gaussian error on where
  the policy thinks cylinders are (the packet's own example; one clean knob).
- Two degraded tiers (targets roughly ~6% and ~3% true rate; exact sigmas to
  be calibrated empirically, not guessed).
- Compute budget: standard (~1-1.5h): n=1000 true-rate runs per real variant;
  oracle gate sweeps 6 p-levels x 200 repetitions; exact binomial theory
  curves alongside.
- Memo angle: no prior — run the comparisons (bigger n, threshold tweaks,
  sequential early-stop, initial-condition scheme) and let the data pick the
  recommendation.

The verification chain we committed to BEFORE seeing results (so results
can't negotiate): (1) calibrate the oracle instrument — dial p, measure p
back through the real pipeline at large n; (2) every audit number produced
two independent ways — harness experiment vs exact binomial computation —
and any disagreement investigated, not smoothed; (3) the one bridging
assumption (episodes behave like independent coin flips) tested empirically
on real-policy data via block-dispersion, which works at any rate — a real
near-90% robot is NOT needed and we are not building one (measured: the
easier all-upright world moves v1 only to 22%, 11/50 — conditions can't
reach the line; placement engineering could, and stays out of scope).

Also parked, Yogya's idea, for the memo's "with another week" list: a
decelerated final-approach zone + post-release settle pause for placement —
top candidate improvement per the collapse taxonomy (15/50 episodes), and
explicitly NOT built now per the standing stopping-rule discipline.

Experiment list: (1) degraded tiers built+calibrated; (2) true rates at
n=1000 for v1/v2/tiers; (3) gate-on-repeat over disjoint seed blocks for real
variants; (4) oracle sweep near the threshold vs theory; (5) blindness
exhibits — v1-vs-v2 same-headline, tip-probability conditions shift;
(6) costed recommendation; (7) side-by-side gate report artifact.

## Part D step 1 — degraded variant built and calibrated (with backing)

- **Implementation decision + backing:** perception noise = one fixed xy
  offset per cylinder per episode, drawn N(0, sigma) from a seeded rng — a
  camera with calibration error, not a flickering one. Chosen over per-read
  jitter because it is deterministic per seed (episodes stay exactly
  replayable), physically interpretable, and one clean knob. Crucial
  separation: only AIMING uses the noisy positions; the capture check keeps
  ground truth — so noisy eyes produce genuinely missed grasps, never
  physics cheats. z/orientation perception stay true (stated simplification).
- **Bug caught in my own calibration sweep:** shell string `0.00$mm` turned
  "12mm" into 1.2mm — spotted because the results broke monotonicity (12mm
  scoring 5% while 8mm scored 0% made no sense). Re-ran with explicit
  values. Lesson repeated: when a result looks weird, suspect the harness
  invocation before the physics.
- **Calibration curve (n=100, seeds 0-99):** v1 8%, 1.2mm 5%, 2mm 6%,
  3mm 5%, 5mm 2%, 8mm 0%, 12mm 1%. Monotone within sampling noise.
- **Tier picks + backing:** mild = 2mm (≈6%) — deliberately CLOSE to v1's 8%
  so the distinguishability question ("can n=50 tell 8% from 6%?") is sharp;
  heavy = 5mm (≈2%) — clearly separated tier. Matches the pre-agreed targets.
- Also noted: v1 measures 8% on seeds 0-99 vs 10% on seeds 0-49 — the same
  policy, different seed sample, different number. Sampling wobble making
  itself visible; exactly the phenomenon Part D quantifies.
- n=1000 true-rate runs for v1 / v2 / mild / heavy launched in the
  background (~70 min).

## Part D step 3/4 — oracle + gate machinery built and verified (with backing)

- **Design decision + backing (oracle):** the calibrated reference policy
  arranges outcomes directly (no arm motion) and lets the REAL judge rule the
  REAL settled state. Backing: the gate only sees pass/fails, so motion
  realism adds nothing to a rule audit — but judge+pipeline pass-through
  does: it validates the whole measurement chain against a known truth,
  something no real robot can offer (nobody knows a real robot's true rate).
  Failure episodes get seeded random flavors (untouched spawn / 2-stack /
  toppled) so failure records look like failures, not blanks. Declared as
  our methodological invention — not a packet requirement — memo will call
  it a "calibrated reference policy."
- **Design decision + backing (three data routes per p-level):** full
  pipeline gate reps (200/level, the experiment), fast Bernoulli reps
  (20k/level, dense cross-check), and the exact binomial number (theory).
  Backing: the pre-committed verification chain requires every audit number
  from two independent routes; the third (Bernoulli) bridges them cheaply
  and exposes any pipeline-vs-coin discrepancy separately from
  experiment-vs-theory.
- **Design decision + backing (seed hygiene):** oracle experiments use seed
  ranges 100000+ / 200000+, disjoint from all real-policy runs. Backing:
  no accidental reuse of episodes across experiments; every number's seeds
  are recoverable from the driver script.
- **Instrument verified before use:** p=1.0 -> 30/30 judged successes
  (the oracle's stacks genuinely satisfy the judge); p=0.0 -> 0/30;
  p=0.9 -> 89.0% over n=200. 73 ms/episode -> full sweep ~75 min,
  launched in background alongside the n=1000 true-rate runs.
- Free data noted for later: the n=1000 true-rate runs double as 20 disjoint
  gate repetitions per real variant (blocks_from_records) plus the
  block-dispersion independence check — zero extra compute.

## Day-1 email sent (with backing for the question choices)

Sent the day-1 update to Vidyut: status, the honest 10%-at-n=50 number, the
tipped-spawn assumption declared, three questions. Question selection went
through two drafts. First draft asked about episode costs and retest
protocol; Yogya rejected those as too straightforward (cost is a lookup,
retest is one sentence). Second draft mined the journal for guesses only
Relling can check, which is the right bar for spending a question:
1. How is success actually specified on the real line? (Backing: every judge
   threshold we use is invented — 25 mm, 10 mm, 10°. The packet says to
   write the judge as if a customer were watching; only Relling knows the
   customer's real acceptance.)
2. What share of real-cell failures are grasp-related? (Backing: our
   kinematic fallback blinds the evaluation to slips/drops. Whether that
   hides 5% or 40% of reality determines how loudly the memo must caveat.)
3. How are the 50 gate episodes scheduled/reset in practice? (Backing: all
   gate math assumes independent episodes. We can test independence in sim
   but not on their cell; back-to-back same-operator runs could correlate
   episodes and quietly break the binomial arithmetic.)

## Pre-registered predictions for the oracle gate sweep (written BEFORE data)

The sweep is still running; nothing has been seen. Exact binomial theory for
P(pass >= 45/50), computed and committed now so the experiment can confirm
or embarrass us:
- p=0.80: 4.8% false-pass rate
- p=0.85: 21.9% false-pass
- p=0.88: 43.5% false-pass (!)
- p=0.90: 61.6% pass, i.e. a 38.4% false-flunk rate at exactly spec (!)
- p=0.92: 79.2% pass (20.8% false-flunk)
- p=0.95: 96.2% pass (3.8% false-flunk)
If confirmed, the headline: the gate is close to a coin flip for policies in
the high-80s and rejects a truly-at-spec policy 4 times out of 10. The
threshold sitting AT the target with n=50 buys the worst of both worlds.

## First true rate landed: v1 is actually 5.3%

n=1000: 53/1000 = 5.3% (Wilson 4.1-6.9%). The gate-sized n=50 sample said
10%; n=100 said 8%. Our own flagship measurement overestimated the policy
2x through ordinary sampling luck — the published Wilson interval (4.3-21.4)
did contain the truth, which is exactly why intervals must ship with the
number. This goes in the memo's opening as the lived demonstration of what
n=50 pins down: not much.

## The sweep landed: pre-registered predictions CONFIRMED

Instrument calibration first: dialed 0.88, measured 0.8840 over n=3000
(CI 0.872-0.895). The judge+harness pipeline reproduces a known rate — the
whole measurement chain validated against ground truth for the first time.

Gate sweep, all three routes agreeing at every level (pipeline 200 reps /
Bernoulli 20k reps / exact theory):
  p=0.80: 6.0% / 4.9% / 4.8%    p=0.90: 64.5% / 62.2% / 61.6%
  p=0.85: 25.0% / 21.4% / 21.9%  p=0.92: 79.5% / 79.0% / 79.2%
  p=0.88: 41.0% / 43.4% / 43.5%  p=0.95: 96.0% / 96.3% / 96.2%
Every pipeline number within sampling error of the pre-registered theory.
No embarrassment, no anomaly — which is itself the finding: the simulation
agrees with the binomial model, so the gate's error rates are REAL:
- An 88% policy (below spec) ships ~4 times in 10.
- A policy at EXACTLY 90% spec is rejected ~4 times in 10.
- Even 85% sneaks through more than 1 in 5.
Independence check inside the sweep: block-dispersion ratios 0.94-1.12
(~1 = coin-flip-like) — episodes through the full pipeline behave
independently, closing the last link of the pre-committed verification chain.

Also landed meanwhile: v2 true rate 6.6% (5.2-8.3) — v2 is genuinely BETTER
than v1 (5.3%), invisible at n=50 where both measured 10%; and mild-noise
5.7% (4.4-7.3) — statistically indistinguishable from v1 even at n=1000,
so the intended "mild degradation" is below the policy's own noise floor.
Three mechanically different policies that no feasible n separates. Heavy
tier still running.

## Part D data collection complete — final true-rate table + real independence

Heavy tier landed: 1.7% (1.1-2.7) — the one clearly separated variant.
Final table (n=1000 each):
  v1 5.3% (4.1-6.9) | v2 6.6% (5.2-8.3) | mild 5.7% (4.4-7.3) | heavy 1.7% (1.1-2.7)
At gate size n=50, v1 and v2 both measured 10%. Truth: v2 > v1, mild ~ v1,
heavy alone distinguishable. 

Real-variant gate blocks (20 disjoint 50-blocks per variant, free from the
n=1000 records): 0/20 passes everywhere — the gate correctly rejects
policies far below spec; its errors live only near the threshold, exactly
where the oracle swept. Block success counts range 0-7 out of 50 for the
SAME policy — sampling wobble made visible.

The last verification link, now closed with REAL physics (not just oracle):
block-dispersion ratios v1 0.93, v2 1.06, mild 0.99, heavy 1.17 — all ~1,
so real episodes behave like independent coin flips. The binomial bridge
between oracle experiments and real robots is validated from both sides.

Every planned Part D experiment has now run. Remaining: assembly — the
side-by-side gate report, the costed recommendation, the memo.

## Assembly decisions (Yogya's calls, with backing)

- Final report = ONE artifact, two sections: the 60-second eval summary first,
  the gate comparison below. Backing: §4.4's literal wording attaches the
  variant comparison to "your run report", and §4.3 promises they open that
  artifact first and time it — one command, one file honors both.
- Memo = markdown (MEMO.md at repo root). Backing: zero toolchain risk,
  versioned with the repo, easiest for Yogya's voice pass before submitting.
- Stretch: ATTEMPT the held-out perturbation (predict in writing which
  failure mode grows fastest with 10% larger cylinders, then test); decline
  the chunked-action refactor and say so in the memo. Backing: core is solid
  (packet's own precondition), the perturbation is ~1-2h on existing
  machinery, and it exercises the same predict-then-verify discipline the
  sweep just validated. Chunked-action is a heavier refactor with less
  evidentiary payoff.
- Timeline: no fixed deadline pressure from Yogya — "work comfortably and
  accurately." Order stays: report -> recommendation decision -> memo ->
  README + fresh-clone test -> stretch.

## Recommendation decided: margin at same cost (>=47/50) + sequential early stop

Yogya's call from the computed menu, backing: (1) early stopping is a pure
win — identical verdicts, and clearly-bad policies stop after ~6 episodes
instead of 50, which is where real cells burn the most reset labor; (2) the
current gate's core flaw is the threshold sitting exactly ON the 90% target,
making near-spec verdicts coin-flips in both directions; moving to >=47/50
cuts the false-pass rate at 88% three-fold (43.5% -> 13.5%) at ZERO extra
episode cost; (3) the price — more false flunks (57% at 92%) — is the
right side to pay on aerospace/defense floors where a shipped bad policy
plausibly costs far more than a retest, and it pairs naturally with a cheap
retest path; (4) the honest caveat stays: the optimal margin depends on
Relling's actual false-pass:false-flunk cost ratio, which we asked Vidyut
and will incorporate if answered. Alternative designs (n=100 >=93 etc.)
presented in the memo table so the recommendation is a pick, not a hiding
of the menu.

## Stretch: held-out perturbation — PREDICTION WRITTEN BEFORE RUNNING

Setup to be built: cylinders 10% larger (radius 15->16.5 mm, height
60->66 mm). World and judge scale to the true geometry; the POLICY keeps its
nominal-part beliefs (grasp height 30 mm, layer spacing 60 mm) — that's the
point of the experiment: an unmodified policy meets slightly different parts.

Prediction, committed now:
1. FASTEST-GROWING failure mode: placement-driven collapse
   (stack_collapse + top_placement_failed). Mechanism, worked out from
   geometry before running: the policy places layer L at center height
   30+60L mm, but the true resting center is 33+66L mm — a deficit of
   3+6L mm that COMPOUNDS with height (9 mm at layer 1, 15 mm at layer 2).
   The arm will try to press the part through the stack top, shoving the
   tower during release. Expect collapses to dominate the delta.
2. grasp_miss roughly FLAT: capture radius 20 mm dwarfs the 3 mm center
   shift; fingers open 85 mm vs part 33 mm.
3. tipped_part_skipped roughly FLAT as a fraction: spawn geometry scales
   with the part; the policy skips tipped parts regardless of size.
4. Headline success rate: down, driven by (1) — plausibly near-zero given
   the 15 mm layer-2 deficit exceeds the 10 mm alignment tolerance.
Comparison plan: n=200 at scale 1.1 vs the first 200 episodes of the
existing scale-1.0 true_v1 run (same seeds 0-199, zero new baseline compute).

## Perturbation results vs the pre-registered prediction — the scorecard

n=200, same seeds, 10% larger parts, policy unchanged. Taxonomy deltas:
tipped +0 | grasp_miss +17 | base_misplaced +10 | stack_collapse +1 |
top_placement -17 | successes 11 -> 0.

Scoring the prediction honestly:
- RIGHT: tipped share exactly flat (+0). RIGHT: success rate collapses
  (11 -> 0 of 200; the gate-relevant conclusion holds).
- MECHANISM RIGHT, CATEGORY WRONG: the compounding height deficit is real —
  but it kills stacks EARLIER than predicted. The press-into-the-stack shove
  shows up as base_misplaced (+10) at layer 1, so episodes die before they
  can become the predicted top_placement failures (-17). Priority-ordered
  categories mask later stages when earlier ones fire.
- WRONG: grasp_miss was predicted flat and instead grew MOST (+17).
  Hypothesis, labeled as such (not verified): parts are 10% wider while the
  spawn separation floor stayed fixed, so finger clearance between neighbors
  shrank, and post-press scatter relocates parts mid-episode. Verifying this
  would be the first task of a follow-up.
Lesson for the memo: predicting the direction of degradation was easy;
predicting WHICH failure bucket absorbs it was not — one more reason a gate
that only counts successes under-informs compared to a taxonomy.

## README written and the fresh-clone test passed

README.md at repo root: reading order (report -> memo -> journal), 5-minute
setup, and a regeneration command for every number in the memo, with
runtimes and the declared blind spots restated. Cross-platform caveat stated
honestly: seeds fix everything on one machine; floating point may shift
borderline episodes across CPUs.

The test the packet promises to run, run by us first: cloned the repo fresh
into a scratch directory, followed the README verbatim. CHECK ALL OK;
flagship n=50 reproduced 5/50 = 10.0% (4.3-21.4%) exactly; tip-0 reproduced
11/50 = 22.0% exactly. The memo's opening promise ("all numbers regenerable
from the README") is now a tested claim, not an aspiration.

Assembly remaining: Yogya's voice pass on MEMO.md and the 60-second test on
reports/final_report.html; readout rehearsal. Code and documents are
otherwise submission-ready.

## Reproduction audit, round 2 — two catches after "submission-ready"

- Asked for a same-machine reproduction of the flagship run before trusting
  the README's promise. 49/50 episodes matched the committed records
  bit-for-bit; seed 41 didn't. Not nondeterminism — two fresh reruns are
  bit-identical to each other — the committed runs/baseline_n50 predated the
  v2 refactor of the shared capture code (center-distance -> axis-distance),
  and v1_refreeze_check (made to guard exactly this) matches the rerun
  perfectly. Same 5/50 headline either way; one failure recategorized
  (grasp_miss -> base_misplaced on seed 41). Stale artifact; regenerated.
- The bigger catch: final_report.py read runs/v1_refreeze_check — a directory
  no README command creates. My earlier fresh-clone test passed because it
  stopped at the eval runs and never executed final_report.py; a grader
  following the README to the end would have crashed at the finish line.
  Fixed to runs/baseline_n50 and rehearsed the full path in a fresh clone
  (setup -> checks -> flagship n=50 -> final_report.py; the ~5 h of long runs
  copied in rather than regenerated, declared): records bit-identical to the
  main repo, report byte-identical to the shipped one except the provenance
  commit stamp.
- Lesson: "tested from a fresh clone" is only true for the commands the test
  actually ran. The rehearsal has to include the LAST command in the README,
  not just the interesting ones.

## Reproduction audit, round 3 — the derived numbers get a script

Review pass (second agent) against the packet's "regenerate EVERY number in
your memo" found three gaps, fixed now (Yogya's call: one committed script
over inline snippets):
- The README claimed the early-stop episode numbers came from "the
  simulation snippet in the journal entry 'Recommendation decided'" — no
  such snippet exists. A grader following that pointer hits a dead end.
- The recommendation table and dispersion ratios lived in README-inline
  `python -c` blocks — runnable, but not the committed one-command form the
  rest of the memo gets.
- Memo finding 3 opens with "both measured 10% at n=50", and the README had
  no command regenerating v2's n=50 number (only its n=1000 true rate).
Fix: `gate_design.py` — design menu (exact binomial), early-stop expected
episodes (exact dynamic programming, replacing the never-committed
simulation; DP and the memo's numbers agree: ~6 episodes for clearly-bad,
42-47 near spec), and gate blocks + dispersion from the n=1000 records.
Output verified line-by-line against every memo claim before committing:
43.5->13.5 at 88%, 42.5% pass at 92%, n=100>=93 7.6%/87.2%, dispersion
0.93/1.06/0.99/1.17, blocks 0/20. README's finding 5 + recommendation
sections now point at the script; v2 n=50 command added to finding 3.
Next: the full rehearsal — fresh clone, every README command including the
~5 h of long runs actually regenerated (round 2 copied them in, declared).

## Memo voice pass (Yogya's call, sample approved before applying)

The memo read compressed and jargon-heavy ("gate-sized sample", "pins down
very little", "pre-registered the binomial predictions"). Decision: rewrite
in plain language — shorter sentences, ordinary words, one idea each — with
a hard rule agreed first: every number, claim, and caveat stays byte-for-
byte identical in meaning; only the wording changes. Process: one sample
section rewritten and approved before touching the rest, then the whole memo
converted. Reasoning: the memo is read by humans under time pressure and
defended live at a readout; plain words survive both better than dense ones.
Deliberately stopped short of casual — it is still an engineering memo.

## Final audit: undeclared assumptions, hunted deliberately

Yogya asked for a full-process sweep for assumptions we never declared. The
packet names its own examples ("cylinder mass, friction, table size,
tolerances — the choice is yours to make and STATE") and the audit found we
had stated tolerances loudly while missing others — including two from the
packet's own list:
1. Cylinder mass 42.4 g — never chosen, inherited from MuJoCo's default
   density and never written down. The packet's first named example.
2. No table — the floor is an infinite collision plane; a part can never be
   lost off an edge (we even watched one roll 1.9 m and stay in play without
   registering what that implied).
3. Friction values half-declared: the rolling-friction CHANGE was declared,
   the VALUES (slide 1.0 default, roll 0.001 picked, neither validated
   against a real part) were not framed as assumptions.
4. Episode time limits (60 s / 120 s) — journal-only, despite defining the
   entire "timeout" failure category.
5. Spawn region + 8 cm separation — journal-only; the separation is a
   kindness the gripper needs that a real cell may not grant.
6. The judge's upside-down quirk (abs of the axis) — harmless for a
   symmetric part, now stated instead of latent.
All now declared in MEMO.md (limitations) and README (assumptions block).
Lesson worth saying in the readout: the assumptions you make on purpose get
declared naturally; the dangerous ones are the defaults you never noticed
choosing. An end-of-project audit specifically for silent defaults should be
standard practice.

## The full rehearsal: every memo number regenerated from a fresh clone

The complete version of the test the packet promises ("we will run them"),
with nothing copied in this time: fresh clone of the repo, fresh venv, fresh
pinned assets, then every README command end to end — including the four
n=1000 true-rate runs and the full oracle sweep (~63k judged episodes) that
round 2 had only copied in. An automated comparison scored the regenerated
numbers against the memo's claims. Result: 16/16 PASS, exact matches —
the four n=50/n=200 runs (headline rates AND taxonomies), all four true
rates (5.3 / 6.6 / 5.7 / 1.7%), the oracle calibration (0.8840), all six
sweep pass-rates, and the final report built cleanly at the finish line.
Total wall time ~4.5 h (paused and resumed mid-run via SIGSTOP/SIGCONT —
worth knowing: a seeded, deterministic pipeline survives that fine).
Reproducibility is now a measured property of this repo, not a promise.

## Report audit before submission — one dishonest label found and fixed

Read the final report end to end as a stranger would, checking every number
against the rehearsal-verified values. All content checked out except one
cell: the truth table listed mild/heavy under "n=50 measured" as ~6%/~2%,
but no n=50 run of those variants exists — the numbers came from the n=100
calibration sweeps. Nobody would likely catch it, which is exactly the kind
of small dishonesty this project is supposed to be allergic to. Fixed: the
column is now "small-sample measured" and every cell states its own sample
size ("10% (n=50)", "6% (n=100)"); README gained the two calibration
commands so those cells are regenerable like everything else. Also checked
and cleared: the two older committed per-run reports (suspected stale after
the seed-41 recategorization — they are in fact consistent with current
code), the worst-episode replay commands, the gate strips (0/20, 0/20, and
the near-threshold flips), and the measured-vs-theory table.

## Adversarial review round — two overclaims and two code fixes

Ran a full packet-vs-deliverable review (three independent passes: report
artifact, sim/judge/harness code, gate statistics — every memo number
recomputed independently; all reproduced). Four fixes applied, chosen by the
rule "fix what a grader meets in the final deliverables; leave anything that
would invalidate committed results":

1. **The oracle sweep was framed above its weight — the review's central
   catch.** Provable from the seeds: in all 13,000 pipeline episodes the
   judged outcome equals the oracle's internal coin flip — the judge never
   overturned an arranged scene. So the "measured" column is an end-to-end
   test of the measurement chain, not an independent physics experiment; it
   cannot disagree with the binomial math unless the judge misrules an
   arranged state. This was always disclosed mechanically (oracle docstring,
   "instrument" labels) but the memo's "experiment I ran, not a formula I
   copied" framing claimed more than the sweep can carry. Fixed: a scope
   paragraph in MEMO.md Finding 2 and a rewritten calibration callout in the
   final report saying exactly what the sweep can and cannot falsify, and
   that the error rates stand on the binomial model + the Finding 5
   independence check on real policies. Better to say it first than have a
   reader find it.
2. **"v2 really is better than v1" was statistically unsupported** (53/1000
   vs 66/1000, two-proportion p≈0.22, overlapping CIs) — and inconsistent
   with calling mild-vs-v1 "indistinguishable" in the same breath. Reworded
   in memo Finding 3 and the report callout to "trends better, unresolved
   even at n=1000" — which strengthens Finding 3's own thesis (the taxonomy
   separates them; the success count doesn't). Journal entries above keep the
   original claim — this log records what we believed at the time.
3. **meta.json recorded a false reproduction command** — harness.py
   hardcoded the string and dropped --policy/--perception-noise/--part-scale,
   so e.g. true_v2's meta claimed a default-v1 invocation. run_eval.py now
   passes the literal argv; the hardcoded form remains only as a labeled
   fallback for programmatic callers. Committed runs keep their stale meta
   (regenerating ~5 h of runs to fix a metadata string fails the cost test);
   records/numbers were never affected. Verified with a scratch run.
4. **final_report.py crashed with a raw traceback on a fresh clone** (runs/
   is gitignored) — the exact command the packet says they open first. Now
   preflights its inputs and prints which run dirs are missing plus the
   README command that regenerates each. Verified both paths: missing-input
   message, and byte-level diff of the regenerated report against the
   committed one showing only the two reworded callouts.

Known review findings deliberately NOT fixed (code changes that would touch
frozen behavior or committed records, none affecting a memo number): the
taxonomy fall-through that can mislabel a not-at-rest full stack as
base_misplaced; per-episode records dropping the initial orientation
quaternion (tipped heading recoverable only by seed replay); the capture
check accepting a pinch ~19 mm above a part's end face; carried parts being
kinematically immovable during transit; a wrong "exact rewind" comment in
v2's reorient (masked by the subsequent IK re-orient); timeout episodes
judging with the arm possibly unparked. All are readout-defense material,
listed here so they're on the record before someone else finds them.
check_all.py green after all changes.
