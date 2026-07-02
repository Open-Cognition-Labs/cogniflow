# ruff: noqa: E501
"""The static audit dashboard markup . Dependency-free HTML+vanilla JS served at /.

Kept in its own module (line-length checks off) because it is a markup blob, not Python.
The JS renders only what the API returns - it never recomputes intervals client-side, so it
cannot re-leak present knowledge into a past replay (the un-knowing is the engine's job)."""

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cogniflow Audit Dashboard</title>
<style>
 body{font:14px/1.5 system-ui,sans-serif;margin:0;background:#0f1115;color:#e6e6e6}
 header{padding:16px 24px;background:#161922;border-bottom:1px solid #262a35}
 h1{font-size:18px;margin:0} .sub{color:#9aa4b2;font-size:12px;margin-top:4px}
 main{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:24px}
 section{background:#161922;border:1px solid #262a35;border-radius:10px;padding:16px}
 section.full{grid-column:1 / -1}
 h2{font-size:14px;margin:0 0 10px;color:#cdd6e4} label{font-size:12px;color:#9aa4b2}
 input[type=date]{background:#0f1115;color:#e6e6e6;border:1px solid #2c3140;border-radius:6px;padding:5px}
 .fact{border:1px solid #262a35;border-radius:8px;padding:10px;margin:8px 0;cursor:pointer}
 .fact:hover{border-color:#3a64ff} .stmt{font-weight:600}
 .meta{color:#9aa4b2;font-size:12px;margin-top:4px}
 .badge{display:inline-block;font-size:11px;padding:1px 7px;border-radius:10px;margin-left:6px}
 .authoritative{background:#143d2b;color:#56d39a} .derived{background:#3d3414;color:#e2c04b}
 .none{background:#33181c;color:#e07a86}
 .superseded{opacity:.6;text-decoration:line-through}
 .note{background:#10233a;border:1px solid #1d3a5c;color:#a9c7ee;font-size:12px;padding:8px;border-radius:6px;margin-bottom:10px}
 pre{white-space:pre-wrap;background:#0f1115;border:1px solid #262a35;border-radius:6px;padding:10px;font-size:12px}
</style></head>
<body>
<header><h1>Cogniflow Audit Dashboard</h1>
<div class="sub">Read-only window onto the belief ledger. The one screen no plain RAG can build.</div></header>
<main>
 <section><h2>Current beliefs (now)</h2><div id="current"></div></section>
 <section>
   <h2>Event-time axis - what was TRUE as of</h2>
   <label>as_of <input type="date" id="evt" value="2026-04-01"></label>
   <div id="event"></div>
 </section>
 <section class="full">
   <h2>System-time replay - what the system KNEW as of (the un-knowing)</h2>
   <div class="note">Scrub to a past moment S: a fact superseded <b>after</b> S reads believed-then and
   un-superseded - its current invalid_at is <b>not</b> shown. The engine un-knows; this view renders
   only what it returns.</div>
   <label>system_time <input type="date" id="sys" value="2026-04-01"></label>
   <div id="replay"></div>
 </section>
 <section class="full"><h2>Provenance trace</h2>
   <div class="sub">Click any fact above to trace its source and what superseded it.</div>
   <pre id="prov">(no selection)</pre>
 </section>
</main>
<script>
const fmt = d => d ? d.slice(0,10) : " - ";
function factHtml(b){
  const cls = b.invalid_at ? "fact superseded" : "fact";
  const src = b.valid_at_source || "none";
  const prov = b.provenance.map(p=>p.display).join(", ") || " - ";
  return `<div class="${cls}" onclick="trace('${b.belief_id}')">
    <div class="stmt">${b.statement}<span class="badge ${src}">${src}</span></div>
    <div class="meta">valid ${fmt(b.valid_at)} &rarr; ${b.invalid_at?("invalid "+fmt(b.invalid_at)):"present"}
      &middot; source: ${prov}</div></div>`;
}
async function load(url, el){
  const r = await fetch(url); const j = await r.json();
  document.getElementById(el).innerHTML = (j.beliefs||[]).map(factHtml).join("") || "<div class='meta'>(none)</div>";
}
async function trace(id){
  const r = await fetch("/audit/provenance/"+id); document.getElementById("prov").textContent = JSON.stringify(await r.json(), null, 2);
}
function refresh(){
  load("/audit/current","current");
  load("/audit/event?as_of="+document.getElementById("evt").value,"event");
  load("/audit/replay?system_time="+document.getElementById("sys").value,"replay");
}
document.getElementById("evt").addEventListener("change", ()=>load("/audit/event?as_of="+evt.value,"event"));
document.getElementById("sys").addEventListener("change", ()=>load("/audit/replay?system_time="+sys.value,"replay"));
refresh();
</script>
</body></html>"""
