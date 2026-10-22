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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dojo_models import factory, make_model  # noqa: E402

import json as _json, os, threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class _FakeSearch(BaseHTTPRequestHandler):  # a stand-in search provider so the Search settings can be tried without a real key
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        body = _json.dumps({"results": [{"title": "Example result", "url": "https://example.org/a", "content": "A short snippet."}]}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _FakePush(BaseHTTPRequestHandler):  # a stand-in push service (the real ones cannot be reached from tests)
    def log_message(self, *a):
        pass

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.send_response(201)
        self.send_header("Content-Length", "0")
        self.end_headers()


_push = ThreadingHTTPServer(("127.0.0.1", 8806), _FakePush)
threading.Thread(target=_push.serve_forever, daemon=True).start()
os.environ["KINTSUGI_PUSH_ALLOW_LOCAL"] = "1"
_fake = ThreadingHTTPServer(("127.0.0.1", 0), _FakeSearch)
threading.Thread(target=_fake.serve_forever, daemon=True).start()
os.environ["KINTSUGI_SEARCH_BASE_URL"] = f"http://127.0.0.1:{_fake.server_port}"

ws = Workspace(sys.argv[1], model_factory=lambda n: MockModel(reply), sync=False, encrypt_keychain=False)
seed(ws)
# studies find a real improvement: the default model is weak, the candidate 'strong' is good
ws.study_model_factory = factory({None: make_model(solves={'two_agents', 'write_file'}), 'strong': make_model()})
ws.improver.update_settings({'candidates': ['strong'], 'repeats': 1})
serve(ws, "127.0.0.1", int(sys.argv[2]))
