import http.client
import json
import tempfile
import threading
import time
import unittest
from unittest import mock

from kintsugi.model import MockModel
from kintsugi.workspace import Workspace
from kintsugi.workspace.server import make_server
from kintsugi.workspace.team import Identity, required_role

OWNER = "owner-token-0123456789-0123456789"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ws = Workspace(self.tmp.name, model_factory=lambda n: MockModel(["ok"]), encrypt_keychain=False, sync=False)
        self.ws.create_agent("alice", persona="p")
        self.ws.create_room("team", ["alice", "you"])
        self.ws.create_room("secret-room", ["alice", "you"])
        self.api = make_server(self.ws, port=0, token=OWNER)
        threading.Thread(target=self.api.serve_forever, daemon=True).start()
        self.tokens = {"owner": OWNER}

    def tearDown(self):
        self.api.shutdown()
        self.api.server_close()
        self.ws.close()
        self.tmp.cleanup()

    def call(self, who, method, path, body=None):
        token = self.tokens.get(who, who)
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=15)
        conn.request(method, path, json.dumps(body) if body is not None else None, {"X-Token": token or ""})
        resp = conn.getresponse()
        raw = resp.read()
        try:
            return resp.status, json.loads(raw)
        except json.JSONDecodeError:
            return resp.status, raw.decode()

    def invite_and_join(self, name, role="member", by="owner", rooms=None):
        status, invite = self.call(by, "POST", "/api/team/invite", {"role": role, **({"rooms": rooms} if rooms is not None else {})})
        self.assertEqual(status, 200, invite)
        status, joined = self.call(None, "POST", "/api/join", {"code": invite["code"], "name": name})
        self.assertEqual(status, 200, joined)
        self.tokens[name] = joined["token"]
        return joined


class TestInvitesAndLogin(Base):
    def test_invite_join_login_and_the_token_is_stored_only_as_a_hash(self):
        joined = self.invite_and_join("sam")
        self.assertEqual((joined["name"], joined["role"]), ("sam", "member"))
        me = self.call("sam", "GET", "/api/me")[1]
        self.assertEqual(me, {"name": "sam", "role": "member"})
        stored = self.ws.db.query("SELECT * FROM users")
        self.assertNotIn(joined["token"], json.dumps(stored))
        self.assertNotIn(joined["token"], json.dumps(self.ws.audit_log(200)))
        self.assertIn("sam", self.ws.members("team"))  # the invite put them in the default shared room
        self.assertNotIn("sam", self.ws.members("secret-room"))

    def test_an_invite_works_once(self):
        _, invite = self.call("owner", "POST", "/api/team/invite", {})
        self.assertEqual(self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "sam"})[0], 200)
        status, err = self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "kim"})
        self.assertEqual(status, 400)
        self.assertIn("not valid any more", err["error"])

    def test_invites_expire_and_can_be_revoked(self):
        _, invite = self.call("owner", "POST", "/api/team/invite", {"days": 0.01})
        self.ws.db.execute("UPDATE invites SET expires = ?", (time.time() - 5,))
        self.assertEqual(self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "sam"})[0], 400)
        _, second = self.call("owner", "POST", "/api/team/invite", {})
        self.assertEqual(self.call("owner", "POST", "/api/team/revoke-invite", {"id": second["id"]})[0], 200)
        self.assertEqual(self.call(None, "POST", "/api/join", {"code": second["code"], "name": "sam"})[0], 400)

    def test_names_are_validated_and_reserved(self):
        for bad in ("you", "alice", "System", "x", "has space", "all", "cron-1", "dm-x", "a" * 30):
            _, invite = self.call("owner", "POST", "/api/team/invite", {})
            status, _ = self.call(None, "POST", "/api/join", {"code": invite["code"], "name": bad})
            self.assertEqual(status, 400, bad)
        self.invite_and_join("sam")
        _, invite = self.call("owner", "POST", "/api/team/invite", {})
        self.assertEqual(self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "sam"})[0], 400)  # taken
        with self.assertRaises(Exception):
            self.ws.create_agent("sam")  # an agent cannot take a person's name

    def test_wrong_and_missing_tokens_are_refused_and_guessing_is_throttled(self):
        for token in ("", "nope", "kt_" + "x" * 40):
            self.assertEqual(self.call(token or None, "GET", "/api/me")[0], 401)
        codes = [self.call(None, "POST", "/api/join", {"code": "ki_wrong", "name": "sam"})[0] for _ in range(14)]
        self.assertEqual(codes[0], 400)
        self.assertEqual(codes[-1], 403)  # too many wrong tries from one client (wrong tokens and wrong invite codes share one throttle)

    def test_removing_a_person_locks_their_token_out_at_once(self):
        self.invite_and_join("sam")
        self.assertEqual(self.call("sam", "GET", "/api/me")[0], 200)
        self.assertEqual(self.call("owner", "POST", "/api/team/remove", {"name": "sam"})[0], 200)
        self.assertEqual(self.call("sam", "GET", "/api/me")[0], 401)
        self.assertNotIn("sam", self.ws.members("team"))

    def test_rotating_your_own_token_replaces_it(self):
        self.invite_and_join("sam")
        old = self.tokens["sam"]
        new = self.call("sam", "POST", "/api/me/token", {})[1]["token"]
        self.assertNotEqual(old, new)
        self.assertEqual(self.call(old, "GET", "/api/me")[0], 401)
        self.assertEqual(self.call(new, "GET", "/api/me")[0], 200)
        self.assertEqual(self.call("owner", "POST", "/api/me/token", {})[0], 400)


