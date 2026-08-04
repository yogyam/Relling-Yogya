"""Part C: the 60-second run report — one self-contained HTML file.

Reads a run directory (records.jsonl + meta.json + snapshots/) and writes
report.html with everything inlined: headline rate + Wilson interval, partial
stacks reported separately, the failure taxonomy ranked, a worst-episodes
gallery, the full per-episode table, and the exact reproduction command.
"""

import base64
import json
from pathlib import Path

from harness import CATEGORY_BLURBS

CSS = """
:root { color-scheme: light;
  --surface:#fcfcfb; --card:#f4f4f2; --line:#e3e2de;
  --ink:#0b0b0b; --ink2:#52514e; --ink3:#8a8984;
  --bar:#2a78d6; --good:#008300; --bad:#c73433; }
@media (prefers-color-scheme: dark) { :root { color-scheme: dark;
  --surface:#1a1a19; --card:#242423; --line:#3a3937;
  --ink:#ffffff; --ink2:#c3c2b7; --ink3:#8a8984;
  --bar:#3987e5; --good:#31b331; --bad:#e66767; } }
* { box-sizing:border-box; margin:0; }
body { background:var(--surface); color:var(--ink);
  font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  max-width:1000px; margin:0 auto; padding:32px 24px 64px; }
h1 { font-size:22px; margin-bottom:4px; }
h2 { font-size:16px; margin:36px 0 12px; }
.sub { color:var(--ink2); font-size:13px; }
.hero { display:flex; gap:16px; flex-wrap:wrap; margin-top:20px; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:16px 20px; flex:1; min-width:180px; }
.tile .k { font-size:34px; font-weight:650; letter-spacing:-0.5px; }
.tile .l { color:var(--ink2); font-size:12px; text-transform:uppercase;
  letter-spacing:0.06em; margin-bottom:6px; }
.tile .d { color:var(--ink2); font-size:13px; margin-top:4px; }
.bars { display:grid; grid-template-columns:max-content 1fr max-content;
  gap:8px 12px; align-items:center; }
.bars .name { font-size:14px; }
.bars .track { background:var(--card); border-radius:4px; height:18px; }
.bars .fill { background:var(--bar); border-radius:4px 4px 4px 4px; height:18px; }
.bars .count { font-variant-numeric:tabular-nums; color:var(--ink2); }
.blurb { grid-column:1/-1; color:var(--ink3); font-size:12.5px; margin:-4px 0 4px; }
.gallery { display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr));
  gap:14px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
  overflow:hidden; }
.card img { width:100%; display:block; }
.card .cap { padding:8px 12px; font-size:12.5px; color:var(--ink2); }
.card .cap b { color:var(--ink); }
table { border-collapse:collapse; width:100%; font-size:13px; }
th { text-align:left; color:var(--ink2); font-weight:600; font-size:12px;
  text-transform:uppercase; letter-spacing:0.05em; }
th,td { padding:6px 10px; border-bottom:1px solid var(--line);
  font-variant-numeric:tabular-nums; }
.ok { color:var(--good); font-weight:600; }
.no { color:var(--bad); font-weight:600; }
.mini { display:inline-block; width:9px; height:9px; border-radius:2px;
  margin-right:3px; }
.up { background:var(--bar); } .tp { background:var(--ink3); }
code { background:var(--card); border:1px solid var(--line); border-radius:6px;
  padding:2px 6px; font-size:12.5px; }
.note { background:var(--card); border:1px solid var(--line); border-radius:10px;
  padding:12px 16px; font-size:13px; color:var(--ink2); margin-top:10px; }
"""


def _img64(path: Path) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(path.read_bytes()).decode()


