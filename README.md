<p align="center">
  <img src="assets/agents.png" width="720" alt="Codo and its crew: Josh, Luna, Codo, Max and Mia">
</p>

<h1 align="center">Codo</h1>

**One terminal agent on top of every model and coding agent you already pay for.**
Claude Code, Codex, Gemini CLI, 20+ ACP agents, any OpenAI compatible API or a local model:
Codo drives them all from one session, and when one hits its plan limit the same conversation
keeps going on the next one.

[![CI](https://github.com/DomaAI/Codo/actions/workflows/ci.yml/badge.svg)](https://github.com/DomaAI/Codo/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/DomaAI/Codo)](https://github.com/DomaAI/Codo/releases/latest)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Linux | macOS | Windows](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-lightgrey)

```bash
curl -fsSL https://github.com/DomaAI/Codo/releases/latest/download/install.sh | bash
codo
```

## Why Codo

- **Never stuck on a plan limit.** Claude Code ran out? The turn moves to Codex, Gemini, your API key
  or a local model, with the whole conversation, and the limited agent rests for an hour.
- **Bring your own everything.** OpenAI, Anthropic, xAI, Google, Mistral, DeepSeek, Groq, OpenRouter,
  Ollama, LM Studio or any `/v1` URL. Several accounts at once, pick a model per turn with `/model`.
- **Agent teams.** `codo team run "goal"`: a lead splits the work, each member gets its own git copy,
  reviewers check it, you approve the plan and the merge, and `apply --pr` opens a pull request.
- **Agent groups across providers.** `codo group`: Claude, Codex and Gemini side by side, in parallel
  with a synthesis, split work, cross review, voting, a pipeline, or a group chat.
- **Marathon mode.** `codo work "goal" --hours 8 --bg` plans, works in episodes with a fresh context,
  keeps a log, retries network errors and stops at hard budget and time limits.
- **Always-on agents on a server.** `codo host` keeps agents running under systemd or launchd and
  answers on Telegram, Discord, Slack, WhatsApp, Signal and e-mail. Agents write to each other and
  hand tasks over, on your Mac and on the server together.
- **MCP both ways.** `codo mcp` exposes Codo tools (browser, team, mail) to Claude Code and Codex.
- **Skills that the agent writes itself**, plus skills from GitHub (`codo skills`).
- **A browser window when you want one.** `codo ui` opens chat, approvals and file diffs in the browser
  on Linux and Windows. On macOS there is a native app (see below).
- **Undo for every edit.** Each file change is backed up; `/undo` reverts it, `/diff` shows it.
- **Phone control.** With the DomaAI app (iOS, Android), `/rc` lets you follow the session and answer
  its questions from your phone. Commands that change things still ask for consent.
- **A single Python file.** No dependencies beyond Python 3.9+, and the installer brings Python along
  when the computer has none.

## How it works

```
 you ── codo (terminal, browser window or the Mac app)
          │
          ├─ brain: MaddLabs, DomaAI, your API keys, a local model,
          │         or Claude Code / Codex / Gemini CLI / ACP agents on this computer
          │         (on a plan limit or provider error the turn moves to the next one)
          │
          ├─ tools: read, search, edit files, run commands, browser, web, MCP servers,
          │         skills, sub agents, teams
          │
          └─ safety: trusted folders, read / ask / auto modes, a backup of every edit,
                     hard budget and time limits for long work
```

1. **You start Codo in a folder.** It asks once whether you trust the folder, reads `Codo.md`
   (the project memory) and picks the model you chose with `codo login` or `/model`.
2. **The agent works in a loop.** It plans, reads and searches files (up to 8 of those in parallel),
   edits them and runs commands. Every step is shown live, and edits and commands ask for your
   consent in the default `ask` mode.
3. **Every change can be undone.** Each edit is written atomically with a backup in `.doma/backups`;
   `/diff` shows what changed and `/undo` reverts it.
4. **Context stays small.** Old tool arguments shrink first, huge outputs are clipped in the middle,
   and `/compact` summarizes a long conversation. When a model stops at its output limit Codo
   continues the answer by itself.
5. **It does not get stuck.** Rate limits and server errors are retried with the provider's
   `Retry-After`. When a plan runs out, the same conversation continues on the next brain.
6. **Bigger work scales out.** `codo work` runs for hours in episodes with fresh context and a log,
   `codo team` splits a goal between agents that each work in their own git copy, and `codo host`
   keeps agents running on a server where they answer messages and hand tasks to each other.

## Everything in one place

| Area | What Codo does | Command |
| --- | --- | --- |
| Conversation | Interactive session, one shot task, resume, print mode for scripts with JSON output | `codo`, `codo "task"`, `codo -c`, `codo resume`, `codo -p --json` |
| App window | Chat, approvals and file diffs in Codo's own window (Windows and Linux; `--tab` for a browser tab) | `codo ui` |
| Long work | Works alone for hours or days with a plan, log, queue of goals and hard limits | `codo work`, `codo work add`, `codo work status` |
| Teams | A lead splits a goal, members work in separate git copies, reviewers check, you approve the plan and the merge, a pull request at the end | `codo team run`, `codo team apply --pr` |
| Groups of agents | Claude, Codex and Gemini in parallel with a synthesis, split work, cross review, voting, a pipeline or a group chat | `codo group` |
| Always on | Agents under systemd or launchd that answer on Telegram, Discord, Slack, WhatsApp, Signal and e-mail, write to each other and pass on tasks with files | `codo host` |
| Models | OpenAI, Anthropic, xAI, Google, Mistral, DeepSeek, Groq, OpenRouter, Ollama, LM Studio, any `/v1` URL, several accounts at once | `codo login`, `codo accounts`, `/model` |
| Agents you already pay for | Claude Code, Codex, Gemini CLI and ACP agents as brains, with automatic fallback | `codo agents`, `codo login agent` |
| MCP | Use MCP servers in Codo, and expose Codo's browser, team and mail tools to other agents | `codo mcp` |
| Skills | Skills the agent writes for itself, per project or global, and skills from GitHub | `codo skills`, `/skill` |
| Project memory | `Codo.md` read at every start, `/init` writes one | `/init` |
| Your commands | Markdown files become slash commands | `.codo/commands/NAME.md` |
| Phone | Follow the session and answer its questions from the DomaAI app | `codo serve`, `codo pair`, `/rc` |
| Maintenance | Self update, diagnosis of connection, account, `PATH` and autostart | `codo update`, `codo doctor`, `codo status` |

### In the interactive session

| Command | What it does |
| --- | --- |
| `/model`, `/effort` | Switch the model or how hard it thinks (low, medium, high, xhigh, max) |
| `/plan` | Plan first, then work |
| `/diff`, `/undo`, `/files` | Show changes, revert the last edit, list touched files |
| `/compact`, `/clear` | Summarize or clear the conversation |
| `/todos`, `/cost`, `/status` | Task list, spending, account and folder |
| `/work`, `/zespol`, `/konta`, `/agenci` | Marathon, team, accounts and agents without leaving the session |
| `/resume`, `/skills`, `/commands`, `/help` | Older conversations, skills, your commands, help |
| `@path` | Attach a file or folder (Tab completes) |
| `!command` | Run a shell command right away |
| **Shift+Tab** | Switch between `read`, `ask` and `auto` |

## Install

**Linux and macOS**

```bash
curl -fsSL https://github.com/DomaAI/Codo/releases/latest/download/install.sh | bash
```

**Windows**

Download [`CodoSetup-x64.exe`](https://github.com/DomaAI/Codo/releases/latest/download/CodoSetup-x64.exe)
and run it. It installs for your user without administrator rights into
`%LOCALAPPDATA%\Programs\Codo`, adds `codo` to `PATH` and has a normal uninstaller. The Start
menu gets **Codo**, the app in its own window, and **Codo Terminal**, the agent in a terminal.
Windows 10 and 11, 64 bit.

Or from PowerShell, without downloading an `.exe`:

```powershell
irm https://github.com/DomaAI/Codo/releases/latest/download/install.ps1 | iex
```

> Windows 11 Smart App Control and some browsers block programs from publishers they do not know
> yet. Code signing for the Windows files is on its way. Until then the PowerShell command above
> works everywhere. After it, `codo ui` opens the Codo window.

The installer downloads `codo` from the latest release, checks its SHA-256 sum against
`SHA256SUMS` and puts it in `~/.local/bin` (Windows: `%LOCALAPPDATA%\Codo\bin`). You can also download
`codo` from [Releases](https://github.com/DomaAI/Codo/releases) and run it with `python3 codo`.

**What the installer adds when it is missing.** It never asks for a password and never needs
administrator rights.

| | Linux and macOS | Windows |
|---|---|---|
| Python 3.9+ (required) | system package manager when you are root or have passwordless sudo (apt, dnf, pacman, zypper, apk) or Homebrew; otherwise a private copy through [uv](https://docs.astral.sh/uv/) in `~/.local/share/codo` | `winget` for the current user; otherwise the signed installer from python.org |
| TLS certificates (required) | `ca-certificates`, or `certifi` | Windows certificate store |
| git, ripgrep (recommended) | installed when a package manager is usable | `winget` |
| `PATH` | the file of your shell (zsh, bash, fish), created if needed | user `PATH`, visible in new windows right away |

Set `CODO_NO_DEPS=1` to install nothing but Codo itself; the installer then only tells you what is
missing. `codo doctor` shows the state of every dependency and the command that adds it.


### Single files, no Python needed

Every release also has ready to run files: `CodoSetup-x64.exe` (installer), `codo-windows-x64.exe`, `codo-linux-x64`, `codo-linux-arm64`, `codo-macos-arm64` (Apple Silicon) and `codo-macos-x64` (Intel). Download one from [Releases](https://github.com/DomaAI/Codo/releases/latest), make it executable on macOS and Linux (`chmod +x`) and run it. The Mac app (Apple Silicon and Intel) is on [domaai.pl/pobierz-codo](https://domaai.pl/pobierz-codo.html).

## Codo for Mac

A native window on top of the same engine, for Apple Silicon and Intel, macOS 15 or newer, signed
and notarized by Apple and updating itself:
[download Codo.dmg](https://bymadd.pl/static/codo/mac/Codo.dmg).

- **Agents with a face.** Create an agent in one sentence, give it a name, a shape and a character,
  and see the whole crew working at once.
- **Rooms.** Shared threads where several agents and you work on one task together.
- **Bots and automations.** Describe a bot in your own words or start from ready ones; they run on
  a schedule, on a webhook or on an e-mail, and report on Telegram, Discord, iMessage or a
  notification.
- **Agent mail.** Agents write to each other and hand over tasks with files, on your Mac and on a
  server together.
- **Terminal, browser and files in the window.** The agent's browser keeps its sign ins, drag and
  drop files into the conversation, preview pages and documents.
- **Office documents.** Presentations, documents, spreadsheets and posters, exported to PPTX,
  DOCX, XLSX and PDF.
- **Gmail, Calendar and Drive**, and more than 40 connections to other services.
- **18 languages**, from English and Polish to Japanese, Korean and Chinese, with the agent
  answering in your language. Light and dark appearance.

## Quick start

```bash
codo login        # choose how Codo talks to a model
cd your-project
codo              # interactive session in this folder
```

On the first start Codo asks you to trust the folder and shows the sign in options:

1. **MaddLabs account**, free credits to start (see below)
2. **Your own API key** or a local model (Ollama, LM Studio)
3. **Agents on this computer**: Claude Code, Codex or Gemini CLI on your existing plan
4. **DomaAI account**, which adds phone control and the DomaAI agent

More ways to run it:

```bash
codo "add a dark theme to the settings page"     # one task and done
cat error.log | codo -p "explain this"          # print mode for scripts, add --json for JSON
codo -c                                          # resume the last conversation in this folder
codo work "migrate the API to v2" --hours 8      # marathon with a time limit
codo work status | codo work log -f | codo work stop
```

## Free credits

Signing in with MaddLabs (`codo login maddlabs`) gives a new account a 14 day trial with
2 million free tokens per day on models hosted in the EU. Terms:
[maddlabs.co/legal/trial](https://maddlabs.co/legal/trial). After the trial you pay per token from a
prepaid balance at [maddlabs.co](https://maddlabs.co), or switch to your own key at any time.

## Connecting models

```bash
codo login openai                  # also: anthropic, xai, google, mistral, deepseek, groq, openrouter
codo login ollama                  # local models, no key
codo login endpoint http://localhost:8000/v1
codo accounts                      # list, add, remove, use
codo agents                        # Claude Code, Codex and Gemini CLI found on this computer
codo model                         # every model you can use right now
```

Models from your own accounts are written as `@account/model`, agents as `agent:claude`,
`agent:codex` and `agent:gemini`.

## Security

Codo edits files and runs commands in the folder you trust. Before the first session in a folder it
asks for consent and shows what is inside (git, number of files, `Codo.md`). Your home directory is
never remembered as trusted.

Three modes, switched with **Shift+Tab**:

| Mode | What the agent may do without asking |
| --- | --- |
| `read` | Read and search files only. Agents run in plan or read only mode. |
| `ask` (default) | Read freely. Edits, shell commands and installs ask for consent. |
| `auto` | Edit and run commands without asking. Agents get workspace write access. |

`--yes` gives consent in advance for one run. Tasks that arrive from the phone run in `ask` mode by default,
and slash commands or `!command` cannot be sent from the phone.

API keys are stored in `~/.config/doma/konta.json` with `0600` permissions. Plain `http` endpoints
are accepted only for localhost and the local network.

Found a security problem? See [SECURITY.md](SECURITY.md).

## Configuration

| Where | What |
| --- | --- |
| `Codo.md` in the project | Project memory, read at the start of every session (`/init` writes one) |
| `.codo/commands/NAME.md` | Your own slash commands for the project (`~/.config/doma/commands/` for all projects) |
| `~/.config/doma/settings.json` | Model, effort, language, trusted folders, marathon limits |
| `~/.config/doma/konta.json` | Connected API accounts |
| `CODO_LANG=en` or `/lang pl` | Interface language (English and Polish). Other codes such as `de`, `fr`, `ja` keep the English interface and make the agent answer in that language |
| `/effort` or `--effort` | How hard the agent thinks: low, medium, high, xhigh, max |

The configuration folder is called `doma` for compatibility with earlier versions.

## Development

Codo is one file, `codo`. Tests run without network access or model providers:

```bash
python3 -m py_compile codo
CODO_LANG=pl CODO_FILE=$PWD/codo python3 -m unittest discover -s tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md). The interface speaks English and Polish (`CODO_LANG`). Some code comments are in Polish;
English translations are welcome as pull requests.

## License

Apache License 2.0, see [LICENSE](LICENSE) and [NOTICE](NOTICE). Codo is made by MADD in Poland.
Claude Code, Codex and Gemini CLI are products of their respective owners and are used through their
own command line tools and your own plans.