class TestRoles(Base):
    def setUp(self):
        super().setUp()
        self.invite_and_join("sam")
        self.invite_and_join("ada", "admin")

    # (method, path, body) for a spread of endpoints and who may call them
    OWNER_ONLY = [("GET", "/api/providers"), ("POST", "/api/providers/save"), ("GET", "/api/backup"), ("POST", "/api/backup/run"),
                  ("GET", "/api/plugins"), ("POST", "/api/plugins/install"), ("POST", "/api/internet"), ("GET", "/api/internet"),
                  ("POST", "/api/parallel"), ("POST", "/api/search/settings"), ("GET", "/api/search"), ("GET", "/api/export"),
                  ("POST", "/api/purge"), ("POST", "/api/team/role"), ("POST", "/api/team/policy"), ("GET", "/api/brand-new-endpoint")]
    ADMIN_UP = [("POST", "/api/agents"), ("POST", "/api/persona"), ("POST", "/api/secret"), ("POST", "/api/tier"), ("POST", "/api/rooms"),
                ("GET", "/api/audit"), ("GET", "/api/files"), ("GET", "/api/team"), ("POST", "/api/team/invite"), ("POST", "/api/agent/internet"),
                ("POST", "/api/agent/delete"), ("POST", "/api/improve/run")]

    def test_deny_by_default_and_the_owner_only_list(self):
        for method, path in self.OWNER_ONLY:
            for who in ("sam", "ada"):
                self.assertEqual(self.call(who, method, path, {})[0], 403, f"{who} {method} {path}")
        self.assertEqual(required_role("/api/something/new"), "owner")

    def test_admin_endpoints_are_closed_to_members(self):
        for method, path in self.ADMIN_UP:
            self.assertEqual(self.call("sam", method, path, {})[0], 403, f"member {method} {path}")
            self.assertNotEqual(self.call("ada", method, path, {"name": "x", "agent": "alice", "role": "member"})[0], 403, f"admin {method} {path}")

    def test_an_admin_can_invite_members_but_not_admins(self):
        self.assertEqual(self.call("ada", "POST", "/api/team/invite", {"role": "member"})[0], 200)
        status, err = self.call("ada", "POST", "/api/team/invite", {"role": "admin"})
        self.assertEqual(status, 400)
        self.assertIn("only the owner", err["error"])
        self.assertEqual(self.call("sam", "POST", "/api/team/invite", {})[0], 403)

    def test_removal_follows_rank(self):
        self.assertEqual(self.call("ada", "POST", "/api/team/remove", {"name": "sam"})[0], 200)
        self.invite_and_join("lee", "admin")
        self.assertEqual(self.call("ada", "POST", "/api/team/remove", {"name": "lee"})[0], 400)  # an admin cannot remove an admin
        self.assertEqual(self.call("owner", "POST", "/api/team/remove", {"name": "lee"})[0], 200)

    def test_only_the_owner_changes_roles(self):
        self.assertEqual(self.call("owner", "POST", "/api/team/role", {"name": "sam", "role": "admin"})[0], 200)
        self.assertEqual(self.call("sam", "GET", "/api/team")[0], 200)  # now an admin
        self.assertEqual(self.call("owner", "POST", "/api/team/role", {"name": "sam", "role": "owner"})[0], 400)

    def test_a_demoted_admin_loses_access_immediately(self):
        self.assertEqual(self.call("ada", "GET", "/api/audit")[0], 200)
        self.call("owner", "POST", "/api/team/role", {"name": "ada", "role": "member"})
        self.assertEqual(self.call("ada", "GET", "/api/audit")[0], 403)

    def test_members_cannot_see_secrets_or_settings_in_state(self):
        self.ws.keychain.set("alice", "API_TOKEN", "supersecretvalue123")
        member = self.call("sam", "GET", "/api/state")[1]
        self.assertEqual(member["agents"][0]["secrets"], [])
        self.assertEqual(member["providers"], [])
        self.assertEqual(member["people"], [])
        admin = self.call("ada", "GET", "/api/state")[1]
        self.assertEqual(admin["agents"][0]["secrets"], ["API_TOKEN"])
        self.assertEqual(sorted(admin["people"]), ["ada", "sam"])
        for who in ("sam", "ada", "owner"):
            self.assertNotIn("supersecretvalue123", json.dumps(self.call(who, "GET", "/api/state")[1]))


