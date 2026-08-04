"""The final deliverable artifact: one command -> one HTML, two sections.

    python final_report.py            -> ../reports/final_report.html

Section 1 — the 60-second read (packet §4.3): baseline n=50 evaluation.
Section 2 — the gate audit (packet §4.4): variants side by side, gate
verdicts visible per repetition, measured-vs-theory near the threshold.

Reads existing run directories; regenerating those from scratch is
documented in the README (this script renders, it does not simulate).
"""

import json
import sys
from pathlib import Path

import gate
from harness import CATEGORY_BLURBS
from report import CSS, _img64

ROOT = Path(__file__).parent
OUT = ROOT.parent / "reports" / "final_report.html"

BASELINE_RUN = ROOT / "runs" / "baseline_n50"  # flagship n=50 (README Finding 1)
TRUE_RUNS = {
    "v1": ROOT / "runs" / "true_v1",
    "v2": ROOT / "runs" / "true_v2",
    "mild (2mm noise)": ROOT / "runs" / "true_mild",
    "heavy (5mm noise)": ROOT / "runs" / "true_heavy",
}
ORACLE = ROOT / "runs" / "gate_oracle" / "results.json"

EXTRA_CSS = """
.strip { display:flex; flex-wrap:wrap; gap:2px; margin:6px 0 2px; }
.chip { width:12px; height:16px; border-radius:2px; }
.chip.p { background:var(--good); } .chip.f { background:var(--bad); opacity:.55; }
.striplabel { font-size:12.5px; color:var(--ink2); margin-bottom:10px; }
.two { display:grid; grid-template-columns:1fr 1fr; gap:20px; }
@media (max-width:700px){ .two { grid-template-columns:1fr; } }
.theory td { font-variant-numeric:tabular-nums; }
.callout { border-left:3px solid var(--bar); padding:8px 14px; margin:14px 0;
  color:var(--ink2); font-size:14px; }
.callout b { color:var(--ink); }
"""


def _meta(run: Path) -> dict:
    return json.loads((run / "meta.json").read_text())


def _records(run: Path) -> list:
    return [json.loads(l) for l in (run / "records.jsonl").read_text().splitlines()]


def _strip(results: list, label: str) -> str:
    chips = "".join(
        f'<div class="chip {"p" if r["pass"] else "f"}" '
        f'title="rep {r["rep"]}: {r["successes"]}/50 -> '
        f'{"PASS" if r["pass"] else "fail"}"></div>'
        for r in results
    )
    passes = sum(r["pass"] for r in results)
    return (
        f'<div class="strip">{chips}</div>'
        f'<div class="striplabel">{label} — {passes}/{len(results)} gates passed</div>'
    )


REGEN = {  # run dir -> the README command that creates it (runs/ is gitignored)
    "runs/baseline_n50": "python run_eval.py --n 50  --out runs/baseline_n50",
    "runs/true_v1": "python run_eval.py --n 1000 --out runs/true_v1",
    "runs/true_v2": "python run_eval.py --n 1000 --policy v2 --out runs/true_v2",
    "runs/true_mild": "python run_eval.py --n 1000 --perception-noise 0.002 --out runs/true_mild",
    "runs/true_heavy": "python run_eval.py --n 1000 --perception-noise 0.005 --out runs/true_heavy",
    "runs/gate_oracle": "python gate_experiments.py --out runs/gate_oracle",
}


def _check_inputs() -> None:
    """Fail with the fix, not a traceback: runs/ is gitignored, so on a fresh
    clone the eval runs must be regenerated before this script can render."""
    needed = [BASELINE_RUN / "meta.json", BASELINE_RUN / "records.jsonl", ORACLE]
    needed += [run / "meta.json" for run in TRUE_RUNS.values()]
    needed += [TRUE_RUNS["v1"] / "records.jsonl", TRUE_RUNS["v2"] / "records.jsonl"]
    missing = sorted({p.parent.name for p in needed if not p.exists()})
    if missing:
        print("final_report.py renders existing runs; these are missing:")
        for name in missing:
            print(f"  runs/{name}   ->  {REGEN.get('runs/' + name, 'see README')}")
        print("(commands and runtimes in the README; the committed report is "
              "reports/final_report.html)")
        sys.exit(1)


