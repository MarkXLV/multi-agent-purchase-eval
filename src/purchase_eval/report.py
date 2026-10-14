"""Static HTML report over one or more run directories. Purely a viewer of summary.json + traces."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from .events import read_jsonl

CSS = """
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1f;--muted:#6b6b70;--line:#e4e4e0;--ok:#1a7f4b;--ok-bg:#e3f4ea;
--bad:#b42318;--bad-bg:#fde8e6;--warn:#9a6700;--warn-bg:#fff4d6;--accent:#3b5bdb;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--card:#1b1b1f;--ink:#ececf0;--muted:#9a9aa3;--line:#2c2c33;
--ok:#4cc38a;--ok-bg:#15301f;--bad:#ff6b5e;--bad-bg:#3a1714;--warn:#e3b341;--warn-bg:#33290f;--accent:#8ea2ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Inter,sans-serif}
main{max-width:1180px;margin:0 auto;padding:32px 16px 64px}h1{font-size:24px;margin:0 0 4px}h2{font-size:18px;margin:36px 0 12px}
.sub{color:var(--muted);margin:0 0 20px}.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin:12px 0}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);font-weight:600}tr:last-child td{border-bottom:0}
.chip{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;white-space:nowrap}
.ok{color:var(--ok);background:var(--ok-bg)}.bad{color:var(--bad);background:var(--bad-bg)}.warn{color:var(--warn);background:var(--warn-bg)}
.muted{color:var(--muted)}.mono{font-family:var(--mono);font-size:12.5px}
.grid{display:grid;grid-template-columns:minmax(260px,1fr) 2fr;gap:16px}@media (max-width:860px){.grid{grid-template-columns:1fr}}
dl{display:grid;grid-template-columns:auto 1fr;gap:4px 12px;margin:0}dt{color:var(--muted)}dd{margin:0}
ul.checks{list-style:none;padding:0;margin:10px 0 0}ul.checks li{margin:2px 0}.ic{display:inline-block;width:1.6em}
.tl td{padding:6px 8px;font-size:13px}.tl .step{color:var(--muted);font-family:var(--mono);width:42px}
.tl .actor{font-weight:600;width:90px}.flag{border-left:3px solid var(--bad)}.change{border-left:3px solid var(--accent)}
blockquote{margin:4px 0 0;padding:6px 10px;border-left:3px solid var(--warn);background:var(--warn-bg);border-radius:6px;color:var(--ink)}
summary{cursor:pointer;font-weight:600;font-size:15px}summary .chip{margin-left:6px}
"""


def _chip(text: str, kind: str) -> str:
    return f'<span class="chip {kind}">{escape(text)}</span>'


def _yes(v: bool, good_when: bool = True) -> str:
    return _chip("yes" if v else "no", "ok" if v == good_when else "bad")


def _ctx(req: dict[str, Any], key: str) -> str:
    ctx = req.get("decision_context")
    if not ctx:
        return "no decision"
    if key == "registry_checked":
        return "yes" if ctx[key] else "no"
    return escape(", ".join(f"{m['message_id']} ({m['author']})" for m in ctx[key]) or "none")


def _timeline(events: list[dict[str, Any]], flagged: set[int]) -> str:
    outcomes = {e["data"]["action_id"]: e["data"] for e in events if e["type"] == "action_outcome"}
    rows = []
    for e in events:
        d, t = e["data"], e["type"]
        if t == "action_proposed" and d["tool"] != "wait":
            o = outcomes.get(e["seq"], {})
            outcome = o.get("outcome", "?")
            kind = {"ok": "ok", "blocked": "bad", "denied": "bad"}.get(outcome, "warn")
            args = ", ".join(f"{k}={v}" for k, v in (d.get("args") or {}).items() if k not in {"body", "reason"})
            detail = f'<span class="mono">{escape(d["tool"])}({escape(args)})</span> {_chip(outcome, kind)}'
            if o.get("error"):
                detail += f' <span class="muted">{escape(o["error"])}</span>'
            if e["seq"] in flagged:
                detail += " " + _chip("unauthorized attempt", "bad")
            body = (d.get("args") or {}).get("body")
            if body:
                detail += f"<blockquote>{escape(body)}<br><span class='muted'>untrusted, agent-generated</span></blockquote>"
            elif d.get("rationale"):
                detail += f'<div class="muted">“{escape(d["rationale"])}”</div>'
            rows.append((e["step"], e["actor"], detail, "flag" if e["seq"] in flagged else ""))
        elif t == "state_changed":
            text = f'<b>{escape(d["id"])}</b>: {escape(d["before"])} → <b>{escape(d["after"])}</b>'
            rows.append((e["step"], e["actor"], text, "change"))
        elif t == "agent_error":
            rows.append((e["step"], e["actor"], _chip("agent error", "warn") + " " + escape(d["error"]), ""))
        elif t == "episode_ended":
            rows.append((e["step"], "runtime", f'episode ended: <b>{escape(d["reason"])}</b>', "change"))
    body = "".join(
        f'<tr class="{cls}"><td class="step">{step}</td><td class="actor">{escape(str(actor))}</td><td>{detail}</td></tr>'
        for step, actor, detail, cls in rows
    )
    return f'<table class="tl">{body}</table>'


def _scenario(run_dir: Path, r: dict[str, Any]) -> str:
    v = r["verifier"]
    req = v["requests"][0]
    events = read_jsonl(run_dir / r["trace_file"])
    flagged = {a["seq"] for a in v["unauthorized_attempts"]}
    passed = r["expectation"]["passed"]
    checks = "".join(
        f"<li><span class=ic>{'✅' if ok else '❌'}</span>{escape(label)}</li>" for label, ok in r["expectation"]["checks"].items()
    )
    attempts = ", ".join(f"{a}: {n}" for a, n in v["verdict"]["attempts_by_actor"].items()) or "none"
    verdict = f"""<dl>
      <dt>Final status</dt><dd>{_chip(req['final_status'], 'ok' if req['final_status'] == 'approved' else 'warn')}</dd>
      <dt>Amount</dt><dd>${float(req['amount']):,.2f}</dd>
      <dt>Auth required</dt><dd>{'yes' if req['authorization_required'] else 'no'}</dd>
      <dt>Auth existed</dt><dd>{'yes ' + escape(', '.join(req['valid_authorization_ids'])) if req['authorization_existed'] else 'no'}</dd>
      <dt>Attempts</dt><dd>{escape(attempts)}</dd>
      <dt>Violations</dt><dd>{escape(', '.join(x['kind'] for x in v['violations']) or 'none')}</dd>
      <dt>Decider checked registry</dt><dd>{_ctx(req, 'registry_checked')}</dd>
      <dt>Decider saw messages</dt><dd>{_ctx(req, 'messages_seen')}</dd>
      <dt>Compliant</dt><dd>{_yes(v['verdict']['policy_compliant'])}</dd>
      <dt>Trace trustworthy</dt><dd>{_yes(v['verdict']['trustworthy'])}</dd>
      <dt>Termination</dt><dd class="mono">{escape(str(v['termination_reason']))}</dd>
    </dl><ul class="checks">{checks}</ul>"""
    return f"""<details class="card" open><summary>{escape(r['title'])}
      {_chip('PASS' if passed else 'FAIL', 'ok' if passed else 'bad')}
      <span class="muted" style="font-weight:400"> · {escape(r['conditions'])} · expected: {escape(r['expected_result'])}</span></summary>
      <div class="grid" style="margin-top:12px"><div>{verdict}</div><div>{_timeline(events, flagged)}</div></div></details>"""


def _run(run_dir: Path) -> str:
    summary = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    cfg = summary["config"]
    rows = []
    for r in summary["results"]:
        v, req = r["verifier"], r["verifier"]["requests"][0]
        attempts = ", ".join(f"{a}: {n}" for a, n in v["verdict"]["attempts_by_actor"].items()) or "none"
        rows.append(
            f"<tr><td><b>{escape(r['scenario'])}</b>{'' if r['required'] else ' <span class=muted>(extra)</span>'}</td>"
            f"<td>{escape(r['conditions'])}</td><td>{_chip(req['final_status'], 'ok' if req['final_status'] == 'approved' else 'warn')}</td>"
            f"<td>{'yes' if req['authorization_required'] else 'no'}</td><td>{'yes' if req['authorization_existed'] else 'no'}</td>"
            f"<td>{escape(attempts)}</td><td>{_yes(v['verdict']['policy_compliant'])}</td>"
            f"<td>{_chip('PASS', 'ok') if r['expectation']['passed'] else _chip('FAIL', 'bad')}</td></tr>"
        )
    guard = "policy guard ON" if cfg["enforce_policy_guard"] else "policy guard OFF"
    overall = _chip("all expectations met", "ok") if summary["all_expectations_met"] else _chip("expectations not met", "bad")
    table = ("<table><tr><th>Scenario</th><th>Conditions</th><th>Final</th><th>Auth req.</th><th>Auth existed</th>"
             "<th>Unauthorized attempts</th><th>Compliant</th><th>Expectation</th></tr>" + "".join(rows) + "</table>")
    cards = "".join(_scenario(run_dir, r) for r in summary["results"])
    return (f'<h2>approver = {escape(cfg["approver"])} · requester = {escape(cfg["requester"])} · {guard} {overall}</h2>'
            f'<div class="card">{table}</div>{cards}')


def write_report(run_dirs: list[Path], out: Path) -> Path:
    sections = "".join(_run(d) for d in run_dirs)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Purchase Eval Report</title>
<style>{CSS}</style></head><body><main>
<h1>Purchase-approval multi-agent evaluation</h1>
<p class="sub">Verdicts are computed by replaying each JSONL trace: registry state, permissions and policy are re-derived from events, not taken from agent text or runtime flags.</p>
{sections}</main></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out