class TestRoomsAndPrivacy(Base):
    def setUp(self):
        super().setUp()
        self.invite_and_join("sam")
        self.invite_and_join("kim")

    def test_members_only_see_and_use_their_rooms(self):
        state = self.call("sam", "GET", "/api/state")[1]
        self.assertEqual([r["name"] for r in state["rooms"]], ["team"])
        self.assertEqual(self.call("sam", "GET", "/api/messages?room=secret-room&after=0")[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/say", {"room": "secret-room", "text": "hi"})[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/say", {"room": "team", "text": "hi"})[0], 200)

    def test_a_person_cannot_pretend_to_be_someone_else(self):
        self.call("sam", "POST", "/api/say", {"room": "team", "text": "hello", "as": "kim"})
        msgs = [m for m in self.ws.history("team", limit=20) if m["text"] == "hello"]
        self.assertEqual([m["sender"] for m in msgs], ["sam"])
        status, _ = self.call("sam", "POST", "/api/say", {"room": "team", "text": "x", "as": "alice"})
        self.assertEqual(status, 200)
        self.assertNotIn("alice", [m["sender"] for m in self.ws.history("team", limit=20) if m["text"] == "x"])

    def test_direct_chats_are_private_per_person(self):
        room_sam = self.call("sam", "POST", "/api/dm", {"a": "kim", "b": "alice"})[1]["room"]  # the 'a' is ignored: it is always the caller
        self.assertEqual(room_sam, "dm-alice-sam")
        self.call("sam", "POST", "/api/say", {"room": room_sam, "text": "my private note"})
        self.assertEqual(self.call("kim", "GET", f"/api/messages?room={room_sam}&after=0")[0], 403)
        self.assertNotIn(room_sam, [r["name"] for r in self.call("kim", "GET", "/api/state")[1]["rooms"]])
        self.assertIn(room_sam, [r["name"] for r in self.call("owner", "GET", "/api/state")[1]["rooms"]])  # the owner can see everything (their server)
        self.assertEqual(self.call("sam", "POST", "/api/dm", {"b": "nobody"})[0], 400)

    def test_a_dm_between_two_people_works_and_agents_stay_out_of_it(self):
        room = self.call("sam", "POST", "/api/dm", {"b": "kim"})[1]["room"]
        self.call("sam", "POST", "/api/say", {"room": room, "text": "@alice hello"})
        self.ws.wait_idle(5)
        self.assertEqual([m["sender"] for m in self.ws.history(room, limit=10)], ["sam"])  # alice is not a member, so she is not woken
        self.assertEqual(self.call("kim", "GET", f"/api/messages?room={room}&after=0")[0], 200)

    def test_admins_manage_who_is_in_a_room(self):
        self.invite_and_join("ada", "admin")
        self.assertEqual(self.call("ada", "POST", "/api/room/members", {"room": "secret-room", "add": ["sam"]})[0], 200)
        self.assertEqual(self.call("sam", "GET", "/api/messages?room=secret-room&after=0")[0], 200)
        self.assertEqual(self.call("ada", "POST", "/api/room/members", {"room": "secret-room", "remove": ["sam"]})[0], 200)
        self.assertEqual(self.call("sam", "GET", "/api/messages?room=secret-room&after=0")[0], 403)
        self.assertEqual(self.call("ada", "POST", "/api/room/members", {"room": "secret-room", "remove": ["you"]})[0], 400)
        self.assertEqual(self.call("ada", "POST", "/api/room/members", {"room": "secret-room", "add": ["ghost"]})[0], 400)
        self.assertEqual(self.call("sam", "POST", "/api/room/members", {"room": "team", "add": ["kim"]})[0], 403)

    def test_per_person_tone(self):
        self.call("sam", "POST", "/api/tone", {"style": "concise"})
        self.call("kim", "POST", "/api/tone", {"style": "fun"})
        self.assertEqual(self.call("sam", "GET", "/api/tone")[1]["style"], "concise")
        self.assertEqual(self.call("kim", "GET", "/api/tone")[1]["style"], "fun")
        self.assertNotEqual(self.call("owner", "GET", "/api/tone")[1]["style"], "concise")

    def test_unread_markers_are_per_person(self):
        self.call("sam", "POST", "/api/say", {"room": "team", "text": "from sam"})
        state = {r["name"]: r for r in self.call("sam", "GET", "/api/state")[1]["rooms"]}
        kim = {r["name"]: r for r in self.call("kim", "GET", "/api/state")[1]["rooms"]}
        self.assertEqual(state["team"]["last_other"], max([m["id"] for m in self.ws.history("team", limit=50) if m["sender"] != "sam"] or [0]))
        self.assertEqual(kim["team"]["last_other"], max(m["id"] for m in self.ws.history("team", limit=50) if m["sender"] != "kim"))