def build() -> Path:
    _check_inputs()
    meta = _meta(BASELINE_RUN)
    records = _records(BASELINE_RUN)
    k, n = meta["successes"], meta["n"]
    lo, hi = meta["wilson95"]
    heights = meta["stack_heights"]
    oracle = json.loads(ORACLE.read_text())

    # --- Section 1: 60-second read -----------------------------------------
    tax = meta["taxonomy"]
    max_c = max(tax.values(), default=1)
    bars = ""
    for cat, c in tax.items():
        bars += (
            f'<div class="name">{cat.replace("_", " ")}</div>'
            f'<div class="track" title="{c} of {n}">'
            f'<div class="fill" style="width:{100 * c / max_c:.0f}%"></div></div>'
            f'<div class="count">{c}</div>'
            f'<div class="blurb">{CATEGORY_BLURBS.get(cat, "")}</div>'
        )
    fails = sorted(
        (r for r in records if not r["outcome"]["success"]),
        key=lambda r: (r["outcome"]["stack_height"], r["seed"]),
    )
    cards = ""
    for r in fails[:4]:
        img = ""
        if r["snapshot"] and (BASELINE_RUN / "snapshots" / r["snapshot"]).exists():
            img = (
                f'<img src="{_img64(BASELINE_RUN / "snapshots" / r["snapshot"])}" '
                f'alt="seed {r["seed"]}">'
            )
        cards += (
            f'<div class="card">{img}<div class="cap"><b>seed {r["seed"]}</b> — '
            f'stacked {r["outcome"]["stack_height"]} of 3 — '
            f'{r["category"].replace("_", " ")}<br>'
            f'watch it happen: '
            f'<code>python render_video.py {r["seed"]} --policy v1</code>'
            f"</div></div>"
        )

    # --- Section 2: the gate audit -----------------------------------------
    # True-rate table: what n=50 said vs what n=1000 pinned down.
    # v1/v2 from the committed n=50 runs; mild/heavy were measured on the
    # n=100 calibration sweeps — the sample size is stated in the cell so no
    # number implies a run that doesn't exist.
    n50 = {
        "v1": "10% (n=50)",
        "v2": "10% (n=50)",
        "mild (2mm noise)": "6% (n=100)",
        "heavy (5mm noise)": "2% (n=100)",
    }
    truth_rows = ""
    for name, run in TRUE_RUNS.items():
        m = _meta(run)
        tlo, thi = m["wilson95"]
        truth_rows += (
            f"<tr><td>{name}</td><td>{n50[name]}</td>"
            f'<td><b>{m["success_rate"]:.1%}</b></td>'
            f"<td>{tlo:.1%}–{thi:.1%}</td></tr>"
        )

    # Real-variant verdict strips (20 disjoint gates each from n=1000 records).
    v1_blocks = gate.blocks_from_records(TRUE_RUNS["v1"] / "records.jsonl")
    v2_blocks = gate.blocks_from_records(TRUE_RUNS["v2"] / "records.jsonl")

    # Oracle strips nearest the threshold: watch the gate flip.
    sweep = {lv["p"]: lv for lv in oracle["sweep"]}

    def oracle_strip(p):
        lv = sweep[p]
        results = [
            {"rep": i, "successes": s, "pass": ps}
            for i, (s, ps) in enumerate(
                zip(lv["pipeline_successes"], lv["pipeline_pass"])
            )
        ]
        return _strip(
            results,
            f"calibrated reference policy, true rate {p:.0%} — "
            f"measured pass rate {lv['pipeline_pass_rate']:.1%} "
            f"(exact theory: {lv['theory_pass_prob']:.1%})",
        )

    theory_rows = ""
    for lv in oracle["sweep"]:
        theory_rows += (
            f'<tr><td>{lv["p"]:.0%}</td>'
            f'<td>{lv["pipeline_pass_rate"]:.1%}</td>'
            f'<td>{lv["bernoulli_pass_rate"]:.1%}</td>'
            f'<td>{lv["theory_pass_prob"]:.1%}</td>'
            f'<td>{lv["dispersion"]["ratio"]:.2f}</td></tr>'
        )
    cal = oracle["calibration"]

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stacking cell — evaluation & gate audit</title>
<style>{CSS}{EXTRA_CSS}</style></head><body>

<h1>Stacking cell evaluation &amp; gate audit</h1>
<div class="sub">baseline (v1) at n=50 · commit {meta["git_commit"]} · mujoco
{meta["mujoco"]} · tip probability {meta["tip_probability"]}</div>

