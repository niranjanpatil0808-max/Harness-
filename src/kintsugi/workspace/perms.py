"""Permission tiers, in the spirit of QM's strict / auto / dangerous modes.

  strict     every tool call waits for a human to approve it
  auto       safe tools run at once; risky tools wait for approval  (default)
  dangerous  every allowed tool runs at once

An agent can also have an allow-list of tools; anything outside it is denied outright.
"""

from __future__ import annotations

TIERS = ("strict", "auto", "dangerous")

ALLOW, ASK, DENY = "allow", "ask", "deny"


def decide(tier: str, risk: str, tool: str, allowed_tools: list[str] | None) -> str:
    """What should happen when an agent calls `tool` (whose risk is 'safe' or 'risky')?"""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}")
    if allowed_tools is not None and tool not in allowed_tools:
        return DENY
    if tier == "dangerous":
        return ALLOW
    if tier == "strict":
        return ASK
    return ALLOW if risk == "safe" else ASK
