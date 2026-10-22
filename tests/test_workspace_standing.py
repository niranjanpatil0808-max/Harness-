import unittest
from unittest import mock

from kintsugi.workspace import standing
from kintsugi.workspace.tools import Ctx, execute
from tests.test_workspace_team import Base

ISOLATED = {"backend": "namespaces", "isolated": True, "network_blocked": True, "note": "test"}


class TestStandingApprovals(Base):
    def setUp(self):
        super().setUp()
        patcher = mock.patch("kintsugi.workspace.sandbox.status", return_value=ISOLATED)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ws.set_tier("alice", "strict")

    def ask(self, code="print(1)", **extra):
        out = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "run_python", {"code": code, **extra})
        return out

    def test_always_allow_makes_only_that_exact_call_run_without_asking(self):
        first = self.ask()
        self.assertEqual(first.status, "pending")
        status, body = self.call("owner", "POST", "/api/approve", {"id": first.approval_id, "approve": True, "remember": True})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["remembered"])
        again = self.ask()  # the same call, maybe from a schedule while nobody is around
        self.assertEqual((again.status, again.output.strip()), ("ok", "1"))
        self.assertTrue(any(r["event"] == "auto-allowed" for r in self.ws.audit_log()))
        self.assertEqual(self.ask("print(2)").status, "pending")  # one character different: asks
        self.assertTrue(standing.matches(self.ws, "alice", "run_python", {"code": "print(1)"}))
        self.assertFalse(standing.matches(self.ws, "bob", "run_python", {"code": "print(1)"}))  # another agent: not covered

    def test_only_the_owner_can_make_it_permanent_and_only_for_safe_kinds(self):
        self.invite_and_join("ada", role="admin", rooms=["team"])
        pending = self.ask()
        self.assertEqual(self.call("ada", "POST", "/api/approve", {"id": pending.approval_id, "approve": True, "remember": True})[0], 403)
        self.assertEqual(self.ws.db.one("SELECT status FROM approvals WHERE id = ?", (pending.approval_id,))["status"], "pending")  # nothing happened
        # a denial cannot be remembered, and code handed secrets never can
        self.assertEqual(self.call("owner", "POST", "/api/approve", {"id": pending.approval_id, "approve": False, "remember": True})[0], 400)
        self.ws.keychain.set("alice", "TOKEN_ONE", "value-123456789")
        with_secret = self.ask("print(1)", secrets=["TOKEN_ONE"])
        self.assertEqual(self.call("owner", "POST", "/api/approve", {"id": with_secret.approval_id, "approve": True, "remember": True})[0], 400)
        # writing a file or scheduling is not in the safe set
        sched = execute(Ctx(self.ws, "alice", "team", 0, "team#1"), "schedule", {"cron": "0 9 * * *", "prompt": "x"})
        if sched.status == "pending":
            self.assertEqual(self.call("owner", "POST", "/api/approve", {"id": sched.approval_id, "approve": True, "remember": True})[0], 400)

    def test_without_isolation_it_stops_applying_and_cannot_be_added(self):
        first = self.ask()
        self.call("owner", "POST", "/api/approve", {"id": first.approval_id, "approve": True, "remember": True})
        with mock.patch("kintsugi.workspace.sandbox.status", return_value={"backend": "process", "isolated": False, "network_blocked": False, "note": ""}):
            self.assertEqual(self.ask().status, "pending")  # the machine lost its sandbox: asks again
            fresh = self.ask("print(7)")
            self.assertEqual(self.call("owner", "POST", "/api/approve", {"id": fresh.approval_id, "approve": True, "remember": True})[0], 400)

    def test_listing_revoking_and_deleting_the_agent(self):
        first = self.ask()
        self.call("owner", "POST", "/api/approve", {"id": first.approval_id, "approve": True, "remember": True})
        listed = self.call("owner", "GET", "/api/standing")[1]
        self.assertEqual([(e["agent"], e["tool"], e["summary"]) for e in listed], [("alice", "run_python", "print(1)")])
        self.invite_and_join("sam", rooms=["team"])
        self.assertEqual(self.call("sam", "GET", "/api/standing")[0], 403)
        self.assertEqual(self.call("sam", "POST", "/api/standing/revoke", {"agent": "alice", "h": listed[0]["h"]})[0], 403)
        self.assertTrue(self.call("owner", "POST", "/api/standing/revoke", {"agent": "alice", "h": listed[0]["h"]})[1]["revoked"])
        self.assertEqual(self.ask().status, "pending")
        second = self.ask()
        self.call("owner", "POST", "/api/approve", {"id": second.approval_id, "approve": True, "remember": True})
        self.ws.delete_agent("alice")
        self.assertIsNone(self.ws.db.one("SELECT 1 FROM settings WHERE key = 'standing:alice'"))

    def test_only_the_owner_is_offered_the_button_and_only_where_it_would_work(self):
        self.invite_and_join("ada", role="admin", rooms=["team"])
        plain = self.ask()
        with_secret = (self.ws.keychain.set("alice", "TOKEN_ONE", "value-123456789"), self.ask("print(2)", secrets=["TOKEN_ONE"]))[1]
        offers = {a["id"]: a["can_remember"] for a in self.call("owner", "GET", "/api/state")[1]["approvals"]}
        self.assertEqual((offers[plain.approval_id], offers[with_secret.approval_id]), (True, False))
        self.assertTrue(all(not a["can_remember"] for a in self.call("ada", "GET", "/api/state")[1]["approvals"]))

    def test_an_agent_has_no_way_to_add_one(self):
        # the only writers are the owner-only approve endpoint; the tool list has nothing that touches it
        from kintsugi.workspace.tools import TOOLS
        self.assertFalse([n for n in TOOLS if "stand" in n or "remember_approval" in n])
        self.assertEqual(standing.listing(self.ws), [])


if __name__ == "__main__":
    unittest.main()
