# memnotify — visible memory activity in chat

A reaction is easy to miss; a line in the chat is not. memnotify posts one short
message per memory operation while the turn runs:

```
🧠 memory-x.md read
🧠 Updating memory-y.md
🧠 memory-z.md created
🧠 MEMORY.md updated
🧠 memories searched
```

## Install

```bash
cp -a plugin/memnotify ~/.hermes/profiles/<profile>/plugins/
hermes plugins enable memnotify
hermes config set plugins.entries.memnotify.allow_platform_actions true
hermes gateway restart   # optional: hooks reload on enable, the module does not
```

`allow_platform_actions` is required for the reaction path only; the message
path resolves the live adapter directly and needs no capability. There is no
reaction any more — see the note at the bottom.

## What it watches

| Tool call | Line |
|---|---|
| `read_file` on a store file | `<file> read` |
| `patch` on a store file | `Updating <file>` |
| `write_file`, path absent before the call | `<file> created` |
| `write_file`, path existed | `<file> updated` |
| `memory` tool | `MEMORY.md updated` (or `USER.md`) |
| `execute_code` / `terminal` naming a store file | `<file> read` |
| `execute_code` / `terminal` naming the store dir | `memories searched` |

`pre_tool_call` records whether the target existed, which is the only way to
tell "created" from "updated" after the fact.

Dedupe is per (session, turn, line): a file read twice in one turn shows once.

## How the message gets out

`post_tool_call` → resolve `(chat_id, thread_id)` from the profile `state.db`
(`sessions`) → schedule `adapter.send(...)` on the gateway's own event loop
(`runner._gateway_loop`) with `_interim_send` metadata, so the stream path treats
it as mid-turn status rather than the final answer.

Log: `~/.hermes/state/memnotify.log`, one line per send with the adapter result.

## Limits

- Telegram only.
- Cron and CLI turns have no chat session row and are skipped.
- Sends bypass the session ledger: chat-only, not part of the transcript.
- Linux paths assembled from pieces at runtime (`"MEM" + "ORY.md"`) are invisible
  to the detector — a deliberate trade, since the same detector must stay cheap.
- An earlier revision reacted with an emoji instead of posting a line. Telegram
  rejects 🧠 in the default reaction set (`REACTION_INVALID`), and a reaction that
  silently falls back to 🤓 is worse than a line that says what happened.
