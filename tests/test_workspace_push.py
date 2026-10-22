import base64
import http.client
import json
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

try:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
except ImportError:
    raise unittest.SkipTest("push notifications need the optional 'cryptography' package (pip install 'kintsugi[push]')")

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace, push
from kintsugi.workspace.core import WorkspaceError
from kintsugi.workspace.server import make_server


def unb64u(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class FakePushService(BaseHTTPRequestHandler):
    """Records what a push service would receive, and answers the way the real ones do."""

    seen: list = []
    status = 201

    def log_message(self, *args):
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        FakePushService.seen.append({"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length)})
        self.send_response(FakePushService.status)
        self.send_header("Content-Length", "0")
        self.end_headers()


class Base(unittest.TestCase):
    def setUp(self):
        FakePushService.seen, FakePushService.status = [], 201
        self.service = ThreadingHTTPServer(("127.0.0.1", 0), FakePushService)
        threading.Thread(target=self.service.serve_forever, daemon=True).start()
        self.endpoint = f"http://127.0.0.1:{self.service.server_port}/push/device-1"
        patcher = mock.patch.dict(os.environ, {"KINTSUGI_PUSH_ALLOW_LOCAL": "1"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["hello"]), encrypt_keychain=False)
        self.ws.create_agent("alice")
        self.ws.create_room("r", ["alice", "you"])

    def tearDown(self):
        self.service.shutdown()
        self.service.server_close()
        self.ws.close()
        self.tmp.cleanup()

    def wait_for(self, count, seconds=5):
        end = time.time() + seconds
        while len(FakePushService.seen) < count and time.time() < end:
            time.sleep(0.02)


class TestKeysAndSigning(Base):
    def test_the_signature_verifies_with_the_published_public_key(self):
        endpoint = "https://fcm.googleapis.com/fcm/send/abc123"
        token = self.ws.pusher.jwt(endpoint, now=1_000_000)
        header, claims, signature = token.split(".")
        self.assertEqual(json.loads(unb64u(header)), {"typ": "JWT", "alg": "ES256"})
        body = json.loads(unb64u(claims))
        self.assertEqual(body["aud"], "https://fcm.googleapis.com")
        self.assertEqual(body["exp"], 1_000_000 + 12 * 3600)  # well under the 24 hours push services allow
        self.assertTrue(body["sub"].startswith("https://"))
        raw = unb64u(signature)
        self.assertEqual(len(raw), 64)
        public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64u(self.ws.pusher.public_key()))
        public.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                      f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))  # raises if the signature is wrong
        with self.assertRaises(Exception):
            public.verify(encode_dss_signature(1, 2), f"{header}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))

    def test_the_public_key_is_a_valid_uncompressed_point_and_survives_a_restart(self):
        key = self.ws.pusher.public_key()
        self.assertEqual((len(unb64u(key)), unb64u(key)[0]), (65, 4))
        self.ws.close()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["x"]), encrypt_keychain=False)
        self.assertEqual(self.ws.pusher.public_key(), key)  # phones stay subscribed across restarts

    def test_the_private_key_never_leaves_the_keychain(self):
        self.ws.pusher.public_key()
        self.ws.pusher.subscribe(self.endpoint)
        self.ws.pusher.notify("test", force=True)
        pem = self.ws.keychain.env_for("_workspace", [push.KEY_NAME])[push.KEY_NAME]
        self.assertIn("PRIVATE KEY", pem)
        everything = repr(self.ws.db.query("SELECT * FROM audit")) + repr(self.ws.db.query("SELECT * FROM settings")) + repr(self.ws.db.query("SELECT * FROM push_subs"))
        self.assertNotIn("PRIVATE KEY", everything)
        self.assertNotIn(pem.splitlines()[1], everything)