<div class="hero">
  <div class="tile"><div class="l">Success rate (n=50)</div>
    <div class="k">{k / n:.0%}</div>
    <div class="d">{k} of {n} episodes succeeded. The honest range around
    that number (95% confidence interval, Wilson): <b>{lo:.0%}–{hi:.0%}</b></div>
    <div class="d">In other words: 50 episodes can't tell a {lo:.0%} policy
    from a {hi:.0%} one. A later 1,000-episode run pinned this same policy
    at 5.3% — see the gate audit below.</div>
    <div class="d">Production gate (≥90% at n=50): <b>does not pass</b></div></div>
  <div class="tile"><div class="l">How high the stacks got</div>
    <div class="k">{heights[3]}·{heights[2]}·{heights[1]}·{heights[0]}</div>
    <div class="d">{heights[3]} episodes ended with all three cylinders
    stacked, {heights[2]} with two, {heights[1]} with one, {heights[0]} with
    none. Partial stacks are counted here, on their own — they are never
    mixed into the headline success rate.</div></div>
  <div class="tile"><div class="l">Cost</div>
    <div class="k">{meta["wall_total_s"] / n:.0f}s</div>
    <div class="d">seconds of real time per episode — the full {n}-episode
    run took {meta["wall_total_s"]:.0f} seconds on a laptop</div></div>
</div>

<h2>Why episodes failed, ranked ({n - k} failures)</h2>
<div class="bars">{bars}</div>

<h2>The worst episodes, first — each one replayable with a single command</h2>
<div class="gallery">{cards}</div>

<hr style="border:none;border-top:1px solid var(--line);margin:40px 0">

<h1>The gate audit</h1>
<div class="sub">Production rule under test: ship if ≥45 of 50 episodes succeed.</div>
<div class="callout">The policies in this audit: <b>v1</b> — the scripted
baseline; it skips tipped-over parts. <b>v2</b> — v1 plus a maneuver that
stands tipped parts up first. <b>mild / heavy</b> — v1 seeing the cylinders
through 2&nbsp;mm / 5&nbsp;mm of seeded perception error. The near-threshold
strips further down use <b>calibrated reference policies</b> — instruments
with a dialed success rate, labeled wherever they appear.</div>

<h2>What 50 episodes said vs. what 1,000 revealed</h2>
<table class="theory"><tr><th>policy</th><th>small-sample measured</th>
<th>true rate (n=1000)</th><th>95% CI</th></tr>{truth_rows}</table>
<div class="callout">The gate-sized sample overestimated v1 <b>2×</b> (10% vs
5.3%). v2 trends better than v1 (6.6% vs 5.3%) but <b>even n=1000 does not
resolve them</b> — their CIs overlap, as do the mild-noise variant's. Three
mechanically different policies whose success counts never separate: the gate
is mechanism-blind; the failure taxonomy above is what tells these policies
apart.</div>

<h2>Two policy variants, side by side — every gate verdict</h2>
<div class="two">
<div>{_strip(v1_blocks, "v1 — true rate 5.3% — 20 disjoint n=50 gates")}</div>
<div>{_strip(v2_blocks, "v2 — true rate 6.6% — 20 disjoint n=50 gates")}</div>
</div>
<div class="callout">Far from the threshold the gate is reliable: two below-spec
policies, 40 gates, zero false passes. The gate's errors live near the
threshold — probed below with calibrated reference policies (an instrument we
declare openly: seeded dial-a-rate policies whose stacks are judged by the
same judge as everything else).</div>

<h2>Watch the gate flip — calibrated policies near the threshold</h2>
{oracle_strip(0.88)}
{oracle_strip(0.92)}
<div class="callout"><b>A below-spec 88% policy ships ~4 times in 10. A
policy at exactly 90% spec is rejected ~4 times in 10.</b> Each square is a
full 50-episode gate on its own seeds, judged episode by episode.</div>

<h2>Measured vs. theory, all levels</h2>
<table class="theory"><tr><th>true rate</th><th>pipeline (200 gates)</th>
<th>coin-flip (20k gates)</th><th>exact theory</th><th>dispersion ratio</th></tr>
{theory_rows}</table>
<div class="callout">Instrument calibration: dialed {cal["dialed_p"]:.0%},
pipeline measured <b>{cal["measured"]:.1%}</b> over n={cal["n"]} judged
episodes. Scope, stated plainly: the reference policy draws each outcome from
a seeded rate and arranges the scene for the real judge to rule — so this
sweep validates the <b>measurement chain</b> (judge, gate arithmetic, seeding)
against a known truth; by construction it cannot disagree with the coin-flip
model unless the judge misrules an arranged scene. The gate's error rates
therefore rest on the binomial model plus its independence assumption — which
is checked on the <b>real</b> policies (dispersion ratios ≈1: v1 0.93, v2
1.06, mild 0.99, heavy 1.17), not assumed.</div>

<h2>Reproduce</h2>
<div class="note">Every number regenerable from a fresh clone — commands in
the README. Declared blind spot: grasping uses a kinematic attach within
20&nbsp;mm; grasp-slip and drop-in-transit failures cannot occur in this
evaluation.</div>
</body></html>"""

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html)
    print(f"final report: {OUT}  ({OUT.stat().st_size / 1e6:.2f} MB)")
    return OUT


if __name__ == "__main__":
    build()
