# Changelog

## 0.32.3

- **Role badges in every language.** Researcher and Reviewer badges next to agents use the full translated name (for example "Badacz" and "Recenzent" in Polish) instead of the English short word.
- **Teams in progress.** The stack of member faces with "+N" no longer overlaps the team title.

## 0.32.2

- **Windows fixes.** File search, grep and @ completion return relative paths with forward slashes, also when the working folder has a short 8.3 name. app-server and mcp read stdin as UTF-8. Claude Code and Codex installed through npm get multi-line arguments in full (no more .cmd shims). Team member logs are UTF-8.
- **app-server exits after its input closes**, even when nobody reads its output any more (at most 10 s, `CODO_APP_EXIT_GRACE`).
- **Team members resume their own conversation** after the supervisor is killed.
- **The window starts at once** instead of waiting about 18 s for a reverse DNS lookup.
- **Tests green on Windows, Linux and macOS** in CI: 495 tests on every push to main.

## 0.32.1

- **Office documents as text.** Edits to Word, Excel, PowerPoint and OpenDocument files show a real text diff in the conversation card and in the Changes panel, with a format badge. Accept, reject and undo work on the whole file. File preview shows the document with headings, tables, sheets and slides.
- **Plurals everywhere.** "1 check failed", "2 checks failed" and about 30 other counts follow the rules of each language, including the Polish, Czech, Ukrainian and Romanian forms.

## 0.32.0

### Word, Excel and PowerPoint edits, reviews and pull request checks, Windows fixes

- **The agent edits documents in place.** New `office_edit`: replace text in Word without losing formatting (even across runs, headers and footers), add or delete paragraphs and headings, edit table cells and rows; set values and formulas in Excel cells and ranges, add rows and sheets with styles kept; replace text on PowerPoint slides, write speaker notes, add a slide from a layout; replace text in ODT and ODS. Several edits at once, all or nothing, with a diff before saving, a backup and `/undo`. Reading PowerPoint no longer drops the first slide.
- **Review card in the conversation.** Findings marked important or minor, with "Fix this" and "Apply all fixes", and file:line links that open the Changes panel on that line.
- **Pull request checks.** The window follows the checks every 30 seconds, shows failures first, sends failed logs to the agent with "Fix now", can fix failing checks on its own and merge when everything passes.
- **HTML preview** in the Changes panel, sandboxed.
- **Tested on real Windows.** `codo ui` started from another program no longer stops on the trust question, short 8.3 paths are expanded, git and gh output is read as UTF-8, files held by another program are saved in place or explained, case only renames work, and the Changes panel respects `core.autocrlf`. Windows window, NTFS and Edge checks now run in CI.

### Fixes

- A new binary file shows "new · PDF · 12 KB" instead of "+1 −0".
- Sign in: the eyes follow what you type, and the disabled button is readable in dark mode.

## 0.31.0

### Working with files and on files

- **Files in the conversation.** Attach files, whole folders, a pasted image or a screenshot; drop anything anywhere on the window. Attachment cards show a thumbnail or the file type and size. Type `@` for a list of project files and folders right at the cursor, with fuzzy search. Windows paths, spaces and accents work.
- **Files in answers are links.** Paths the agent mentions open a preview: code with colours, Markdown, HTML, images, PDF, video. Open in the default app, show in folder, copy the path or download. Files the agent made appear as cards under its answer.
- **A new Changes panel.** A list or a tree of changed files, unified or side by side diffs with syntax colours, folded unchanged lines and smooth large files. Accept, reject or undo one hunk, a whole file or everything, always with a backup and earlier versions to restore. Comments on lines go back to the agent as one fix. Git: branch, commit, pull request. Keyboard shortcuts (press `?`).
- **The agent handles files better.** UTF-16, cp1250 and BOM files are read and written back byte for byte, Windows line endings stay. Edits land even with a different indent or typographic quotes, and a miss shows the closest lines. `read_file` reads PDF, DOCX, XLSX, PPTX, ODF and notebooks, and shows images to models that see. Every `/undo` steps back one change, including moves, copies and deletes. Read only files are no longer overwritten; files outside the project need your OK.