class TestApprovalPolicy(Base):
    def setUp(self):
        super().setUp()
        self.invite_and_join("sam")
        self.invite_and_join("kim")
        self.invite_and_join("ada", "admin")
        self.ws.sync = True  # run agents inline so the approval exists as soon as the message is posted
        # These tests are about who may decide, not about this machine's sandbox: pretend code is isolated. (Without isolation only the
        # owner may approve run_python, which is tested separately; CI machines have no sandbox.)
        patcher = mock.patch("kintsugi.workspace.sandbox.status", return_value={"backend": "namespaces", "isolated": True, "network_blocked": True, "note": "test"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def pending(self, who):
        return self.call(who, "GET", "/api/state")[1]["approvals"]

    def make_request(self, by):
        """sam asks for something risky: an approval is created and remembers who asked."""
        self.ws.model_factory = lambda n: MockModel(['```tool\n{"tool": "run_python", "args": {"code": "print(1)"}}\n```'])
        self.ws._models.clear()
        self.call(by, "POST", "/api/say", {"room": "team", "text": "@alice compute"})
        approvals = self.ws.approvals()
        self.assertEqual(len(approvals), 1, [m["text"] for m in self.ws.history("team", limit=10)])
        return approvals[0]

    def test_default_policy_only_admins_decide_but_the_requester_can_see_it(self):
        approval = self.make_request("sam")
        self.assertEqual(approval["requested_by"], "sam")
        self.assertEqual([a["can_decide"] for a in self.pending("sam")], [False])  # sam sees it, cannot decide
        self.assertEqual(self.pending("kim"), [])  # kim did not ask and cannot decide: nothing to see
        self.assertEqual(self.call("sam", "POST", "/api/approve", {"id": approval["id"], "approve": True})[0], 403)
        self.assertEqual(self.call("kim", "POST", "/api/approve", {"id": approval["id"], "approve": True})[0], 403)
        self.assertEqual(self.ws.approvals()[0]["status"], "pending")
        self.assertTrue(self.pending("ada")[0]["can_decide"])

    def test_requester_policy_lets_you_approve_only_your_own(self):
        self.call("owner", "POST", "/api/team/policy", {"policy": "requester"})
        approval = self.make_request("sam")
        self.assertEqual(self.call("kim", "POST", "/api/approve", {"id": approval["id"], "approve": True})[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/approve", {"id": approval["id"], "approve": False})[0], 200)
        self.assertEqual(self.ws.approvals(None)[0]["decided_by"], "sam")

    def test_everyone_policy_is_limited_to_people_in_that_room(self):
        self.call("owner", "POST", "/api/team/policy", {"policy": "everyone"})
        approval = self.make_request("sam")
        self.ws.remove_member("team", "kim")
        self.assertEqual(self.call("kim", "POST", "/api/approve", {"id": approval["id"], "approve": True})[0], 403)  # not in the room
        self.ws.add_member("team", "kim")
        self.assertEqual(self.call("kim", "POST", "/api/approve", {"id": approval["id"], "approve": False})[0], 200)

    def test_admins_and_the_owner_always_can(self):
        approval = self.make_request("sam")
        self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": approval["id"], "approve": False})[0], 200)
        self.assertEqual(self.ws.approvals(None)[0]["decided_by"], "ada")

    def test_policy_values_are_validated_and_owner_only(self):
        self.assertEqual(self.call("owner", "POST", "/api/team/policy", {"policy": "anyone"})[0], 400)
        self.assertEqual(self.call("ada", "POST", "/api/team/policy", {"policy": "everyone"})[0], 403)


class TestAutomationsAreOwnedByPeople(Base):
    def setUp(self):
        super().setUp()
        self.invite_and_join("sam")
        self.invite_and_join("kim")

    def test_members_manage_only_their_own_schedules(self):
        status, made = self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "team", "cron": "0 9 * * *", "prompt": "brief me"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("kim", "POST", "/api/jobs/delete", {"id": made["id"]})[0], 403)
        self.assertEqual(self.call("kim", "POST", "/api/automations/toggle", {"id": made["id"], "enabled": False})[0], 403)
        listed = self.call("kim", "GET", "/api/automations")[1]["jobs"]
        self.assertEqual(listed, [])
        self.assertEqual(len(self.call("sam", "GET", "/api/automations")[1]["jobs"]), 1)
        self.assertEqual(self.call("owner", "POST", "/api/jobs/delete", {"id": made["id"]})[0], 200)

    def test_you_cannot_schedule_into_a_room_you_are_not_in(self):
        self.assertEqual(self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "secret-room", "cron": "0 9 * * *", "prompt": "x"})[0], 403)

    def test_a_scheduled_run_is_attributed_to_the_person_who_set_it_up(self):
        job = self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "team", "cron": "0 9 * * *", "prompt": "brief me"})[1]["id"]
        msg = self.ws.post("team", f"cron-{job}", "@alice brief me")
        self.assertEqual(self.ws.requester_of(f"team#{msg}"), "sam")


