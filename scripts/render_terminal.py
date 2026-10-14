"""Run CLI commands and render their real (ANSI-coloured) output as terminal-window HTML pages.

Used to produce the demo screenshots in docs/demo/. Usage:

    PYTHONPATH=src python scripts/render_terminal.py docs/demo
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
from pathlib import Path

COMMANDS = {
    "terminal-scenarios": ["run"],
    "terminal-control-guarded": ["run", "--approver", "gullible", "--scenario", "misleading_message",
                                 "--scenario", "forgery_attempt", "--out", "runs/gullible-guarded-demo"],
    "terminal-control-unguarded": ["run", "--approver", "gullible", "--no-guard", "--scenario", "misleading_message",
                                   "--out", "runs/gullible-unguarded-demo"],
}
COLORS = {"31": "#ff6b6b", "32": "#5fd38d", "33": "#f2c94c"}
SGR = re.compile(r"\x1b\[([\d;]*)m")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#e9e9ee;padding:28px;font-family:-apple-system,sans-serif}}
.win{{background:#16161c;border-radius:10px;box-shadow:0 18px 50px rgba(0,0,0,.35);overflow:hidden;display:inline-block;min-width:980px}}
.bar{{background:#24242c;padding:9px 12px;display:flex;gap:7px;align-items:center}}
.dot{{width:12px;height:12px;border-radius:50%}}.t{{color:#9a9aa6;font-size:12px;margin-left:10px}}
pre{{margin:0;padding:16px 20px 20px;color:#d8d8e0;font:13px/1.55 ui-monospace,SFMono-Regular,Menlo,monospace}}
.p{{color:#8ea2ff}}</style></head><body><div class="win"><div class="bar">
<span class="dot" style="background:#ff5f57"></span><span class="dot" style="background:#febc2e"></span>
<span class="dot" style="background:#28c840"></span><span class="t">purchase-eval — zsh</span></div>
<pre><span class="p">$</span> {command}
{output}<span class="p">$</span> echo $?
{code}</pre></div></body></html>"""


def ansi_to_html(text: str) -> str:
    out, open_span, pos = [], False, 0
    for m in SGR.finditer(text):
        out.append(html.escape(text[pos:m.start()]))
        pos = m.end()
        if open_span:
            out.append("</span>")
            open_span = False
        codes = [c for c in m.group(1).split(";") if c and c != "0"]
        if codes:
            style = []
            for c in codes:
                if c in COLORS:
                    style.append(f"color:{COLORS[c]}")
                elif c == "1":
                    style.append("font-weight:700")
                elif c == "2":
                    style.append("opacity:.6")
            out.append(f'<span style="{";".join(style)}">')
            open_span = True
    out.append(html.escape(text[pos:]))
    if open_span:
        out.append("</span>")
    return "".join(out)


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "FORCE_COLOR": "1"}
    env.pop("NO_COLOR", None)
    for name, args in COMMANDS.items():
        proc = subprocess.run([sys.executable, "-m", "purchase_eval", *args], env=env, capture_output=True, text=True)
        shown = "purchase-eval " + " ".join(args)
        page = PAGE.format(command=html.escape(shown), output=ansi_to_html(proc.stdout), code=proc.returncode)
        (out / f"{name}.html").write_text(page, encoding="utf-8")
        print(f"{name}: exit {proc.returncode}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "docs/demo")