## 0.30.5

### Sign in, live agent faces and every provider logo on Windows and Linux

- **Sign in on first start, like on Mac.** Codo opens on a full window sign in to your DomaAI account: email, a 6 digit code from your inbox (two step codes and backup codes too), new terms, your first name for a new account. Then "How will you use Codo?" (just me or for a company) and the agent creator. The same account as `codo login`.
- **Agent faces drawn live.** The glass, the liquid and the eyes are rendered in the window with the same shader as on Mac. Up to five colours mix inside, the eye colour changes, faces blink, look around and react. Every change in the creator shows at once, and every list shows each agent's real colours and eyes.
- **Every provider logo.** One way to tell the maker of a model for the whole window: Mistral, Kimi, GLM, Llama, Bielik, Seed, Groq, OpenRouter, Ollama, LM Studio and models without a prefix (`gpt-5`, `codestral`, `gemini-2.5`). 40 logos, no network.
- **The window matches the Mac app 1:1.** Accounts on the bar, title bar, projects and the start screen.

### Fixes

- In the creator, the first tap on a colour cleared the liquid instead of adding the colour.

## 0.30.3

### Rooms and Compare on Windows and Linux

- **Rooms.** Shared threads with several of your persistent agents. Write without a name and the lead answers, `@Name` calls one agent, `@all` everyone, and an agent that names another brings it in. Rooms live in `codo host`, so agents keep talking with the window closed, within the same limits as on Mac (6 steps without you, 60 messages an hour). Same `agent-rooms.json` as Codo for Mac.
- **Compare models.** Pick two to four models in the model picker and send one message: each answers in its own card, read only, side by side. Continue with the one you like.
- **Earlier team runs** come back after a restart, and you can join a running team again.
- **Real provider logos** everywhere in the window, the same as on Mac.

### Fixes

- The switch to the backup brain is announced in English too.
- Group lists read "Max, Josh and Mia".
- Team budgets use the 𝔻 credit sign, and the status after a pull request says so.

## 0.30.2

### Model picker, teams and groups in the Windows and Linux app

- **Model picker like on Mac.** Providers with their logos, model families, search across every provider, a card for agents on this computer (Claude Code, Codex) and the backup brain that finishes a turn when a plan runs out.
- **Agent teams in the window.** Pick a team template in the model picker and send your task: the lead asks its questions, you approve the plan, follow every member live, then merge, keep a branch or open a pull request.
- **Groups.** Create a group from a ready team or your own agents, pick how it works (conversation, side by side, split, cross review, vote, pipeline), set limits and talk to everyone at once with `@mentions`. Earlier runs come back after a restart.
- **18 languages, done.** Czech, Danish, Spanish, French, Hungarian, Italian, Japanese, Korean, Dutch, Portuguese, Romanian, Swedish, Turkish and Chinese now have every window text, and say "this computer" instead of "this Mac".

### Fixes

- A group's "at once per provider" setting was lost on every save.
- The window showed `agent:claude` instead of Claude Code before the model list loaded.

## 0.30.1

### Bots and agents work with the window closed

- Swarms run on their own schedule (hourly, daily, on weekdays, weekly) through `codo host`. Results go to the inbox and to your connected channels.
- Bots and persistent agents wake up when something happens: a folder changes, a pull request gets a failed check or a new comment, a new e-mail arrives, or a webhook is called (a local address with its own secret key). Set it up under "Also wakes it" in the bot or agent settings.
- Work you delegate now reports back to the channels you picked.

### Office

- Open Word, PowerPoint and Excel files as new Office files, and attach PDF, DOCX, PPTX and XLSX files as sources for Codo.
- Export slides and designs as PNG. Pictures now end up in exported Word files.
- "Show in folder" opens the Office folder in Explorer or your file manager.

### Fixes