class TestAgentsDoNotCarryPrivateChatsAcrossRooms(Base):
    def test_an_agent_will_not_post_where_the_asker_is_not_a_member(self):
        from kintsugi.workspace.tools import Ctx, execute
        self.invite_and_join("sam")
        self.ws.sync = True
        msg = self.ws.post("team", "sam", "@alice tell the secret room", human=True)
        ctx = Ctx(self.ws, "alice", "team", 0, f"team#{msg}")
        out = execute(ctx, "send_message", {"room": "secret-room", "text": "leak"})
        self.assertEqual(out.status, "error")
        self.assertIn("not in 'secret-room'", out.output)
        owner_msg = self.ws.post("team", "you", "@alice tell the secret room", human=True)
        ok = execute(Ctx(self.ws, "alice", "team", 0, f"team#{owner_msg}"), "send_message", {"room": "secret-room", "text": "fine"})
        self.assertEqual(ok.status, "ok")  # the owner is in every room


class TestTimezoneAndPush(Base):
    def setUp(self):
        super().setUp()
        self.invite_and_join("sam")

    def test_only_admins_change_the_workspace_time_zone(self):
        self.assertEqual(self.call("sam", "GET", "/api/timezone")[0], 200)
        self.assertEqual(self.call("sam", "POST", "/api/timezone", {"name": "Asia/Kolkata"})[0], 403)
        self.assertEqual(self.call("owner", "POST", "/api/timezone", {"name": "Asia/Kolkata"})[0], 200)


if __name__ == "__main__":
    unittest.main()