def build_report(run_dir: str | Path) -> Path:
    run = Path(run_dir)
    meta = json.loads((run / "meta.json").read_text())
    records = [json.loads(l) for l in (run / "records.jsonl").read_text().splitlines()]

    k, n = meta["successes"], meta["n"]
    lo, hi = meta["wilson95"]
    heights = meta["stack_heights"]
    gate = "PASSES" if k / n >= 0.90 else "does not pass"

    # --- taxonomy bars -----------------------------------------------------
    tax = meta["taxonomy"]
    max_c = max(tax.values(), default=1)
    bars = ""
    for cat, c in tax.items():
        pct = 100 * c / max_c
        blurb = CATEGORY_BLURBS.get(cat, "")
        bars += (
            f'<div class="name">{cat.replace("_", " ")}</div>'
            f'<div class="track" title="{c} of {n} episodes">'
            f'<div class="fill" style="width:{pct:.0f}%"></div></div>'
            f'<div class="count">{c}</div>'
            f'<div class="blurb">{blurb}</div>'
        )

    # --- worst episodes: lowest stack first, then seed ---------------------
    policy_flag = "v2" if "V2" in meta["policy"] else "v1"
    fails = [r for r in records if not r["outcome"]["success"]]
    fails.sort(key=lambda r: (r["outcome"]["stack_height"], r["seed"]))
    cards = ""
    for r in fails[:8]:
        img = ""
        if r["snapshot"]:
            p = run / "snapshots" / r["snapshot"]
            if p.exists():
                img = f'<img src="{_img64(p)}" alt="final state of seed {r["seed"]}">'
        cards += (
            f'<div class="card">{img}<div class="cap">'
            f'<b>seed {r["seed"]}</b> · h={r["outcome"]["stack_height"]} · '
            f'{r["category"].replace("_", " ")}<br>'
            f'lifted {r["policy"]["picks_lifted"]}/{r["policy"]["picks_attempted"]}'
            f' · watch it: <code>python render_video.py {r["seed"]}'
            f' --policy {policy_flag}</code>'
            f"</div></div>"
        )

    # --- full table --------------------------------------------------------
    rows = ""
    for r in records:
        o = r["outcome"]
        spawn = "".join(
            f'<span class="mini {"up" if c["state"] == "upright" else "tp"}" '
            f'title="{name}: {c["state"]}"></span>'
            for name, c in r["init"].items()
        )
        verdict = '<span class="ok">✓ pass</span>' if o["success"] else \
                  '<span class="no">✗ fail</span>'
        cat = "—" if r["category"] == "success" else r["category"].replace("_", " ")
        rows += (
            f'<tr><td>{r["seed"]}</td><td>{spawn}</td>'
            f'<td>{r["policy"]["picks_lifted"]}/{r["policy"]["picks_attempted"]}</td>'
            f'<td>{o["stack_height"]}</td><td>{verdict}</td><td>{cat}</td>'
            f'<td>{r["timing"]["wall_s"]}s</td></tr>'
        )

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Stacking eval — {meta["policy"]} n={n}</title>
<style>{CSS}</style></head><body>
<h1>Stacking cell evaluation — {meta["policy"]}</h1>
<div class="sub">{n} seeded episodes (seeds {meta["seed_start"]}–{meta["seed_start"] + n - 1})
 · tip probability {meta["tip_probability"]} · commit {meta["git_commit"]}
 · mujoco {meta["mujoco"]}</div>

<div class="hero">
  <div class="tile"><div class="l">Success rate</div>
    <div class="k">{k / n:.0%}</div>
    <div class="d">{k} of {n} episodes · 95% CI (Wilson): <b>{lo:.0%}–{hi:.0%}</b></div>
    <div class="d">What n={n} actually pins down: the true rate is plausibly
    anywhere in that {(hi - lo) * 100:.0f}-point span — this sample cannot
    distinguish a {lo:.0%} policy from a {hi:.0%} one.</div>
    <div class="d">Production gate (≥90% at n=50): <b>{gate}</b></div></div>
  <div class="tile"><div class="l">Stack height reached (all episodes)</div>
    <div class="k">{heights[3]}·{heights[2]}·{heights[1]}·{heights[0]}</div>
    <div class="d">3-stack · 2-stack · 1 · none — partial stacks are reported
    here and <b>never</b> blended into the headline rate</div></div>
  <div class="tile"><div class="l">Cost</div>
    <div class="k">{meta["wall_total_s"] / n:.0f}s</div>
    <div class="d">per episode (wall) · {meta["wall_total_s"]:.0f}s total</div></div>
</div>

<h2>Failure taxonomy — ranked by count ({n - k} failures)</h2>
<div class="bars">{bars}</div>

<h2>Worst episodes first</h2>
<div class="gallery">{cards}</div>

<h2>Every episode</h2>
<table><tr><th>seed</th><th>spawn</th><th>lifted</th><th>height</th>
<th>verdict</th><th>failure category</th><th>wall</th></tr>{rows}</table>
<div class="sub" style="margin-top:6px">spawn dots: <span class="mini up"></span>
upright · <span class="mini tp"></span> tipped</div>

<h2>Reproduce</h2>
<div class="note"><code>{meta["command"]}</code><br>
Same seeds ⇒ same episodes, bit-for-bit. Known blind spot (declared): grasping
uses a kinematic attach within 20&nbsp;mm — grasp-slip and drop-in-transit
failures cannot occur in this evaluation.</div>
</body></html>"""

    out = run / "report.html"
    out.write_text(html)
    print(f"report: {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return out
