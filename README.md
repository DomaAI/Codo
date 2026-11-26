<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/agents-dark.png">
    <img src="assets/agents-light.png" alt="Codo and its agents: Josh, Luna, Codo, Max and Mia">
  </picture>
</p>

<h1 align="center">Codo</h1>

**One terminal agent on top of every model and coding agent you already pay for.**
Claude Code, Codex, Gemini CLI, 20+ ACP agents, any OpenAI compatible API or a local model:
Codo drives them all from one session, and when one hits its plan limit the same conversation
keeps going on the next one.

[![CI](https://github.com/DomaAI/codo/actions/workflows/ci.yml/badge.svg)](https://github.com/DomaAI/codo/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/DomaAI/codo)](https://github.com/DomaAI/codo/releases/latest)
[![License](https://img.shields.io/badge/license-Apache_2.0-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)
![Linux | macOS | Windows](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20windows-lightgrey)

```bash
curl -fsSL https://github.com/DomaAI/codo/releases/latest/download/install.sh | bash
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

## Install

**Linux and macOS**

```bash
curl -fsSL https://github.com/DomaAI/codo/releases/latest/download/install.sh | bash
```

**Windows (PowerShell)**

```powershell
irm https://github.com/DomaAI/codo/releases/latest/download/install.ps1 | iex
```

The installer downloads `codo` from the latest release, checks its SHA-256 sum against
`SHA256SUMS` and puts it in `~/.local/bin` (Windows: `%LOCALAPPDATA%\Codo\bin`). You can also download
`codo` from [Releases](https://github.com/DomaAI/codo/releases) and run it with `python3 codo`.

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

Every release also has ready to run files: `codo-windows-x64.exe`, `codo-linux-x64`, `codo-linux-arm64`, `codo-macos-arm64` (Apple Silicon) and `codo-macos-x64` (Intel). Download one from [Releases](https://github.com/DomaAI/codo/releases/latest), make it executable on macOS and Linux (`chmod +x`) and run it. The Mac app (Apple Silicon and Intel) is on [domaai.pl/pobierz-codo](https://domaai.pl/pobierz-codo.html).

## Codo for Mac

A native window on top of the same engine: terminal and preview browser in the window, bots and
swarms, always-on agents that answer on Telegram, Discord and iMessage, workflows on a schedule,
Gmail, Calendar and Drive, and Office documents. macOS 15 or newer, signed and notarized:
[download Codo.dmg](https://bymadd.pl/static/codo/mac/Codo.dmg).

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
| `CODO_LANG=en` or `/lang pl` | Interface language (English and Polish) |
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
