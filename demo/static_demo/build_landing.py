# ruff: noqa: E501
"""Build the Cogniflow landing page from REAL captured runs.

Inlines demo_data.json (the as-of head-to-head) and benchmark_data.json (the two-panel
benchmark) into a self-contained landing.html - no build step, no CDN, no fabricated numbers.
If benchmark_data.json is missing it refuses to build (run demo/benchmark.py first): a landing
page for an audit product must not carry an unmeasured number.

Positioning: the auditable, self-hostable belief ledger for agents. Leads with the as-of axis.
No "first temporal RAG" claim. The honest tie row + honest boundaries are the credibility.
Run: python demo/static_demo/build_landing.py
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
DEMO = HERE / "demo_data.json"
BENCH = HERE / "benchmark_data.json"
OUT = HERE / "landing.html"
REPO = "https://github.com/Nagendhra-web/cogniflow"

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cogniflow - the auditable, self-hostable belief ledger for agents</title>
<style>
 :root{--bg:#0f1115;--card:#161922;--line:#262a35;--fg:#e8eaed;--mut:#9aa4b2;--win:#56d39a;--warn:#e2c04b;--miss:#5b6472}
 *{box-sizing:border-box}
 body{font:16px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",system-ui,sans-serif;margin:0;background:var(--bg);color:var(--fg)}
 .wrap{max-width:960px;margin:0 auto;padding:0 22px}
 section{padding:92px 0;border-bottom:1px solid var(--line)}
 .eyebrow{color:var(--mut);font-size:13px;letter-spacing:.14em;text-transform:uppercase;margin:0 0 18px}
 h1{font-size:clamp(34px,6vw,60px);line-height:1.08;letter-spacing:-.02em;margin:0 0 20px;max-width:16ch}
 h2{font-size:clamp(24px,3.4vw,34px);letter-spacing:-.01em;margin:0 0 10px}
 .sub{font-size:clamp(17px,2.2vw,21px);color:#c3cad6;max-width:60ch;margin:0 0 34px}
 .lede{color:var(--mut);max-width:62ch;margin:0 0 26px}
 .cta{display:flex;gap:14px;flex-wrap:wrap}
 a.btn{display:inline-block;text-decoration:none;padding:13px 22px;border-radius:10px;font-weight:600;font-size:15px}
 .btn.p{background:#fff;color:#000} .btn.p:hover{background:#e7e7e7}
 .btn.s{border:1px solid #3a4150;color:var(--fg)} .btn.s:hover{background:#ffffff10}
 .proof{margin-top:40px;background:var(--card);border:1px solid var(--line);border-left:3px solid var(--win);border-radius:12px;padding:18px 20px}
 .proof .q{color:var(--mut);font-size:14px;margin-bottom:10px}
 .proof .r{margin:6px 0} .proof b{color:var(--win)} .proof .x{color:#e07a86}
 table{width:100%;border-collapse:collapse;margin-top:10px}
 th,td{text-align:left;padding:12px 10px;border-bottom:1px solid var(--line);font-size:15px;vertical-align:top}
 th{color:var(--mut);font-weight:600;font-size:13px;letter-spacing:.04em;text-transform:uppercase}
 .win{color:var(--win);font-weight:600} .miss{color:var(--miss)} .tie{color:var(--warn);font-weight:600}
 .panels{display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-top:8px}
 @media(max-width:680px){.panels{grid-template-columns:1fr}}
 .panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:20px}
 .panel h3{margin:0 0 4px;font-size:15px} .panel .cap{color:var(--mut);font-size:13px;margin:0 0 16px}
 .score{display:flex;justify-content:space-between;align-items:baseline;margin:10px 0}
 .score .name{color:var(--mut);font-size:14px} .score .val{font-size:26px;font-weight:700}
 .bar{height:7px;border-radius:4px;background:#222836;overflow:hidden;margin-top:4px}
 .bar > i{display:block;height:100%}
 ul.b{list-style:none;padding:0;margin:0;max-width:64ch} ul.b li{padding:10px 0;border-bottom:1px solid var(--line);color:#c3cad6}
 ul.b li b{color:var(--fg)}
 code{background:#0b0d12;border:1px solid var(--line);border-radius:6px;padding:2px 7px;font-size:14px;color:#cdd6e4}
 .note{color:var(--mut);font-size:13px;margin-top:14px}
 footer{padding:40px 0 70px;color:var(--mut);font-size:14px}
 footer a{color:#7aa2ff}
</style></head>
<body>
<div class="wrap">

<section>
 <p class="eyebrow">Self-hostable &middot; open source (Apache-2.0) &middot; built on Graphiti &times; LlamaIndex</p>
 <h1>The auditable, self-hostable belief ledger for agents.</h1>
 <p class="sub">Plain RAG can tell you what's true <em>now</em>. Cogniflow tells you what your agent believed at any <em>past</em> moment - and proves it. Temporally-correct context and cited answers, running in your own VPC, where your data never leaves.</p>
 <div class="cta">
  <a class="btn p" href="index.html">See the live head-to-head &rarr;</a>
  <a class="btn s" href="__REPO__">Read the code</a>
 </div>
 <div class="proof" id="proof"></div>
</section>

<section>
 <p class="eyebrow">The one thing plain RAG can't do</p>
 <h2>Ask "as of when?"</h2>
 <p class="lede">Modern RAG (and hosted memory) has no time axis. It answers from whatever it retrieves today. Cogniflow filters context to the moment you ask about, so the answer is temporally correct - and cites the fact it stood on.</p>
 <table>
  <thead><tr><th>Same question, add "as of 2015"</th><th>Answer</th></tr></thead>
  <tbody>
   <tr><td class="miss">Plain RAG</td><td class="miss">Can't isolate the past - no time axis. It sees both the old and new fact and hedges or picks wrong.</td></tr>
   <tr><td class="win">Cogniflow (as of 2015)</td><td id="asof-a" class="win"></td></tr>
  </tbody>
 </table>
 <div class="cta" style="margin-top:26px"><a class="btn s" href="index.html">Watch it in the live demo &rarr;</a></div>
</section>

<section>
 <p class="eyebrow">Positioned by contrast</p>
 <h2>We are the thing the recall-optimized clouds vacated</h2>
 <p class="lede">Not a worse hosted-memory service. The answer to a question their governed cloud structurally can't answer - for the regulated buyer who can't send data out. We tie on retrieval (we inherit Graphiti's); we win where they're blank.</p>
 <table>
  <thead><tr><th>Capability</th><th>Cogniflow</th><th>Hosted recall-optimized memory</th></tr></thead>
  <tbody>
   <tr><td>Standard retrieval / recall</td><td class="tie">Tie - inherited, not a win</td><td class="win">Strong</td></tr>
   <tr><td>Temporal correctness / as-of replay</td><td class="win">Yes</td><td class="miss"> - no time axis</td></tr>
   <tr><td>Auditable provenance - "why did this change?"</td><td class="win">Yes</td><td class="miss"> - </td></tr>
   <tr><td>System-time replay (what did it <em>know</em> then)</td><td class="win">Yes</td><td class="miss"> - </td></tr>
   <tr><td>Self-hostable / in-VPC / data never leaves</td><td class="win">Yes</td><td class="miss"> - hosted SaaS</td></tr>
  </tbody>
 </table>
 <p class="note">The tie row is the point: an all-green matrix is the one nobody believes.</p>
</section>

<section>
 <p class="eyebrow">Real benchmark - every number from a live run</p>
 <h2>Where we tie, and where it isn't close</h2>
 <p class="lede">Same corpus, same model, same embeddings. The only difference is memory. Panel 1 is an honest tie on stable facts. Panel 2 is what a temporal store is <em>for</em>.</p>
 <div class="panels" id="panels"></div>
 <p class="note" id="bench-note"></p>
</section>

<section>
 <p class="eyebrow">Honesty is the marketing</p>
 <h2>What we are - and what we're not</h2>
 <ul class="b">
  <li><b>Structured input is deterministic.</b> Facts you assert (OKF <code>fact</code> keys) get precise temporal validity. Facts extracted from raw prose are only as good as the extraction LLM - each served fact is labeled with its confidence, so nothing is laundered.</li>
  <li><b>Retrieval is inherited, not class-leading.</b> We use Graphiti's retrieval; we don't out-retrieve the recall specialists. An optional reranker is measured, off by default, on by evidence.</li>
  <li><b>Not "first" at temporal RAG.</b> Validity filters and temporal-graph RAG exist. What we ship is honest <em>system-time replay</em> - the un-knowing invariant - as auditable, self-hostable infrastructure.</li>
  <li><b>Read-only audit surface.</b> The replay dashboard is a window onto the ledger, never a second product; the answer path never writes.</li>
 </ul>
</section>

<section style="border-bottom:none">
 <p class="eyebrow">Try it</p>
 <h2>Run it in your own environment</h2>
 <p class="lede">Your infrastructure, your LLM, your embedder - your data never leaves. For an audit product, the strongest CTA is: read the code that produces the audit trail.</p>
 <div class="cta">
  <a class="btn p" href="__REPO__">Read the code &rarr;</a>
  <a class="btn s" href="index.html">Reproduce the demo</a>
 </div>
 <p class="note">Reproduce every number here: <code>python demo/capture_demo.py</code> and <code>python demo/benchmark.py</code>.</p>
</section>

<footer>
 Cogniflow - temporal, self-falsifying belief substrate for agentic RAG. Apache-2.0.
 Benchmark captured <span id="cap"></span>. All figures from live runs; none fabricated.
</footer>

</div>
<script>
const DEMO = __DEMO__, BENCH = __BENCH__;
const H = DEMO.as_of_headline;
document.getElementById("proof").innerHTML =
  `<div class="q">${H.query}</div>`+
  `<div class="r">Cogniflow, as of 2015 &nbsp;&rarr;&nbsp; <b>${H.past_2015.answer.replace(/\\*\\*/g,"")}</b></div>`+
  `<div class="r">Cogniflow, now &nbsp;&rarr;&nbsp; <b>${H.now.answer.replace(/\\*\\*/g,"")}</b></div>`+
  `<div class="r x">Plain RAG, as of 2015 &nbsp;&rarr;&nbsp; can't answer it at all - no temporal axis.</div>`;
document.getElementById("asof-a").textContent = H.past_2015.answer.replace(/\\*\\*/g,"");

const P = BENCH.panels;
function panel(key, title, cap){
  const p = P[key];
  const pct = s => Math.round(100*s/p.n);
  const row = (name,score,color) =>
    `<div class="score"><span class="name">${name}</span><span class="val" style="color:${color}">${score}/${p.n}</span></div>`+
    `<div class="bar"><i style="width:${pct(score)}%;background:${color}"></i></div>`;
  return `<div class="panel"><h3>${title}</h3><p class="cap">${cap}</p>`+
    row("Plain RAG", p.plain_score, p.plain_score>=p.cogniflow_score?"#56d39a":"#e07a86")+
    `<div style="height:14px"></div>`+
    row("Cogniflow", p.cogniflow_score, "#56d39a")+`</div>`;
}
document.getElementById("panels").innerHTML =
  panel("standard","Standard questions","Stable facts that don't change. Both do well - an honest tie.")+
  panel("as_of","As-of questions","What was true at a past date. Plain RAG has no time axis.");
const dp = P.as_of.plain_score, dc = P.as_of.cogniflow_score, n = P.as_of.n;
document.getElementById("bench-note").textContent =
  `On as-of questions: plain RAG ${dp}/${n}, Cogniflow ${dc}/${n}. Reproduce: python demo/benchmark.py`;
document.getElementById("cap").textContent = (BENCH.captured_at||"").slice(0,10);
</script>
</body></html>"""


def main() -> None:
    if not BENCH.exists():
        raise SystemExit("benchmark_data.json missing - run `python demo/benchmark.py` first "
                         "(a landing page for an audit product must not carry an unmeasured number).")
    demo = json.loads(DEMO.read_text(encoding="utf-8"))
    bench = json.loads(BENCH.read_text(encoding="utf-8"))
    html = (TEMPLATE
            .replace("__DEMO__", json.dumps(demo))
            .replace("__BENCH__", json.dumps(bench))
            .replace("__REPO__", REPO))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)} bytes)")


if __name__ == "__main__":
    main()
