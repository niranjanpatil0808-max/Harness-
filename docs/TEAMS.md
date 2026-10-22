# Teams: separate logins, invite links and roles

One person (the **owner**) runs the workspace. Everyone else gets their own login through a single-use invite link.

## Roles

| | Member | Admin | Owner |
|---|---|---|---|
| Chat in rooms they belong to; private chats with agents or other people | yes | yes | yes (sees every room) |
| Set their own reply style, notifications, schedules in their rooms | yes | yes | yes |
| Approve risky actions | only if the approval policy allows | yes | yes |
| Create and edit agents, rooms, who is in a room; view agent files and the log | no | yes | yes |
| Invite and remove members | no | yes | yes |
| Invite admins, change roles, set the approval policy | no | no | yes |
| API keys (Models), plugins, backups, the internet switch, spending and parallel limits, search key, export, delete all data | no | no | yes |

The owner is whoever holds the access token (`KINTSUGI_TOKEN` or the token file). Everything else is **denied by default**: a
new endpoint is owner-only until it is deliberately opened to a lower role.

## Inviting people

Settings > Team > **Create invite link**. Pick member or admin (only the owner can invite admins) and which shared rooms they join.
Send the link privately. It works once and expires in 7 days. The person opens it, picks a name, and their browser stays signed
in with a personal token that is shown once and stored on the server only as a SHA-256 hash. Names are lowercase letters, digits,
`-` and `_`; `you`, `system`, `all`, agent names and a few others are reserved.

Remove a person (Settings > Team) and their token stops working at once. Anyone can make a new token for themselves
(Settings > General > Your account), which invalidates the old one.

## Rooms and private chats

- **Shared rooms**: admins choose who is in them (people and agents). Members only see rooms they belong to.
- **Private chats**: a direct chat between a person and an agent (or two people) is a room only those two are in. Other members cannot read it.
  The owner can read every room, because it is the owner's server.
- An agent will not post into a room the person who asked is not part of, so a private chat is not carried into other rooms by an agent.
- `@all` wakes every agent in the room at once.

## Who can approve a risky action

Settings > Team > *Who can approve risky actions* (owner only):

- **Only admins** (default): admins and the owner approve; the person who asked sees it is waiting.
- **The person who asked** can also approve their own request.
- **Anyone in the room** can approve.

Owners and admins can always decide. A scheduled run is attributed to the person who set the schedule up. Approval decisions are
recorded with the name of whoever decided.

## Honest limits

- **Agents have one memory and one folder each**, shared by everyone who can talk to them. Something a person tells an agent in a
  private chat can come up later when a teammate talks to that agent. Use separate agents for things that must stay separate.
- The owner can read everything, including other people's private chats.
- Tokens and invite links travel through the browser: use HTTPS (hosting platforms provide it). There is no email check, password
  reset or single sign-on; losing a token means asking for a new invite.
- **Integration and plugin tools run for anyone who can talk to an agent they are switched on for.** If you switch GitHub, Slack, Gmail or
  Calendar on for an agent, any member of a room that agent is in can ask it to read from them. Switch integrations on only for agents
  (and rooms) whose members you are comfortable sharing that data with.
- **Admins** can add themselves to any shared room, read agent files and lessons, and approve risky actions in rooms they belong to,
  but cannot read other people's private chats, tool arguments in the log, or approvals from chats they are not part of. Code that would
  run with the server's own rights, or that is handed secret values, can only be approved by the owner; only the owner can make an agent that
  never asks, turn on lesson sharing, or delete a private chat.
- **Published agent apps** are shown on the workspace's address. A page made by an agent can look like anything, so never type passwords or
  tokens into one (the approval card for publishing says so).
- Limits per person: 30 messages a minute, 20 schedules, 20 notification devices.
- Tested with scripted tests and two real browsers on one machine, not yet with a real group over a real deployment.