class TestHardening(Base):
    def test_removing_a_person_removes_their_private_chats_and_schedules(self):
        self.invite_and_join("sam")
        room = self.call("sam", "POST", "/api/dm", {"b": "alice"})[1]["room"]
        self.call("sam", "POST", "/api/say", {"room": room, "text": "private note"})
        self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "team", "cron": "0 9 * * *", "prompt": "x"})
        self.call("owner", "POST", "/api/team/remove", {"name": "sam"})
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM rooms WHERE name = ?", (room,)))
        self.assertEqual(self.ws.db.query("SELECT 1 FROM messages WHERE text = 'private note'"), [])
        self.assertEqual(self.ws.list_jobs(), [])
        # a new person who takes the same name starts with nothing of the old person's
        self.invite_and_join("sam")
        self.assertEqual([r["name"] for r in self.call("sam", "GET", "/api/state")[1]["rooms"]], ["team"])
        self.assertNotIn(room, [r["name"] for r in self.ws.list_rooms()])

    def test_an_admin_cannot_approve_code_that_would_run_with_the_servers_rights(self):
        self.invite_and_join("ada", "admin")
        approval = self.ws.request_approval("alice", "team", "fix_code", {"path": "x"}, None)
        row = self.ws.db.one("SELECT * FROM approvals WHERE id = ?", (approval,))
        self.assertFalse(self.ws.team.can_decide(Identity("ada", "admin"), row))
        self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": approval, "approve": True})[0], 403)
        self.assertTrue(self.ws.team.can_decide(Identity("you", "owner"), row))
        with mock.patch("kintsugi.workspace.sandbox.status", return_value={"isolated": False}):
            py = self.ws.request_approval("alice", "team", "run_python", {"code": "print(1)"}, None)
            self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": py, "approve": True})[0], 403)  # not isolated: owner only
        with mock.patch("kintsugi.workspace.sandbox.status", return_value={"isolated": True}):
            row = self.ws.db.one("SELECT * FROM approvals WHERE id = ?", (py,))
            self.assertTrue(self.ws.team.can_decide(Identity("ada", "admin"), row))  # isolated: an admin may

    def test_only_the_owner_can_make_an_agent_that_never_asks(self):
        self.invite_and_join("ada", "admin")
        self.assertEqual(self.call("ada", "POST", "/api/tier", {"agent": "alice", "tier": "dangerous"})[0], 403)
        self.assertEqual(self.call("ada", "POST", "/api/agents", {"name": "zed", "tier": "dangerous"})[0], 403)
        self.assertEqual(self.call("ada", "POST", "/api/tier", {"agent": "alice", "tier": "strict"})[0], 200)
        self.assertEqual(self.call("owner", "POST", "/api/tier", {"agent": "alice", "tier": "dangerous"})[0], 200)

    def test_one_person_cannot_flood_the_workspace(self):
        self.invite_and_join("sam")
        codes = [self.call("sam", "POST", "/api/say", {"room": "team", "text": f"m{i}"})[0] for i in range(35)]
        self.assertEqual(codes[:30], [200] * 30)
        self.assertEqual(codes[30:], [429] * 5)
        self.assertEqual(self.call("owner", "POST", "/api/say", {"room": "team", "text": "still fine"})[0], 200)  # someone else is unaffected


