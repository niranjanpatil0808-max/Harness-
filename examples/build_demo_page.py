"""Build docs/demo.html: a static, read-only page showing a real run of examples/workspace_demo.py.

    python examples/build_demo_page.py

The page is generated from the demo's own output (a scripted mock model, no API key), so it shows what the
workspace does, not what any real model achieves. Open docs/demo.html in a browser, or host it with GitHub Pages.
"""

import html
import re
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent.parent
output = subprocess.run([sys.executable, str(root / "examples" / "workspace_demo.py")], capture_output=True,
                        text=True, check=True, timeout=120).stdout

sections = re.split(r"\n(?=\d\. )", output.strip())
cards = []
for block in sections:
    title, _, body = block.partition("\n")
    lines = []
    for line in body.splitlines():
        match = re.match(r"\s+(\S+): (.*)", line)
        if match and not line.lstrip().startswith("->"):
            who, text = match.groups()
            kind = "system" if who in ("system",) or who.startswith("cron-") else "msg"
            lines.append(f'<div class="{kind}"><b>{html.escape(who)}</b> {html.escape(text)}</div>')
        elif line.strip():
            lines.append(f'<div class="note">{html.escape(line.strip())}</div>')
    cards.append(f"<section><h2>{html.escape(title)}</h2>{''.join(lines)}</section>")

page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Kintsugi workspace: demo run</title>
<style>
:root{{--bg:#faf9f5;--fg:#141413;--mut:#73726c;--card:#f0eee6;--line:#e5e3da;--gold:#c96442}}
@media(prefers-color-scheme:dark){{:root{{--bg:#262624;--fg:#faf9f5;--mut:#a09e95;--card:#141413;--line:#3e3e3a;--gold:#d97757}}}}
body{{margin:0;padding:16px;font:16px/1.5 system-ui,sans-serif;background:var(--bg);color:var(--fg)}}
main{{max-width:720px;margin:0 auto}}h1{{color:var(--fg);font:400 28px ui-serif,Georgia,serif}}h2{{font-size:16px;margin:24px 0 8px}}
.msg,.system{{padding:8px 10px;margin:6px 0;background:var(--card);border:1px solid var(--line);border-radius:8px;white-space:pre-wrap;overflow-wrap:anywhere}}
.system{{color:var(--mut);font-style:italic}}.msg b{{color:var(--gold)}}.note{{color:var(--mut);font-size:14px;margin:4px 0}}
p.small{{color:var(--mut);font-size:14px}}
</style></head><body><main>
<h1>Kintsugi workspace: a demo run</h1>
<p>A team of agents with their own files, secrets, permissions, schedules and web apps. When one of an agent's tool calls fails, it writes a lesson and remembers it.</p>
<p class="small">This page is a recording of <code>python examples/workspace_demo.py</code>. The model is a scripted stand-in, so it shows the workspace's behaviour, not how well any real model performs. Whether lessons improve a real agent is not yet measured.</p>
{''.join(cards)}
<p class="small">Code and docs: the repository's <code>docs/WORKSPACE.md</code>.</p>
</main></body></html>
"""
(root / "docs" / "demo.html").write_text(page)
print(f"wrote {root / 'docs' / 'demo.html'}")
