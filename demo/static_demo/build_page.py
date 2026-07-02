# ruff: noqa: E501
"""Build the self-contained static demo page from the REAL captured run (demo_data.json).

Inlines the captured data into index.html so the page works with zero setup (double-click,
no server). No network - it only reads the already-captured, real run. Line-length checks off:
this module is mostly an HTML/CSS/JS markup blob, not Python.
Run: python demo/static_demo/build_page.py
"""

from __future__ import annotations

import json
import pathlib

HERE = pathlib.Path(__file__).parent
DATA = HERE / "demo_data.json"
OUT = HERE / "index.html"

TEMPLATE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cogniflow - the RAG that knows *when*</title>
<style>
 body{font:15px/1.6 system-ui,sans-serif;margin:0;background:#0f1115;color:#e8eaed}
 .wrap{max-width:920px;margin:0 auto;padding:28px 20px 60px}
 h1{font-size:24px;margin:0 0 4px} .tag{color:#9aa4b2;margin:0 0 24px}
 .card{background:#161922;border:1px solid #262a35;border-radius:12px;padding:18px 20px;margin:16px 0}
 .lead{border-color:#2c5cff55;background:#111a33}
 h2{font-size:15px;letter-spacing:.03em;text-transform:uppercase;color:#9aa4b2;margin:0 0 12px}
 .q{font-weight:600;color:#cdd6e4;margin-bottom:10px}
 .row{display:flex;gap:12px;margin:8px 0;align-items:baseline}
 .k{flex:0 0 118px;color:#9aa4b2;font-size:13px}
 .a{flex:1} .a b{color:#7fd1a8}
 .bad{color:#e07a86}
 .badge{display:inline-block;font-size:11px;padding:1px 8px;border-radius:10px;margin-left:6px}
 .derived{background:#3d3414;color:#e2c04b} .authoritative{background:#143d2b;color:#56d39a}
 .none{background:#33181c;color:#e07a86}
 table{width:100%;border-collapse:collapse;margin-top:8px} td,th{padding:6px 8px;text-align:left;border-bottom:1px solid #262a35;font-size:14px}
 .lift{color:#56d39a;font-weight:600}
 .fact{font-size:13px;color:#b7c0cf;border-left:2px solid #2c3140;padding-left:10px;margin:6px 0}
 code{background:#0f1115;border:1px solid #262a35;border-radius:5px;padding:1px 5px;font-size:13px}
 .foot{color:#9aa4b2;font-size:13px;margin-top:22px}
 a{color:#7aa2ff}
</style></head>
<body><div class="wrap">
<h1>Cogniflow - the RAG that knows <em>when</em></h1>
<p class="tag">Same corpus, same model. The only difference is memory. A real captured run - not a mockup.</p>

<div class="card lead">
 <h2>The one thing plain RAG can't do: answer "as of"</h2>
 <div class="q" id="q"></div>
 <div class="row"><div class="k">Cogniflow - now</div><div class="a" id="now"></div></div>
 <div class="row"><div class="k">Cogniflow - as of 2015</div><div class="a" id="past"></div></div>
 <div class="row"><div class="k bad">Plain RAG</div><div class="a bad" id="plain"></div></div>
</div>

<div class="card">
 <h2>A cited answer that knows how sure it is</h2>
 <div class="tag">The "now" answer stands on these facts (each labeled by confidence + source):</div>
 <div id="facts"></div>
</div>

<div class="card">
 <h2>Reranker - measured on a confusable corpus, not assumed</h2>
 <div class="tag" id="rr-note"></div>
 <table><thead><tr><th>configuration</th><th>top-1</th><th>MRR</th></tr></thead>
 <tbody id="rr"></tbody></table>
 <div class="tag" id="rr-verdict" style="margin-top:10px"></div>
</div>

<div class="card">
 <h2>Faithful under thin context</h2>
 <div class="q" id="weakq"></div><div class="a" id="weak"></div>
</div>

<p class="foot" id="foot"></p>
</div>
<script>
const D = __DATA__;
const badge = s => `<span class="badge ${s}">${s}</span>`;
const conf = c => Object.entries(c||{}).map(([k,v])=>`${badge(k)}&times;${v}`).join(" ");
document.getElementById("q").textContent = D.as_of_headline.query;
document.getElementById("now").innerHTML = `<b>${D.as_of_headline.now.answer}</b> ${conf(D.as_of_headline.now.confidence)}`;
document.getElementById("past").innerHTML = `<b>${D.as_of_headline.past_2015.answer}</b> ${conf(D.as_of_headline.past_2015.confidence)}`;
document.getElementById("plain").textContent = D.as_of_headline.plain_rag_note;
document.getElementById("facts").innerHTML = (D.as_of_headline.now.facts||[]).map(f =>
  `<div class="fact">${f.statement} ${badge(f.valid_at_source)} <span style="color:#6b7480">source: ${(f.provenance||[]).join(", ")||"-"}</span></div>`).join("");
const rr = D.reranker;
document.getElementById("rr-note").textContent = `Golden set n=${rr.golden_size}. Reranker: ${rr.model}.`;
document.getElementById("rr").innerHTML =
  `<tr><td>retrieval only (BGE-M3, reranker OFF)</td><td>${rr.off.top1}/${rr.golden_size}</td><td>${rr.off.mrr}</td></tr>`+
  `<tr><td>+ reranker ON</td><td>${rr.on.top1}/${rr.golden_size}</td><td>${rr.on.mrr}</td></tr>`;
const dTop1 = rr.on.top1 - rr.off.top1, dMrr = (rr.on.mrr - rr.off.mrr).toFixed(3);
document.getElementById("rr-verdict").innerHTML = dTop1>0 || dMrr>0
  ? `<span class="lift">Lift: top-1 +${dTop1}, MRR +${dMrr}</span> on hard indirect queries - the reranker earns its place as an opt-in quality tier (off by default for the GPU-free path).`
  : `No lift on this corpus - the retriever already sets the ceiling; reranker stays off by default.`;
document.getElementById("weakq").textContent = D.weak_context.query;
document.getElementById("weak").textContent = D.weak_context.answer;
document.getElementById("foot").innerHTML =
  `Captured ${D.captured_at} over a ${D.corpus_size}-fact confusable corpus. `+
  `Run it yourself: <code>python demo/capture_demo.py</code> (reproduces this run) and `+
  `<code>cogniflow.serving.audit.run(backend)</code> (the live replay dashboard).`;
</script>
</body></html>"""


def main() -> None:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT} ({len(html)} bytes) from real capture {data['captured_at']}")


if __name__ == "__main__":
    main()