class TestSubscriptions(Base):
    def test_only_real_push_services_are_accepted(self):
        good = ["https://fcm.googleapis.com/fcm/send/abc", "https://updates.push.services.mozilla.com/wpush/v2/abc", "https://web.push.apple.com/abc",
                "https://wns2-par02p.notify.windows.com/w/?token=abc"]
        for url in good:
            self.assertTrue(push.endpoint_ok(url), url)
        with mock.patch.dict(os.environ, {"KINTSUGI_PUSH_ALLOW_LOCAL": "0"}):
            for url in ["http://fcm.googleapis.com/x", "https://evil.example/push", "https://fcm.googleapis.com.evil.example/x", "https://user:pw@fcm.googleapis.com/x",
                        "https://fcm.googleapis.com:8443/x", "http://127.0.0.1:9/x", "https://169.254.169.254/latest", "file:///etc/passwd", "https://localhost/x",
                        "https://" + "a" * 700 + ".push.apple.com/x", "javascript:alert(1)", ""]:
                self.assertFalse(push.endpoint_ok(url), url)

    def test_subscribe_validates_dedupes_caps_and_unsubscribes(self):
        with mock.patch.dict(os.environ, {"KINTSUGI_PUSH_ALLOW_LOCAL": "0"}):
            with self.assertRaises(WorkspaceError):
                self.ws.pusher.subscribe("https://evil.example/push")
        self.ws.pusher.subscribe(self.endpoint)
        self.ws.pusher.subscribe(self.endpoint)
        self.assertEqual(self.ws.pusher.count(), 1)
        self.ws.pusher.unsubscribe(self.endpoint)
        self.assertEqual(self.ws.pusher.count(), 0)
        for i in range(push.MAX_SUBSCRIPTIONS):
            self.ws.pusher.subscribe(f"http://127.0.0.1:{self.service.server_port}/d{i}")
        with self.assertRaises(WorkspaceError):
            self.ws.pusher.subscribe(f"http://127.0.0.1:{self.service.server_port}/one-too-many")
        self.ws.pusher.subscribe(f"http://127.0.0.1:{self.service.server_port}/d0")  # an existing one is fine

    def test_without_the_cryptography_package_push_is_off_and_says_so(self):
        with mock.patch.object(push, "ec", None):
            self.assertFalse(push.available())
            with self.assertRaises(WorkspaceError) as caught:
                self.ws.pusher.subscribe(self.endpoint)
            self.assertIn("cryptography", str(caught.exception))
            self.assertEqual(self.ws.pusher.notify("x", force=True), 0)
        self.ws.post("r", "alice", "still works without push")  # messaging is unaffected