- Several screens could stay visible behind another one after switching.
- German and Ukrainian: no more "Mac" and English sentences; weekday names follow the window language.
- Narrow windows (1000 px) no longer cut cards and buttons.
- Polish texts in Office were partly in English in 0.30.0.
- A crafted document could write a picture outside the Office media folder.

## 0.30.0

### The full Codo app on Windows and Linux

`codo ui` (and **Codo** in the Start menu) now opens the same app as Codo for Mac, screen for screen:

- **Code**: tabs, the sidebar with chats and your persistent agents, the greeting with your agent, the composer with files (+, drag and drop, paste), @ mentions, Files and Chat, the permission mode, your balance and the model, and the Changes panel with live diffs.
- **Office**: presentations, documents and spreadsheets with the editor, live writing and export to PowerPoint, Word, Excel, CSV, Markdown and HTML (PDF through print).
- **Bots**: describe a bot in your own words, ready characters and tasks, swarms on a canvas, results and approvals, and channels: Telegram, Discord, Slack, Signal and e-mail.
- **Workflows**: steps, checks and loops on a canvas, ready templates and runs you can watch.
- **Delegate**: say what to do, who takes it, where, when and where the result goes.
- **Persistent agents**: the "Meet your agent" creator and a conversation with each agent, with its own settings, memory and schedule. They keep working in the background through `codo host`, on Windows too (over a local connection with a token).
- **Settings**: your agent, skills, tools, LogBot, accounts, 38 connections, cloud computer, appearance (light, dark, 18 languages), limits and quiet hours, privacy and updates.

Bots, swarms and agents use the same `~/.config/doma/hive.json` as Codo for Mac, so they move between computers as they are.

Not yet on Windows and Linux: iMessage and Mac notifications, swarms on a schedule, bot triggers (file, webhook, mail) and importing DOCX and PPTX into Office.

## 0.29.3

### Codo updates itself

- Once a day Codo checks for a new version and, if there is one, downloads it in the background, checks its SHA-256 and replaces itself. The new version runs from the next start, and Codo tells you it updated.
- Works for the script install (`install.sh`, `install.ps1`) and for the single files and the Windows installer, which fetch their own file from `SHA256SUMS`.
- `codo update` on a single file (for example `codo.exe`) no longer overwrites the program with the Python script.
- Turn it off with `codo update --auto off` (on again with `--auto on`) or `CODO_NO_AUTO_UPDATE=1`. The Mac app updates its engine itself.

## 0.29.2

### Codo in its own window on Windows and Linux

- `codo ui` now opens Codo as an app window (Microsoft Edge on Windows, Edge, Chrome or Chromium on Linux) with its own icon on the taskbar, instead of a browser tab. `codo ui --tab` keeps the old behaviour. If no such browser is found, Codo opens in your default browser as before.
- Windows installer: **Codo** in the Start menu opens the app window in `~/Codo`, **Codo Terminal** opens the agent in a terminal.
- `codo okno` (also `codo window`) starts the app window the same way as the Start menu shortcut.
- The PowerShell install (`irm …/install.ps1 | iex`) also adds **Codo** to the Start menu.
- The double click messages are now in English too.

## 0.29.1

### Windows

- New installer `CodoSetup-x64.exe`: installs for your user without administrator rights, adds `codo` to PATH, a Start menu shortcut (and an optional desktop one) that opens the Codo window in your browser, and a clean uninstaller.
- `codo.exe` has the Codo icon and file details.
- Double clicking `codo.exe` opens the Codo window in your browser in `~/Codo` instead of a console that closed at once.
- `codo link` on Windows wrote a broken autostart file and failed; the bridge now starts with Windows again.
- Single files (Windows, Linux, macOS) now restart themselves correctly: the browser window, teams, MCP and background work used to fail there.

### Everywhere

- With `CODO_LANG` set to one of 18 languages (for example `de`, `fr`, `ja`, `zh-Hans`) the agent answers in that language.
- README: how Codo works and everything it does in one place.

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
