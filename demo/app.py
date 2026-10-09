"""One-page demo app: the answer on the left, its receipts on the right.

    python -m uvicorn demo.app:app --port 8077        (from the repo root)
    # or:  python demo/app.py

The right-hand panel is the whole point: for each claim in the last answer it shows the
receipt, its status, and a command you can run yourself to re-check it. The "self-audit"
button asks the harder question — what has it told me that it cannot back?

Runs with a real model when NEBIUS_API_KEY is set (any OpenAI-compatible endpoint via
RECEIPTS_BASE_URL); otherwise it falls back to a scripted mock so the page can still be
demonstrated without a key. The header says which one you are looking at.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import HTMLResponse, JSONResponse  # noqa: E402

from receipts.agent import Agent  # noqa: E402
from receipts.llm import MockClient, NebiusClient, Reply, ToolCall  # noqa: E402
from receipts.receipts import VERIFIED  # noqa: E402
from receipts.store import Store  # noqa: E402

DB = os.environ.get("RECEIPTS_DB", str(Path(__file__).resolve().parents[1] / "data" / "demo.db"))

app = FastAPI(title="Receipts")

STATE: dict = {}


def get_state() -> dict:
    if STATE:
        return STATE
    real = NebiusClient()
    if real.api_key:
        client, mode = real, "live"
    else:
        # No key: still show the UI, but say so. A demo that silently pretends to be live
        # is exactly the kind of thing this project is against.
        store_seed = [
            Reply(text="", tool_calls=[ToolCall(id="c1", name="recall",
                                                arguments={"query": "where do I live"})]),
            Reply(text="You live in Porto."),
        ]
        client, mode = MockClient(store_seed), "mock (no API key)"
    store = Store(DB)
    if not store.facts(status=None):
        # Seed a cold start so the page is demonstrable: without this, the first question
        # has nothing to recall and the receipts panel has nothing to show.
        store.add_fact("Robin lives in Porto", source_kind="user_statement",
                       source_ref="chat 2026-09-12", source_excerpt="我住在波尔图，Ribeira 那边")
        store.add_fact("Robin is learning to sail", source_kind="user_statement",
                       source_ref="chat 2026-09-20", source_excerpt="我刚开始学帆船")
    STATE.update({
        "store": store,
        "agent": Agent(client, store),
        "mode": mode,
        "base_url": getattr(client, "base_url", "mock"),
        "model": getattr(client, "model_ultra", "mock"),
        "last": None,
    })
    return STATE


def claim_json(c) -> dict:
    r = c.receipt
    return {
        "text": c.text,
        "status": c.status,
        "receipt_kind": r.kind if r else None,
        "receipt_note": r.note if r else "",
        "verify_command": r.verify_command if r else None,
        "evidence": r.evidence if r else {},
    }


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    st = get_state()
    return PAGE.replace("{{MODE}}", st["mode"]).replace("{{MODEL}}", str(st["model"])) \
               .replace("{{BASE}}", str(st["base_url"]))


@app.post("/ask")
async def ask(request: Request) -> JSONResponse:
    st = get_state()
    payload = await request.json()
    question = (payload.get("question") or "").strip()
    if not question:
        return JSONResponse({"error": "empty question"}, status_code=400)
    turn = st["agent"].ask(question)
    st["last"] = turn
    a = turn.answer
    return JSONResponse({
        "question": question,
        "answer": a.text,
        "claims": [claim_json(c) for c in a.claims],
        "counts": a.counts(),
        "overclaim_rate": a.overclaim_rate(),
        "tools": [r.name for r in turn.tool_runs],
        "conflicts": [{"a": x.text, "b": y.text, "ids": [x.id, y.id]}
                      for x, y in st["store"].conflicts()],
    })


@app.get("/audit")
def audit() -> JSONResponse:
    st = get_state()
    store: Store = st["store"]
    unbacked = []
    last = st["last"]
    if last is not None:
        unbacked = [claim_json(c) for c in last.answer.claims if c.status != VERIFIED]
    return JSONResponse({
        "facts_live": len(store.facts()),
        "facts_awaiting_decision": [
            {"id": f.id, "text": f.text} for f in store.facts(status="disputed")
        ],
        "conflicts": [{"a": x.text, "b": y.text, "ids": [x.id, y.id]}
                      for x, y in store.conflicts()],
        "unbacked_in_last_answer": unbacked,
    })


@app.post("/resolve")
async def resolve(request: Request) -> JSONResponse:
    st = get_state()
    payload = await request.json()
    try:
        kept = st["store"].resolve_conflict(keep=payload["keep"], drop=payload["drop"],
                                            reason=payload.get("reason", ""))
    except (KeyError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"kept": {"id": kept.id, "text": kept.text}})


@app.get("/facts")
def facts() -> JSONResponse:
    st = get_state()
    return JSONResponse({
        "facts": [
            {"id": f.id, "text": f.text, "source": f.source_kind, "ref": f.source_ref,
             "excerpt": f.source_excerpt, "status": f.status, "stated": f.created_at}
            for f in st["store"].facts(status=None)
        ]
    })


PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Receipts</title>
<style>
  :root { --ink:#1c1c22; --dim:#6b6b76; --line:#e3e3e8; --ok:#0b7a3b; --warn:#a4610a;
          --bad:#a01414; --bg:#fbfbfd; }
  * { box-sizing:border-box }
  body { margin:0; font:15px/1.5 ui-sans-serif,system-ui,"Segoe UI",sans-serif; color:var(--ink);
         background:var(--bg); }
  header { padding:12px 18px; border-bottom:1px solid var(--line); display:flex; gap:14px;
           align-items:baseline; }
  header b { font-size:16px }
  header span { color:var(--dim); font-size:12px }
  main { display:grid; grid-template-columns:1fr 1fr; gap:0; height:calc(100vh - 54px) }
  section { padding:16px 18px; overflow:auto }
  section + section { border-left:1px solid var(--line) }
  h2 { font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--dim);
       margin:0 0 10px }
  textarea { width:100%; height:64px; padding:9px; border:1px solid var(--line);
             border-radius:8px; font:inherit; resize:vertical; background:#fff }
  button { padding:8px 14px; border:1px solid var(--line); border-radius:8px; background:#fff;
           font:inherit; cursor:pointer }
  button:hover { border-color:#bbb }
  .answer { white-space:pre-wrap; background:#fff; border:1px solid var(--line);
            border-radius:8px; padding:12px; margin:12px 0 }
  .claim { border-left:3px solid var(--line); padding:6px 0 6px 10px; margin:10px 0 }
  .claim.ok   { border-color:var(--ok) }
  .claim.unv  { border-color:var(--bad) }
  .claim.stale{ border-color:var(--warn) }
  .claim.bad  { border-color:var(--bad) }
  .claim .t { font-weight:500 }
  .claim .m { color:var(--dim); font-size:13px; margin-top:3px }
  code { background:#f1f1f5; padding:1px 5px; border-radius:4px; font-size:12px }
  .pill { display:inline-block; font-size:11px; padding:1px 7px; border-radius:999px;
          border:1px solid var(--line); color:var(--dim); margin-right:6px }
  .pill.ok { color:var(--ok); border-color:#bfe3cc }
  .pill.unv, .pill.contradicted { color:var(--bad); border-color:#eec2c2 }
  .pill.stale { color:var(--warn); border-color:#f0dcbb }
  .row { display:flex; gap:10px; align-items:center; margin-top:10px }
  .muted { color:var(--dim); font-size:13px }
</style></head>
<body>
<header>
  <b>Receipts</b>
  <span>a personal AI that shows its work</span>
  <span>mode: <code>{{MODE}}</code></span>
  <span>model: <code>{{MODEL}}</code></span>
  <span>endpoint: <code>{{BASE}}</code></span>
</header>
<main>
  <section>
    <h2>Ask</h2>
    <textarea id="q" placeholder="where do I live?  /  I moved to Berlin last month"></textarea>
    <div class="row">
      <button onclick="ask()">Ask</button>
      <button onclick="audit()">Self-audit</button>
      <span class="muted" id="tools"></span>
    </div>
    <div id="answer" class="answer" style="display:none"></div>
    <div id="auditbox"></div>
  </section>
  <section>
    <h2>Receipts for the last answer</h2>
    <div id="summary" class="muted">nothing asked yet</div>
    <div id="claims"></div>
    <div id="conflicts"></div>
  </section>
</main>
<script>
const esc = s => (s ?? "").replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
function pill(st){ const cls = st==='verified'?'ok':(st==='stale'?'stale':'unv');
  return `<span class="pill ${cls}">${esc(st)}</span>`; }

async function ask(){
  const q = document.getElementById('q').value.trim();
  if(!q) return;
  const r = await fetch('/ask', {method:'POST', headers:{'Content-Type':'application/json'},
                                 body: JSON.stringify({question:q})});
  const d = await r.json();
  document.getElementById('answer').style.display = 'block';
  document.getElementById('answer').textContent = d.answer;
  document.getElementById('tools').textContent = 'tools: ' + (d.tools.join(' · ') || 'none');
  const c = d.counts;
  document.getElementById('summary').innerHTML =
    `verified ${c.verified} · stale ${c.stale} · unverified ${c.unverified} · ` +
    `contradicted ${c.contradicted} &nbsp;→&nbsp; <b>overclaim ${(d.overclaim_rate*100).toFixed(0)}%</b>`;
  document.getElementById('claims').innerHTML = d.claims.map(cl => `
    <div class="claim ${cl.status==='verified'?'ok':(cl.status==='stale'?'stale':'unv')}">
      <div class="t">${pill(cl.status)} ${esc(cl.text)}</div>
      <div class="m">${esc(cl.receipt_kind)} — ${esc(cl.receipt_note)}</div>
      ${cl.verify_command ? `<div class="m">re-check: <code>${esc(cl.verify_command)}</code></div>` : ''}
    </div>`).join('');
  document.getElementById('conflicts').innerHTML = d.conflicts.length ? (
    `<h2 style="margin-top:18px">Open conflicts — waiting for you</h2>` +
    d.conflicts.map(x => `<div class="claim unv"><div class="t">${esc(x.a)}</div>
      <div class="t">vs ${esc(x.b)}</div>
      <div class="m">resolve: <code>python -m receipts.cli resolve ${esc(x.ids[0])} ${esc(x.ids[1])}
      --reason "..."</code></div></div>`).join('')) : '';
}

async function audit(){
  const d = await (await fetch('/audit')).json();
  document.getElementById('auditbox').innerHTML = `
    <h2 style="margin-top:18px">Self-audit</h2>
    <div class="muted">live facts: ${d.facts_live} · awaiting your decision:
      ${d.facts_awaiting_decision.length} · open conflicts: ${d.conflicts.length}</div>
    ${d.unbacked_in_last_answer.length
      ? d.unbacked_in_last_answer.map(c => `<div class="claim unv">
          <div class="t">${pill(c.status)} ${esc(c.text)}</div>
          <div class="m">${esc(c.receipt_note)}</div></div>`).join('')
      : '<div class="muted" style="margin-top:8px">every claim in the last answer carries a receipt</div>'}`;
}
</script>
</body></html>
"""


if __name__ == "__main__":
    import uvicorn

    st = get_state()
    print(f"mode={st['mode']} model={st['model']} db={DB}")
    print("http://127.0.0.1:8077")
    uvicorn.run(app, host="127.0.0.1", port=8077)