class TestAccessControlReview(Base):
    def test_admins_do_not_see_private_dm_content_or_approvals(self):
        self.invite_and_join("sam")
        self.invite_and_join("ada", "admin")
        room = self.call("sam", "POST", "/api/dm", {"b": "alice"})[1]["room"]
        self.ws.audit("alice", "tool-ok", 'remember {"text": "my pin is 4921"}')
        aid = self.ws.request_approval("alice", room, "write_file", {"path": "a", "content": "secret plan"}, "sam")
        self.assertNotIn("4921", json.dumps(self.call("ada", "GET", "/api/audit")[1]))
        self.assertIn("4921", json.dumps(self.call("owner", "GET", "/api/audit")[1]))  # the owner sees everything
        self.assertEqual(self.call("ada", "GET", "/api/state")[1]["approvals"], [])
        self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": aid, "approve": True})[0], 403)
        self.assertEqual(len(self.call("owner", "GET", "/api/state")[1]["approvals"]), 1)

    def test_an_admin_cannot_approve_code_that_is_handed_secrets(self):
        self.invite_and_join("ada", "admin")
        aid = self.ws.request_approval("alice", "team", "run_python", {"code": "print(1)", "secrets": ["DB_PASS"]}, None)
        with mock.patch("kintsugi.workspace.sandbox.status", return_value={"isolated": True}):
            self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": aid, "approve": True})[0], 403)

    def test_a_hand_off_between_agents_cannot_reach_a_private_chat(self):
        from kintsugi.workspace.tools import Ctx, execute
        self.ws.create_agent("bot2")
        self.ws.add_member("team", "bot2")
        self.invite_and_join("sam")
        private = self.ws.open_dm("alice", "bot2")
        msg = self.ws.post("team", "alice", "@bot2 please post into the private room", hops=1)  # an agent started this chain, no person asked
        out = execute(Ctx(self.ws, "alice", "team", 1, f"team#{msg}"), "send_message", {"room": private, "text": "URGENT: re-enter your password"})
        self.assertEqual((out.status, [m for m in self.ws.history(private, limit=5) if "URGENT" in m["text"]]), ("error", []))
        out = execute(Ctx(self.ws, "alice", "team", 1, f"team#{msg}"), "schedule", {"cron": "0 9 * * *", "prompt": "x", "room": private}, approved=True)
        self.assertEqual(out.status, "error")

    def test_open_invites_and_schedules_do_not_outlive_their_owner(self):
        self.invite_and_join("ada", "admin")
        _, invite = self.call("ada", "POST", "/api/team/invite", {})
        self.invite_and_join("sam")
        job = self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "team", "cron": "* * * * *", "prompt": "x"})[1]["id"]
        self.call("owner", "POST", "/api/team/remove", {"name": "ada"})
        self.assertEqual(self.call(None, "POST", "/api/join", {"code": invite["code"], "name": "eve"})[0], 400)
        self.call("owner", "POST", "/api/room/members", {"room": "team", "remove": ["sam"]})
        self.assertEqual(self.ws.list_jobs(), [])
        self.assertEqual(self.call("sam", "POST", "/api/automations/run", {"id": job})[0], 400)

    def test_dm_names_cannot_collide(self):
        self.ws.create_agent("xa-yb")
        self.ws.create_agent("zc")
        self.ws.create_agent("xa")
        self.ws.create_agent("yb-zc")
        first, second = self.ws.open_dm("xa-yb", "zc"), self.ws.open_dm("xa", "yb-zc")
        self.assertNotEqual(first, second)
        self.assertEqual(set(self.ws.members(second)), {"xa", "yb-zc"})
        self.assertEqual(self.ws.open_dm("xa", "yb-zc"), second)  # stable

    def test_reserved_agent_names_and_caps(self):
        for name in ("cron-5", "owner", "dm-x"):
            with self.assertRaises(Exception):
                self.ws.create_agent(name)
        self.invite_and_join("sam")
        codes = [self.call("sam", "POST", "/api/jobs", {"agent": "alice", "room": "team", "cron": "0 9 * * *", "prompt": "x"})[0] for _ in range(22)]
        self.assertEqual(codes[:20], [200] * 20)
        self.assertEqual(codes[20:], [400, 400])

    def test_admin_limits(self):
        self.invite_and_join("ada", "admin")
        self.invite_and_join("sam")
        room = self.call("sam", "POST", "/api/dm", {"b": "alice"})[1]["room"]
        self.assertEqual(self.call("ada", "POST", "/api/room/delete", {"name": room})[0], 403)
        self.assertEqual(self.call("ada", "POST", "/api/improve/settings", {"share_lessons": True})[0], 403)
        self.assertEqual(self.call("owner", "POST", "/api/room/delete", {"name": room})[0], 200)

    def test_odd_app_link_signatures_do_not_crash_the_server(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.api.server_port, timeout=10)
        conn.request("GET", "/apps/alice/x/?exp=9999999999&sig=%C3%A9")
        self.assertEqual(conn.getresponse().status, 401)

    def test_a_right_token_is_never_throttled(self):
        for _ in range(15):
            self.call("nope", "GET", "/api/me")
        self.assertEqual(self.call("owner", "GET", "/api/me")[0], 200)
