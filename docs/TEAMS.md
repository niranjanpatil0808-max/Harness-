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

## Working with agents as a team

- **Team tasks** (sidebar > Tasks, or Ctrl/Cmd+K "tasks"): pick a room, an agent and what it should do. The task is posted in the room
  ("@alice Task #7: ...") and the board shows everyone in that room how it is going: *Waiting to start*, *Working*, *Needs approval*,
  *Done*, *Stopped* or *Failed*, with a link to the result. The person who gave a task, or an admin, can ask again, mark it done or remove it.
  You only see tasks from rooms you are in (the owner sees all). A task gives the agent no extra powers: approvals apply as usual.
- **Share**: every message has a *Share* button. It copies the message into another room you are in, with your name and where it came
  from ("Shared by sam from a private chat with alice"). It wakes no agent. Use it to bring a good answer from a private chat to the team.
- **@mentions**: writing `@sam` in a room nudges Sam's phone (if notifications are on and Sam is not in the app right now). `@agent`
  wakes that agent; `@all` wakes every agent in the room.
- **Files**: a file you attach is given to the agent *in that chat only*. The agent reads it as `uploads/<name>` while working in that
  chat; in other rooms it cannot see it, and only people in that chat can download it. (Agent code run with run_python cannot see uploads.)
- **Repeating tasks**: when you give a task you can choose to repeat it every weekday, every Monday or daily at 9:00. It is given now and also appears under Automations, belongs to you, and goes if you are removed.
- **Delete a message**: tap your own message and choose Delete. Admins can delete anyone's message in rooms they can see. Summaries made from the room are dropped.
- **Long chats**: agents see the last 12 messages and a short summary of older ones, so a team can come back to a room days later.

## Agents get to know each person

Every 8 messages a person sends, one extra model call updates a short profile of them from their own recent messages and the replies
they marked 👍 or 👎. It has two parts:

- **How you like replies** (length, format, language, tone): used in every chat with you, including shared rooms.
- **About your work** (role, projects, recurring tasks): used only in your private chats with agents, never in shared rooms.

Each person sees and edits only their own profile in Settings > General ("What agents have learned about you"), and can clear it or
switch learning off. Sentences that look like rule changes ("ignore the approval rules") or secrets are dropped; the profile can only
shape style and context, never permissions. It is deleted when the person is removed. Honest limits: the owner's server stores it
(so the owner could read it in the database); the model may learn something wrong, so check it now and then; it is not tested with
real models yet.

## Signing in again

If someone loses their sign-in, the **owner** opens Settings > Team > *Reset sign-in* for that person. Their old sign-in stops working at
once, and the owner gets a link to send them privately. The link carries a **one-time code**, not their key: it works once, expires in a
day, and opening it makes a fresh key that exists only in that person's browser, so a link left in a chat or browser history is useless
afterwards. Admins cannot do this, because a new sign-in would let them read that person's private chats. If a browser is already signed in
as someone, opening a link asks before switching accounts. (The owner's own link, printed when the server starts, is still the permanent
owner key: keep it private.)

## Who can approve a risky action

Settings > Team > *Who can approve risky actions* (owner only):

- **Only admins** (default): admins and the owner approve; the person who asked sees it is waiting.
- **The person who asked** can also approve their own request.
- **Anyone in the room** can approve.

Owners and admins can always decide. A scheduled run is attributed to the person who set the schedule up. Approval decisions are
recorded with the name of whoever decided.

**Always allow this exact one (owner only).** On an approval card the owner also sees *Always allow this exact one*. From then on that
agent's identical call (same tool, same arguments, character for character) runs without asking, which keeps a repeating task from
stalling while nobody is around. It never widens anything: other code, other links or another agent still ask, and calls that are given
secrets, could send data out, or would run without isolation never offer the button. Settings > Remembered approvals lists every one with a
Revoke button; deleting the agent clears them; each automatic run is recorded in the audit log as *auto-allowed*. Agents cannot add one.

## Honest limits

- **What stays in its chat:** files you attach, notes an agent saves with `remember`, and the long-chat summary. These are only
  available to the agent while it works in that chat, and are deleted with it.
- **Files an agent writes in a private chat** are labelled with that chat: the agent will not read, list or overwrite them from another room,
  and admins outside that chat cannot download them. A file written or rewritten in a shared room is shared. **Limit:** code an agent runs
  (`run_python`, which you approve after reading it) can open any file in its folder, so approved code in a team room could still read such a
  file. Use separate agents for work that must stay separate.
- **What an agent still shares across chats:** its published apps and its lessons from mistakes (general rules it learned from failed tool calls).
- The owner can read everything, including other people's private chats.
- Tokens and invite links travel through the browser: use HTTPS (hosting platforms provide it). There is no email check, password
  reset or single sign-on; losing a sign-in means asking the owner for a new link.
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
