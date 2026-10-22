"""A workspace server with a scripted model, for the browser tests in this folder.

    KINTSUGI_TOKEN=tok123 python tests/ui/serve_mock.py /tmp/ws 8804
"""
import sys, re
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.cli import seed
from kintsugi.workspace.server import serve

def reply(messages):
    last = messages[-1]["content"]
    if "general lesson" in last:
        return "When a file may not exist, list the folder before reading it."
    if "Tool results" in last:
        return "Finished. The answer is **391**."
    n = re.search(r"Respond to message (\d+)", last)
    line = re.search(r'<message id="' + (n.group(1) if n else "0") + r'" from="[^"]*">\n(.*?)\n</message>', last, re.S)
    trigger = (line.group(1) if line else "").lower()
    if "your request to run" in trigger:
        return "Done! `17 * 23 = 391`.\n\n```python\nprint(17 * 23)\n```"
    if "python" in trigger:
        return '```tool\n{"tool": "run_python", "args": {"code": "print(17 * 23)"}}\n```'
    if "missing" in trigger:
        return '```tool\n{"tool": "read_file", "args": {"path": "missing.txt"}}\n```'
    return "Hello! Here is a **list**:\n\n- one\n- two\n\n```python\nprint('hi')\n```\n\n[a link](https://example.com) <script>alert(1)</script>"

ws = Workspace(sys.argv[1], model_factory=lambda n: MockModel(reply), sync=False, encrypt_keychain=False)
seed(ws)
serve(ws, "127.0.0.1", int(sys.argv[2]))
