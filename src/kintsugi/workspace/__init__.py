"""Kintsugi Workspace: a small multi-agent workspace whose agents learn from their mistakes.

Each agent has a durable folder (its sandbox), its own mistake memory (kintsugi.memory), a keychain,
a permission tier, scheduled jobs and optional web apps. Agents work alone or together in rooms and
direct messages. The idea follows YC's open-source QM (https://github.com/yc-software/qm, MIT);
this is an independent, much smaller implementation written from scratch.
"""

from .core import Workspace

__all__ = ["Workspace"]
