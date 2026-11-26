# Changelog

## 0.29.0

A cleaner, safer and faster engine.

- **Faster turns**: reads, searches and listings that come before the first write run in parallel (up to 8 at once).
- **Long answers keep going**: when a model stops at its output limit, Codo continues the answer by itself (up to two times).
- **Smarter context**: old tool arguments shrink first, huge tool results are clipped in the middle instead of dropping whole turns, the context meter no longer counts twice.
- **Retries that respect the provider**: 429, 5xx and 529 are retried with `Retry-After` (up to 5 attempts, 60 s at most); a refused connection or a bad certificate fails at once.
- **Safer installs**: a package install needs your own words in the latest message, with every package named there; never in `codo work`.
- **Atomic writes** for files, restores and settings (also on Windows), backups pruned to the last 20.
- **Better file tools**: `edit_file` with `replace_all`, CRLF aware and with a hint when the text is almost there; line edits keep files without a trailing newline intact; `grep` searches hidden files but never `.env`; more build folders skipped.
- **`run_app`** waits until the port answers (IPv4 and IPv6), shows the log tail and stops the whole process group.
- **`codo work`** starts a fresh context after repeated 400/413/422 errors and stops at the spending cap.
- **Sturdier REPL**: a crash in one turn is logged and the conversation goes on, SIGTERM and SIGHUP save and exit, the trust question never reads from a pipe.

## 0.28.0

First release from the DomaAI organisation. Covers everything since 0.23.0.

- **Agent teams** (`codo team run`): a lead splits the goal, each member works in its own git copy, reviews, plan and merge approvals, conflicts resolved by the author, `apply --pr`, team templates, an MCP server for the team (`codo mcp --zespol`).
- **Agent groups** (`codo group`): named line-ups from different providers with five ways of working (parallel with synthesis, split, cross review, vote, pipeline) and a group chat mode where agents reply, react and delegate to each other.
- **ACP agents**: a generic Agent Client Protocol client, about 20 agents selectable as the brain.
- **Agent mail**: agents write to each other and hand over tasks with files, also when the brain is Claude Code or Codex.
- **`codo host`**: always-on agents on a server (systemd or launchd) with Telegram (with voice), Discord, Slack, WhatsApp, Signal and e-mail (only senders verified by DMARC or DKIM/SPF), schedules, daily work limits and quiet hours. Conversations move between your Mac and the server.
- **Skills written by the agent** and a shared user profile; agents search past conversations.
- **`codo ui`**: a browser window with chat, approvals and file changes, for Windows and Linux.
- Reasoning from OpenAI compatible models (`reasoning_content`, `<think>`) goes to the agent log.
- Fixes: a silent ACP agent crash no longer breaks the turn, tests no longer depend on the server time zone.

## 0.23.0

Always-on agents, connections and a backup brain.

- Backup brain: when a model answers with a plan limit, a rate limit, a server error or the network is gone, the turn continues on the backup model you chose, and without internet on a local model (Ollama, LM Studio). The conversation carries over between brains, each one is told what happened in the meantime.
- Works offline: the model list is cached, local models and agents on this computer keep working.
- `codo mcp`: Codo tools as an MCP server for Claude Code and Codex.
- Connections from a DomaAI account: Gmail, Calendar and about 40 connectors, each call that changes something asks first.
- Google Drive for desktop is read as a normal folder.
- iMessage on macOS: read chats and send a message, always with your consent.
- Agent persona and roles (assistant, developer, reviewer, researcher, editor, coordinator) on every brain.
- Tools for the Codo window on Mac: terminal, preview browser and computer control.

## 0.22.1

Installation that works on a computer with nothing on it.

- The installers add what is missing, without a password and without administrator rights: Python (system package manager, Homebrew, `winget`, or a private copy through uv on Linux and macOS and the signed python.org installer on Windows), TLS certificates, git and ripgrep. `CODO_NO_DEPS=1` turns this off.
- Python 3.9 is enough, so the Python that ships with the macOS command line tools works.
- Windows: the installer is plain ASCII (Windows PowerShell 5.1 misread the UTF-8 one), the Microsoft Store `python.exe` placeholder is no longer taken for Python, and new terminal windows see `codo` right away instead of after signing out.
- Windows: output redirected to a file or a pipe no longer crashes on characters outside the ANSI code page.
- macOS: `~/.zshrc` is created when it does not exist, fish and login bash get their `PATH` entry too.
- A truncated or broken download can no longer replace a working installation: the new file is started once before the old one is swapped.
- When `python3` on `PATH` is too old, the installer writes the interpreter it found into the first line of `codo`, and `codo update` keeps it.
- Certificates are also read from the usual system bundle locations, which fixes HTTPS on Python builds that look for them elsewhere.
- `codo doctor` lists Python, TLS certificates, git and ripgrep with the command that installs each one.

## 0.22.0

First public release.

- English interface by default, Polish with `/lang pl` or `CODO_LANG=pl`.
- First start without any account shows MaddLabs sign in with free credits at the top, then your own key or a local model, agents on this computer and DomaAI.
- Several OpenAI compatible accounts at once (`codo login openai|anthropic|xai|google|mistral|deepseek|groq|openrouter|ollama|lmstudio`, `codo accounts`), models written as `@account/model`.
- Claude Code, Codex and Gemini CLI as models (`agent:claude`, `agent:codex`, `agent:gemini`) with permissions mapped to the `read`, `ask` and `auto` modes.
- Fallback when an agent reaches its plan limit: the turn continues on another connected model and the agent is paused for an hour.
- `delegate` tool: hand a task or a read only review to another agent.
- Marathon mode `codo work`: episodes with a fresh context, work log, retries, budget and time limits, background runs with `--bg`, a queue of goals.
- Subagents (`task`), live todo list (`/todos`), saved conversations (`codo -c`, `codo resume`), `@file` mentions, `!command`, `/init`, `/compact`, custom commands in `.codo/commands`.
- `codo -p` print mode for scripts, with `--json`.
