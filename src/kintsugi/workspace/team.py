"""Teams: separate logins, invite links and roles.

Who is who
  owner   whoever holds the workspace access token (KINTSUGI_TOKEN or the token file). One per workspace. Can do everything,
          including API keys, plugins, backups, and managing admins. Appears in rooms as "you".
  admin   trusted teammates: manage agents, rooms, people and approvals, but not API keys, plugins, backups, internet
          or spending settings.
  member  everyday users: chat in the rooms and direct chats they belong to, set their own reply style, and approve
          only what the approval policy lets them approve.

How people get in: an owner or admin creates a single-use, expiring invite link. The person opens it, chooses a name, and
receives a personal token (shown once, kept in their browser, stored on the server only as a SHA-256 hash). Removing a person
or rotating their token locks the old token out at once.

Everything is enforced on the server, by endpoint, and anything not listed here is owner-only (deny by default), so a new
endpoint is never accidentally open to members.

Honest limits: the owner token is a single shared secret and the owner can read every room, including other people's
direct chats (it is their server). Invite links and tokens travel in the browser, so use HTTPS. There is no email
verification, password reset or single sign-on.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .core import Workspace

ROLES = ("member", "admin", "owner")
RANK = {r: i for i, r in enumerate(ROLES)}
USER_RE = re.compile(r"^[a-z][a-z0-9_-]{1,23}$")
RESERVED = {"you", "system", "all", "everyone", "owner", "admin", "root"}
POLICIES = ("admins", "requester", "everyone")
INVITE_DAYS_DEFAULT, INVITE_DAYS_MAX, MAX_USERS, MAX_OPEN_INVITES = 7, 30, 50, 20
OWNER = "you"  # the owner's name everywhere in messages, rooms and settings (what the single-user app always used)


class TeamError(Exception):
    """A people or permission problem the person can understand (shown as-is)."""


@dataclass(frozen=True)
class Identity:
    name: str
    role: str  # member | admin | owner

    def at_least(self, role: str) -> bool:
        return RANK[self.role] >= RANK[role]


# Minimum role per endpoint. Anything not listed needs the owner. (GET and POST share one table: the paths differ.)
MEMBER_PATHS = {
    "/api/state", "/api/messages", "/api/say", "/api/dm", "/api/me", "/api/me/token", "/api/tone", "/api/push", "/api/push/subscribe",
    "/api/push/unsubscribe", "/api/push/test", "/api/approve", "/api/timezone", "/api/applink", "/api/automations",
    "/api/automations/toggle", "/api/automations/run", "/api/jobs", "/api/jobs/delete", "/api/stop", "/api/find", "/api/upload",
}
ADMIN_PATHS = {
    "/api/agents", "/api/persona", "/api/secret", "/api/secret/delete", "/api/agent/delete", "/api/agent/model", "/api/agent/playbook",
    "/api/agent/internet", "/api/tier", "/api/rooms", "/api/room/delete", "/api/room/members", "/api/audit", "/api/usage", "/api/templates", "/api/templates/apply", "/api/team/reset", "/api/download", "/api/files", "/api/file",
    "/api/lessons", "/api/improve", "/api/improve/study", "/api/improve/models", "/api/improve/settings", "/api/improve/run",
    "/api/improve/decide", "/api/improve/revert", "/api/team", "/api/team/invite", "/api/team/revoke-invite", "/api/team/remove",
}
# owner only (by default): /api/providers*, /api/search*, /api/internet, /api/plugins*, /api/parallel, /api/backup*, /api/purge,
# /api/export, /api/team/role, /api/team/policy, anything new.


def required_role(path: str) -> str:
    if path in MEMBER_PATHS:
        return "member"
    if path in ADMIN_PATHS:
        return "admin"
    return "owner"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Team:
    def __init__(self, ws: "Workspace") -> None:
        self.ws = ws

    # --- who is calling -------------------------------------------------------------------

    def identify(self, token: str, owner_token: str) -> Identity | None:
        if token and hmac.compare_digest(token.encode(), owner_token.encode()):
            return Identity(OWNER, "owner")
        if not token or len(token) < 20:
            return None
        row = self.ws.db.one("SELECT name, role, last_seen FROM users WHERE token_hash = ?", (_hash(token),))
        if row is None:
            return None
        now = self.ws.clock()
        if not row["last_seen"] or now - row["last_seen"] > 60:
            self.ws.db.execute("UPDATE users SET last_seen = ? WHERE name = ?", (now, row["name"]))
        return Identity(row["name"], row["role"])

    # --- people -----------------------------------------------------------------------------

    def users(self) -> list[dict]:
        return self.ws.db.query("SELECT name, role, created, last_seen FROM users ORDER BY created")

    def get(self, name: str) -> dict | None:
        return self.ws.db.one("SELECT name, role, created, last_seen FROM users WHERE name = ?", (name,))

    def is_person(self, name: str) -> bool:
        return name == OWNER or self.get(name) is not None

    def _check_name(self, name: str) -> str:
        name = (name or "").strip().lower()
        if not USER_RE.match(name):
            raise TeamError("a name is 2-24 characters: lowercase letters, digits, '-' and '_', starting with a letter")
        if name in RESERVED or name.startswith(("cron-", "dm-")) or self.ws.get_agent(name, missing_ok=True) or self.get(name):
            raise TeamError("that name is taken or reserved; choose another")
        return name

    def _new_token(self) -> str:
        return "kt_" + secrets.token_urlsafe(32)

    # --- invites ------------------------------------------------------------------------------

    def create_invite(self, by: Identity, role: str = "member", rooms: list[str] | None = None, days: float = INVITE_DAYS_DEFAULT) -> dict:
        if role not in ("member", "admin"):
            raise TeamError("an invite is for a member or an admin")
        if role == "admin" and not by.at_least("owner"):
            raise TeamError("only the owner can invite an admin")
        open_now = self.ws.db.one("SELECT COUNT(*) AS n FROM invites WHERE used_by IS NULL AND expires > ?", (self.ws.clock(),))["n"]
        if open_now >= MAX_OPEN_INVITES:
            raise TeamError(f"at most {MAX_OPEN_INVITES} open invites; revoke some first")
        if len(self.users()) >= MAX_USERS:
            raise TeamError(f"at most {MAX_USERS} people")
        rooms = [r for r in (rooms if rooms is not None else (["team"] if self.ws.db.one("SELECT 1 FROM rooms WHERE name = 'team'") else []))]
        for room in rooms:
            if self.ws._require_room(room)["kind"] != "room":
                raise TeamError("invites can add people to shared rooms only")
        days = min(max(float(days), 0.01), INVITE_DAYS_MAX)
        code = "ki_" + secrets.token_urlsafe(18)
        self.ws.db.execute("INSERT INTO invites (code_hash, role, rooms, created_by, created, expires) VALUES (?, ?, ?, ?, ?, ?)",
                           (_hash(code), role, json.dumps(rooms), by.name, self.ws.clock(), self.ws.clock() + days * 86400))
        self.ws.audit(None, "invite-created", f"{role} by {by.name}, rooms {rooms}")
        return {"code": code, "role": role, "rooms": rooms, "expires": self.ws.clock() + days * 86400, "id": _hash(code)[:10]}

    def invites(self) -> list[dict]:
        rows = self.ws.db.query("SELECT code_hash, role, rooms, created_by, created, expires, used_by FROM invites ORDER BY created DESC LIMIT 50")
        now = self.ws.clock()
        return [{"id": r["code_hash"][:10], "role": r["role"], "rooms": json.loads(r["rooms"]), "created_by": r["created_by"], "expires": r["expires"],
                 "status": "used by " + r["used_by"] if r["used_by"] else ("expired" if r["expires"] <= now else "open")} for r in rows]

    def revoke_invite(self, invite_id: str) -> None:
        row = self.ws.db.one("SELECT code_hash FROM invites WHERE substr(code_hash, 1, 10) = ? AND used_by IS NULL", (str(invite_id)[:10],))
        if row is None:
            raise TeamError("no such open invite")
        self.ws.db.execute("DELETE FROM invites WHERE code_hash = ?", (row["code_hash"],))
        self.ws.audit(None, "invite-revoked", str(invite_id)[:10])

    def join(self, code: str, name: str) -> dict:
        """Turn an invite into a person. The invite works once; the token returned here is shown once and never stored in clear."""
        row = self.ws.db.one("SELECT * FROM invites WHERE code_hash = ?", (_hash(code or ""),))
        if row is None or row["used_by"] or row["expires"] <= self.ws.clock():
            raise TeamError("this invite link is not valid any more (it was used, revoked or expired). Ask for a new one")
        name = self._check_name(name)
        token = self._new_token()
        with self.ws.db.lock:  # claim the invite and create the person together, so a link can never be used twice
            claimed = self.ws.db.conn.execute("UPDATE invites SET used_by = ? WHERE code_hash = ? AND used_by IS NULL", (name, row["code_hash"])).rowcount
            if not claimed:
                raise TeamError("this invite link was just used by someone else")
            self.ws.db.conn.execute("INSERT INTO users (name, role, token_hash, created) VALUES (?, ?, ?, ?)",
                                    (name, row["role"], _hash(token), self.ws.clock()))
            self.ws.db.conn.commit()
        for room in json.loads(row["rooms"]):
            if self.ws.db.one("SELECT 1 FROM rooms WHERE name = ?", (room,)):
                self.ws.add_member(room, name)
        self.ws.audit(None, "person-joined", f"{name} as {row['role']}")
        return {"name": name, "role": row["role"], "token": token}

    # --- managing people ----------------------------------------------------------------------------

    def remove(self, by: Identity, name: str) -> None:
        user = self.get(name)
        if user is None:
            raise TeamError("no such person")
        if RANK[user["role"]] >= RANK[by.role] and by.role != "owner":
            raise TeamError("you cannot remove someone with the same or a higher role")
        for room in self.ws.list_rooms():  # their private chats go with them: a new person must never inherit them
            if room["kind"] == "dm" and name in self.ws.members(room["name"]):
                self.ws.delete_room(room["name"])
        self.ws.db.execute("DELETE FROM invites WHERE created_by = ? AND used_by IS NULL", (name,))  # their open invites must not outlive them
        self.ws.db.execute("DELETE FROM users WHERE name = ?", (name,))
        self.ws.db.execute("DELETE FROM members WHERE member = ?", (name,))
        self.ws.db.execute("DELETE FROM push_subs WHERE user = ?", (name,))
        self.ws.db.execute("DELETE FROM jobs WHERE owner = ?", (name,))
        self.ws.db.execute("DELETE FROM settings WHERE key = ?", (f"tone:{name}",))
        self.ws.db.execute("UPDATE approvals SET requested_by = NULL WHERE requested_by = ?", (name,))
        self.ws.audit(None, "person-removed", f"{name} by {by.name}")

    def set_role(self, name: str, role: str) -> None:
        if role not in ("member", "admin"):
            raise TeamError("a role is member or admin")
        if self.get(name) is None:
            raise TeamError("no such person")
        self.ws.db.execute("UPDATE users SET role = ? WHERE name = ?", (role, name))
        if role == "member":
            self.ws.db.execute("DELETE FROM invites WHERE created_by = ? AND used_by IS NULL", (name,))  # a demoted admin's open invites (some for admins) go too
        self.ws.audit(None, "role-changed", f"{name} -> {role}")

    def reset_token(self, by: Identity, name: str) -> str:
        """Give a person a new sign-in (they lost theirs or signed out everywhere). Admins can do this for members; the owner for anyone."""
        user = self.get(name)
        if user is None:
            raise TeamError("no such person")
        if RANK[user["role"]] >= RANK[by.role] and by.role != "owner":
            raise TeamError("you can only reset a member's sign-in")
        token = self._new_token()
        self.ws.db.execute("UPDATE users SET token_hash = ? WHERE name = ?", (_hash(token), name))
        self.ws.audit(None, "token-reset", f"{name} by {by.name}")
        return token

    def rotate_token(self, name: str) -> str:
        if self.get(name) is None:
            raise TeamError("the owner's token is changed by setting KINTSUGI_TOKEN (or deleting the token file), not here")
        token = self._new_token()
        self.ws.db.execute("UPDATE users SET token_hash = ? WHERE name = ?", (_hash(token), name))
        self.ws.audit(None, "token-rotated", name)
        return token

    # --- who may approve ------------------------------------------------------------------------------

    def policy(self) -> str:
        value = self.ws.get_setting("approval_policy", "admins")
        return value if value in POLICIES else "admins"

    def set_policy(self, policy: str) -> str:
        if policy not in POLICIES:
            raise TeamError("policy must be one of: " + ", ".join(POLICIES))
        self.ws.set_setting("approval_policy", policy)
        self.ws.audit(None, "approval-policy", policy)
        return policy

    @staticmethod
    def owner_only_tool(tool: str, args: str | dict | None = None) -> bool:
        """Code that could run with the server's own rights (fix_code always; run_python when it is not isolated) can only be approved
        by the owner: otherwise an admin could read the keychain and the owner token and take over the workspace."""
        from . import sandbox

        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        handed_secrets = tool == "run_python" and bool((args or {}).get("secrets"))  # code that is given secret values could print them in a form redaction misses
        return tool == "fix_code" or handed_secrets or (tool == "run_python" and not sandbox.status()["isolated"])

    def can_decide(self, who: Identity, approval: dict) -> bool:
        """Owners can always decide, admins too (except for code that would run unisolated). Members only when the policy says so AND
        they belong to the room it came from."""
        if self.owner_only_tool(approval["tool"], approval.get("args")) and who.role != "owner":
            return False
        if who.role != "owner" and who.name not in self.ws.members(approval["room"]):
            return False  # nobody but the owner decides (or sees) approvals from chats they are not part of
        if who.at_least("admin"):
            return True
        policy = self.policy()
        if policy == "everyone":
            return True
        return policy == "requester" and approval.get("requested_by") == who.name

    def can_use_agent(self, who: Identity, agent: str) -> bool:
        """Owners and admins can use any agent; a member only agents that share a chat with them."""
        if who.at_least("admin"):
            return True
        for room in self.ws.list_rooms():
            members = self.ws.members(room["name"])
            if agent in members and who.name in members:
                return True
        return False

    def can_see_room(self, who: Identity, room: str) -> bool:
        return who.role == "owner" or who.name in self.ws.members(room)