class TestSending(Base):
    def test_a_push_has_a_vapid_header_a_ttl_and_no_text_at_all(self):
        self.ws.pusher.subscribe(self.endpoint)
        self.assertEqual(self.ws.pusher.notify("message", force=True), 1)
        (request,) = FakePushService.seen
        self.assertEqual(request["body"], b"")  # nothing about the message leaves the server
        headers = {k.lower(): v for k, v in request["headers"].items()}
        self.assertRegex(headers["authorization"], r"^vapid t=[\w-]+\.[\w-]+\.[\w-]+, k=[\w-]{87}$")
        self.assertEqual(headers["ttl"], "3600")
        self.assertIn(self.ws.pusher.public_key(), headers["authorization"])

    def test_you_are_only_pinged_when_away_and_at_most_once_a_minute(self):
        self.ws.pusher.subscribe(self.endpoint)
        self.ws.touch()  # the app is open right now
        self.ws.post("r", "alice", "you are here, no ping needed")
        time.sleep(0.3)
        self.assertEqual(FakePushService.seen, [])
        self.ws.activity["you"] = time.time() - 120  # two minutes ago: away
        self.ws.post("r", "alice", "now you are away")
        self.wait_for(1)
        self.assertEqual(len(FakePushService.seen), 1)
        self.ws.post("r", "alice", "and another right away")
        self.ws.post("r", "alice", "and one more")
        time.sleep(0.4)
        self.assertEqual(len(FakePushService.seen), 1)  # throttled: no notification storm

    def test_approvals_and_only_agent_messages_trigger_a_ping(self):
        self.ws.pusher.subscribe(self.endpoint)
        self.ws.activity["you"] = 0
        self.ws.post("r", "you", "my own message")
        self.ws.post_system("r", "a system notice")
        time.sleep(0.3)
        self.assertEqual(FakePushService.seen, [])
        self.ws.request_approval("alice", "r", "run_python", {"code": "print(1)"})
        self.wait_for(1)
        self.assertEqual(len(FakePushService.seen), 1)

    def test_scheduled_agent_replies_ping_a_phone_that_is_away(self):
        self.ws.pusher.subscribe(self.endpoint)
        self.ws.activity["you"] = 0
        job = self.ws.add_job("alice", "r", "0 8 * * *", "say good morning")
        self.ws.run_job_now(job)
        self.wait_for(1)
        self.assertEqual(len(FakePushService.seen), 1)

    def test_a_device_the_push_service_has_forgotten_is_removed_and_failures_are_harmless(self):
        self.ws.pusher.subscribe(self.endpoint)
        FakePushService.status = 410
        self.assertEqual(self.ws.pusher.notify("x", force=True), 0)
        self.assertEqual(self.ws.pusher.count(), 0)
        self.ws.pusher.subscribe(self.endpoint)
        FakePushService.status = 500
        self.assertEqual(self.ws.pusher.notify("x", force=True), 0)
        self.assertEqual(self.ws.pusher.count(), 1)  # a temporary failure keeps the device
        with mock.patch.dict(os.environ, {"KINTSUGI_PUSH_ALLOW_LOCAL": "1"}):
            self.ws.pusher.subscribe("http://127.0.0.1:1/unreachable")
            self.assertEqual(self.ws.pusher.notify("x", force=True), 0)  # an unreachable service does not raise

    def test_nothing_is_sent_with_no_devices_subscribed(self):
        self.ws.activity["you"] = 0
        self.ws.post("r", "alice", "hello")
        time.sleep(0.2)
        self.assertEqual(FakePushService.seen, [])


class TestPushApi(Base):
    def setUp(self):
        super().setUp()
        self.ws.close()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["hello"]), sync=False, encrypt_keychain=False)
        self.server = make_server(self.ws, port=0, token="secret-token")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def call(self, method, path, body=None, token="secret-token", headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": token, **(headers or {})})
        resp = conn.getresponse()
        return resp.status, json.loads(resp.read() or b"{}")

    def test_the_browser_gets_the_public_key_and_can_subscribe_test_and_unsubscribe(self):
        status, info = self.call("GET", "/api/push")
        self.assertEqual((status, info["available"], info["devices"], len(info["public_key"])), (200, True, 0, 87))
        self.assertNotIn("PRIVATE", json.dumps(info))
        self.assertEqual(self.call("POST", "/api/push/subscribe", {"endpoint": self.endpoint})[1], {"devices": 1})
        self.assertEqual(self.call("POST", "/api/push/test", {})[1], {"delivered": 1})
        self.assertEqual(len(FakePushService.seen), 1)
        self.assertEqual(self.call("POST", "/api/push/unsubscribe", {"endpoint": self.endpoint})[1], {"devices": 0})

    def test_it_needs_the_token_and_refuses_unknown_services(self):
        self.assertEqual(self.call("GET", "/api/push", token="wrong")[0], 401)
        self.assertEqual(self.call("POST", "/api/push/subscribe", {"endpoint": self.endpoint}, token="wrong")[0], 401)
        with mock.patch.dict(os.environ, {"KINTSUGI_PUSH_ALLOW_LOCAL": "0"}):
            self.assertEqual(self.call("POST", "/api/push/subscribe", {"endpoint": "https://evil.example/x"})[0], 400)
        self.assertEqual(self.call("POST", "/api/push/subscribe", {})[0], 400)

    def test_a_hidden_tab_does_not_count_as_being_here(self):
        self.ws.activity["you"] = 0
        self.call("GET", "/api/state", headers={"X-Visible": "0"})
        self.assertEqual(self.ws.last_active, 0)
        self.call("GET", "/api/state", headers={"X-Visible": "1"})
        self.assertGreater(self.ws.last_active, time.time() - 5)


if __name__ == "__main__":
    unittest.main()
