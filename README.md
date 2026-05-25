<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/mohamed-elkholy95/Pythinker-ai@main/webui/public/brand/icon.svg" alt="Pythinker" width="180">
</p>

<h1 align="center"> Pythinker</h1>

<div align="center">
  <p>
    <a href="https://pypi.org/project/pythinker-ai/"><img src="https://img.shields.io/pypi/v/pythinker-ai?cacheSeconds=300" alt="PyPI"></a>
    <a href="https://pepy.tech/projects/pythinker-ai"><img src="https://img.shields.io/pepy/dt/pythinker-ai?label=downloads&color=%2312b76a&cacheSeconds=600" alt="Downloads"></a>
    <img src="https://img.shields.io/badge/python-%E2%89%A53.11-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-MIT-green" alt="License">
  </p>
</div>

🤖 **Pythinker** is an open-source tiny agent framework. It keeps the core agent loop compact and readable while still supporting chat channels, long-term memory, MCP, and practical deployment paths — so you can go from local setup to a long-running personal agent with minimal overhead.

> Powered by a tiny, multiplexing agent loop: one Python process listens to Slack, Telegram, Discord, WhatsApp, Matrix, MS Teams, email, a WebSocket WebUI, and an OpenAI-compatible HTTP API — all backed by a single session-scoped memory layer.

> **What's new in 2.6.0** — New **Signal channel** (signal-cli HTTP/SSE) with full DM and group support. New **DM pairing system**: first-time senders receive a one-time code; owner approves via `/pairing approve`. Channel modules now load lazily (only enabled channels import their SDKs at startup), and the OpenAI-compatible provider client initializes on first use (~700 ms cold-start savings). `AnthropicProvider` transparently retries long requests via streaming. Shell tool detaches stdin so interactive prompts no longer block turns. See the [changelog](CHANGELOG.md) for details.

## 💡 Key Features

- **Tiny agent** — a compact readable core. Stable long-running behavior without orchestration sprawl.
- **Channel-agnostic** — Slack, Telegram, Discord, WhatsApp, Matrix, MS Teams, email, WebSocket, plus an OpenAI-compatible HTTP API.
- **Full-screen TUI** — `pythinker-ai tui` (alias `chat`) opens a `prompt_toolkit` chat with live streaming, slash-command pickers (`/model`, `/provider`, `/sessions`, `/theme`, `/help`, `/status`), fuzzy search, themable chrome (default + monochrome), and Ctrl+C cancellation of in-flight turns.
- **Provider-rich** — 25+ LLM providers (Anthropic, OpenAI, Azure OpenAI, OpenAI Codex, GitHub Copilot, Qwen/DashScope, MiniMax, VolcEngine, Moonshot, DeepSeek, StepFun, and more) behind a single interface.
- **Provider hot-reload** — edits to model / provider / API key in `~/.pythinker-ai/config.json` land at the next turn boundary. No restart of the SDK or gateway. Same-signature snapshots short-circuit; broken configs are logged and swallowed so an in-flight session can't crash on a typo.
- **Headless browser tool** *(opt-in)* — drives Playwright-managed Chromium for JavaScript-rendered pages, click/form flows, screenshots, and DOM snapshots. `mode="auto"` launches a packaged headless Chromium without Docker; `mode="cdp"` connects to an external service for hardened deployments. First-use Chromium binary installs lazily, with idle eviction, per-context page caps, SSRF route handling, and turn-boundary hot reload of browser config.
- **Governed-execution runtime** *(off by default)* — opt-in `RuntimeConfig` wires a `PolicyService` (allow-lists from agent manifests, per-turn budgets, recursion depth), a `ToolEgressGateway` chokepoint, an `AgentRegistry` directory loader, `RequestContext` + `BudgetCounters` plumbing, and a pluggable `TelemetrySink` (loguru / JSONL / composite). When the loader is `None` and policy is off, the runtime is bit-for-bit identical to the legacy path.
- **Autonomous subagent tracking** — spawned subagents are first-class task records with durable output under `.pythinker-ai/task-results/`. Pick a role at spawn time — `coder` (full tools), `explore` (read-only navigation), or `plan` (planning-only, no write/edit/shell) — and use `/tasks`, `/task-output <task_id>`, and `/task-stop <task_id>` to inspect or stop background work from chat.
- **Memory that learns** — a two-phase "Dream" process consolidates long-term memory into `MEMORY.md` / `SOUL.md` / `USER.md`, auto-versioned with pure-Python git.
- **Skills & MCP** — bundled skills (GitHub, cron, weather, tmux, summarize, skill-creator, …) plus first-class [Model Context Protocol](https://modelcontextprotocol.io/) tool access with defensive HTTP probing and provider-safe tool names.
- **Research-grade PDF reports** — opt-in `make_pdf` tool renders structured Markdown to a styled PDF via ReportLab (`pip install 'pythinker-ai[reports]'`).
- **Safer channel ingress** — chat/email adapters apply `allowFrom` before costly side effects like media downloads, attachment extraction, or voice transcription; Matrix also drops replayed pre-startup events.
- **Sandboxed shell** — every command is wrapped in a bubblewrap sandbox on Linux; file tools enforce workspace boundaries.
- **Hackable** — the Python package is ~58k LOC with zero monolithic orchestration layer. Read it, fork it, extend it.

## 📦 Install

Pythinker ships **native installers for every platform** alongside the PyPI
wheel. Pick the row that matches your OS — no Python, Node, or `uv` prerequisite
for the native paths.

> ✅ **Status note (May 2026):** native installers are now the canonical path
> for new installs. The short URLs below always resolve to the latest GitHub
> Release artifact, verify its `.sha256` sidecar, and install `pythinker-ai`.

| Platform | One-line install | Artifact |
|---|---|---|
| 🪟 **Windows** | `irm https://pythinker.com/ai.ps1 \| iex` | `PythinkerSetup-<version>.exe` |
| 🍎 / 🐧 **macOS / Linux** | `curl -fsSL https://pythinker.com/ai \| bash` | native tarball |
| 🍎 **macOS (Homebrew)** | `brew install mohamed-elkholy95/pythinker/pythinker-ai` | Homebrew tap |
| 🐧 **Linux packages** | `.deb` / `.rpm` from [Releases](https://github.com/mohamed-elkholy95/Pythinker/releases/latest) | system package |
| 🐍 **Python fallback** | `pip install pythinker-ai` | [PyPI](https://pypi.org/project/pythinker-ai/) |

Every artifact ships with a matching `.sha256` file — verify before install on
any platform with `sha256sum`, `shasum -a 256`, or `Get-FileHash`.

After install, on any OS:

```bash
pythinker-ai --version                # confirm install
pythinker-ai onboard                  # interactive setup wizard
pythinker-ai                          # start the interactive CLI
```

> **In-app updates** — `pythinker-ai update` queries the GitHub Releases API and
> re-runs the right installer for your build with SHA-256 verification. Set
> `PYTHINKER_AI_CLI_NO_AUTO_UPDATE=1` to disable the proactive startup check.

### 🪟 Windows — native installer

The short PowerShell installer downloads the latest `PythinkerSetup-<version>.exe`,
verifies its `.sha256` sidecar, and runs the Inno Setup installer silently.
It installs per-user into `%LOCALAPPDATA%\Programs\Pythinker`, registers
`pythinker-ai` on your user PATH (`HKCU\Environment`), broadcasts
`WM_SETTINGCHANGE` so new shells see the change, and does not require UAC.

```powershell
irm https://pythinker.com/ai.ps1 | iex
pythinker-ai --version
```

For a pinned version or an IT-managed per-machine install, download the script
first and pass flags:

```powershell
irm https://pythinker.com/ai.ps1 -OutFile install.ps1
powershell -ExecutionPolicy Bypass -File .\install.ps1 -Version 2.7.1
powershell -ExecutionPolicy Bypass -File .\install.ps1 -AllUsers
```

Manual `.exe` downloads from [Releases](https://github.com/mohamed-elkholy95/Pythinker/releases/latest)
still work; verify them with `Get-FileHash` before running.

**Upgrade:** `pythinker-ai update` from inside the running app — it downloads
the newest installer, verifies SHA-256, and re-runs it silently
(`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART`).

**Uninstall:** Apps & Features → *Pythinker* → Uninstall reverts both the
files and the PATH edit.

> 🛡 **First-launch SmartScreen warning** — until the Authenticode cert is
> provisioned in CI, the installer ships unsigned and Windows shows
> *"Windows protected your PC."* Click **More info → Run anyway**. Use the
> published `.sha256` as your integrity check until signing comes online.

### 🍎 macOS — Homebrew tap

```bash
# 1. Install — always pulls the newest pythinker-ai release on PyPI
brew install mohamed-elkholy95/pythinker/pythinker-ai

# 2. Verify
pythinker-ai --version
which pythinker-ai       # -> /opt/homebrew/bin/pythinker-ai (Apple Silicon)
                         #    or /usr/local/bin/pythinker-ai (Intel)
```

Works on **Apple Silicon and Intel** — brew picks the right Python build for
you. The formula provisions a clean venv and installs `pythinker-ai`
unpinned, so every fresh `brew install` resolves the newest release on PyPI;
the tap also auto-republishes its `url`/`sha256` block on every Pythinker
release so `brew info` reflects the current version.

**Upgrade:** `brew upgrade pythinker-ai` works once the tap has refreshed
for the new release. To pick up a PyPI point release immediately (between
tap refreshes), `brew reinstall pythinker-ai`.

**Uninstall:** `brew uninstall pythinker-ai && brew untap mohamed-elkholy95/pythinker`.

> The tap repo is [mohamed-elkholy95/homebrew-pythinker](https://github.com/mohamed-elkholy95/homebrew-pythinker) — auto-maintained, do not hand-edit.

### 🐧 Linux — system packages

Native `.deb` and `.rpm` packages for both `x86_64` and `aarch64` are attached
to every GitHub Release.

```bash
# Debian / Ubuntu (x86_64)
sudo dpkg -i pythinker-ai_2.7.1_amd64.deb
sudo apt-get install -f       # only if dpkg reports missing deps

# Debian / Ubuntu (ARM64)
sudo dpkg -i pythinker-ai_2.7.1_arm64.deb

# Fedora / RHEL / openSUSE (x86_64)
sudo rpm -i pythinker-ai-2.7.1.x86_64.rpm
# or use the package manager (preferred — handles deps):
sudo dnf install ./pythinker-ai-2.7.1.x86_64.rpm
sudo zypper install ./pythinker-ai-2.7.1.x86_64.rpm

# Fedora / RHEL (aarch64)
sudo rpm -i pythinker-ai-2.7.1.aarch64.rpm
```

Both packages drop a small `/usr/bin/pythinker-ai` launcher that execs the real
binary under `/usr/lib/pythinker/`, so your `$PATH` stays tidy.

**Verify before install:**

```bash
sha256sum -c pythinker-ai_2.7.1_amd64.deb.sha256        # Debian/Ubuntu
sha256sum -c pythinker-ai-2.7.1.x86_64.rpm.sha256       # Fedora/RHEL
```

**Upgrade:** download the new `.deb`/`.rpm` from Releases and `dpkg -i` /
`dnf install` over it. Or run `pythinker-ai update` from inside the running app —
it'll fetch the matching new package and prompt for sudo to install.

**Uninstall:**

```bash
sudo dpkg -r pythinker-ai                                # Debian/Ubuntu
sudo rpm -e pythinker-ai                                 # Fedora/RHEL
```

### 🌐 macOS / Linux — curl-bash native installer

For containers, fresh VMs, or any host without a system package manager. The
[install-native.sh](./scripts/install-native.sh) helper detects your OS + arch,
downloads the matching PyInstaller-frozen tarball, verifies its SHA-256, and
lands the single binary at `~/.local/bin/pythinker-ai`.

```bash
# Latest release
curl -fsSL https://pythinker.com/ai | bash

# Pin a specific version
curl -fsSL https://pythinker.com/ai | bash -s -- --version 2.7.1

# Custom prefix (defaults to $HOME/.local)
curl -fsSL https://pythinker.com/ai | bash -s -- --prefix /opt/pythinker
```

Supported targets:

| `uname -s / -m`             | Tarball asset                                            |
|---|---|
| Linux / x86_64              | `pythinker-<version>-x86_64-unknown-linux-gnu.tar.gz`    |
| Linux / aarch64             | `pythinker-<version>-aarch64-unknown-linux-gnu.tar.gz`   |
| Darwin / arm64              | `pythinker-<version>-aarch64-apple-darwin.tar.gz`        |

The script prints PATH guidance if `~/.local/bin` isn't already on your `$PATH`.
Intel macOS users — use Homebrew or `pip install pythinker-ai`; no
PyInstaller-built Intel Darwin binary is published.

**Uninstall:** `rm ~/.local/bin/pythinker-ai`.

### 🛠 Power-user / legacy install paths

> 🚧 **Deprecated.** These paths still work, but the per-OS native installers
> above are the canonical install method for **all new releases**. The legacy
> options below remain for existing automation; new tooling, examples, and
> support docs target the native installers exclusively.

<details>
<summary>Legacy uv / pipx / pip / source paths</summary>

```bash
# uv (one-off run)
uvx pythinker-ai

# uv tool install (isolated env)
uv tool install pythinker-ai

# pipx (equivalent to uv tool install, slower):
pipx install pythinker-ai

# Plain pip (last resort — you may need to add ~/.local/bin to PATH):
pip install --user pythinker-ai

# From source (contributors only):
git clone git@github.com:mohamed-elkholy95/Pythinker.git
cd Pythinker && uv sync --all-extras
```

If `pythinker-ai` isn't found after install, run `pythinker-ai doctor` (via
`python -m pythinker doctor` if needed) for diagnostics.

The legacy `scripts/install.sh` and `scripts/install.ps1` wrappers print a
deprecation banner; set `PYTHINKER_AI_INSTALL_QUIET_DEPRECATION=1` to silence it.

</details>

### 3. Optional extras

Pythinker ships with the Python browser automation library needed by the
`browser` tool. Optional extras are for add-on channels and heavier document
features:

```bash
uv tool install 'pythinker-ai[reports]'   # Markdown → PDF reports (research/report deliverables)
uv tool install 'pythinker-ai[matrix]'    # Matrix channel (E2E messaging)
uv tool install 'pythinker-ai[discord]'   # Discord channel
uv tool install 'pythinker-ai[msteams]'   # Microsoft Teams channel
uv tool install 'pythinker-ai[pdf]'       # Read PDF files (PyMuPDF)
uv tool install 'pythinker-ai[api]'       # OpenAI-compatible HTTP server
# Combine: uv tool install 'pythinker-ai[reports,discord,api]'
```

The historical `pythinker-ai[browser]` extra is still accepted as a
compatibility alias, but it no longer adds packages. Enable the browser tool in
config with `tools.web.browser.enable=true`; the managed Chromium binary is
installed lazily on first browser use when allowed, or explicitly with
`python -m playwright install chromium`.

### 4. Install / pin a specific version

`pythinker-ai` follows [SemVer](https://semver.org/) — major-version
upgrades **are not** auto-installed. To pin or to opt into a major bump,
use the explicit pin form for your install method:

| Goal | Command |
|---|---|
| Pin exactly `2.0.0` (uv tool — recommended) | `uv tool install --reinstall "pythinker-ai==2.0.0"` |
| Pin exactly `2.0.0` (pipx) | `pipx install --force "pythinker-ai==2.0.0"` |
| Pin exactly `2.0.0` (plain pip) | `python -m pip install --force-reinstall "pythinker-ai==2.0.0"` |
| Stay at the latest stable release | `pythinker-ai upgrade` |
| From inside pythinker, target a specific version | `pythinker-ai update --target 2.0.0 -y` |

`pip install -U pythinker-ai==2.0.0` works too, but it's semantically
noisy: the **exact pin** controls the version, not `-U`. `pythinker
upgrade` will refuse to cross a major version (e.g. `1.x → 2.x`)
without an explicit `pythinker-ai update --target` opt-in.

## 🚀 Quick Start

```bash
pythinker-ai onboard                           # write a config at ~/.pythinker-ai/config.json
pythinker-ai provider login openai-codex       # OAuth sign-in (the default provider)
pythinker-ai agent                             # interactive CLI chat
pythinker-ai tui                               # full-screen interactive chat (alias: chat)
```

`pythinker-ai onboard` ships a config preconfigured for **OpenAI Codex via ChatGPT OAuth** (no API key needed). To use a different provider/model, edit `~/.pythinker-ai/config.json` — see [Configuration](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/configuration.md) for the full catalog of 25+ providers.

Want several independent agents on one host? `pythinker agents` lays out per-agent configs under `~/.pythinker-ai/agents/<name>/` with isolated workspace, history, and memory; pass `--agent <name>` to any subcommand to target one.

- Want different LLM providers, web search, MCP, security settings, or more config options? See [Configuration](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/configuration.md).
- Want to run Pythinker in chat apps like Telegram, Discord, Slack, WhatsApp, or Matrix? See [Chat Apps](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/chat-apps.md).
- Want Docker or Linux service deployment? See [Deployment](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/deployment.md).
- Want governed-execution (policy allow-lists, budgets, telemetry) for hardened deployments? See [Architecture §5.X — `pythinker/runtime/`](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/ARCHITECTURE.md). The layer is opt-in via `runtime.policyEnabled` in `config.json`.

## 🧠 Agent Runtime Controls

Pythinker can launch subagents for background coding, research, and maintenance work. The runtime now tracks those subagents as autonomous tasks instead of relying on chat text alone.

| Command | What it does |
|---|---|
| `/tasks` | List active and recent autonomous tasks for the current session |
| `/task-output <task_id>` | Show the latest bounded output tail for a task |
| `/task-stop <task_id>` | Cancel a running subagent by id |

Task output is written to `.pythinker-ai/task-results/`, so large results do not flood the conversation and recovered output can still be inspected after a process restart. In-memory records are session-scoped; restart-recovered orphan output is workspace-wide by design for Pythinker's single-user/local deployment model.

## 🖥️ TUI

`pythinker-ai tui` (alias `pythinker-ai chat`) opens a full-screen `prompt_toolkit` interface for interactive sessions — a step up from `pythinker-ai agent`'s line-by-line REPL.

```bash
pythinker-ai tui                               # opens with the default theme
pythinker-ai tui --theme monochrome            # high-contrast / accessibility-friendly
pythinker-ai tui --workspace ~/work/agent      # override per-session workspace
pythinker-ai tui --logs ~/.pythinker-ai/tui.log   # mirror loguru output to a file
```

**Layout.** A persistent chat pane (streamed assistant tokens render live with markdown swap-in once the turn ends), a status bar showing session/model/provider/iteration count, a hint footer for the current keymap, and a multiline editor with slash-command autocomplete.

**Slash commands.** Open in-app overlays for everything you'd normally configure on the CLI:

| Command | Opens |
|---|---|
| `/help` | Built-in cheat sheet |
| `/status` | Live snapshot — session key, model, provider, message count, recent activity |
| `/sessions` | Fuzzy-pick from past sessions and resume |
| `/model` | Fuzzy-pick a model from the active provider |
| `/provider` | Switch LLM provider |
| `/theme` | Swap between `default` and `monochrome` themes (persisted to `cli.tui.theme`) |
| `/mcp` | Show MCP status — configured servers, connected servers, registered tools; `/mcp reconnect` reloads MCP config and reconnects |
| `/login` / `/logout` | OAuth sign-in / sign-out for providers like OpenAI Codex and GitHub Copilot, with in-terminal prompts |
| `/init` | Generate a tuned `AGENTS.md` for the current workspace from the bundled template |
| `/clear` | Clear the chat pane (`/clear --hard` also wipes session memory) |
| `/exit` | Quit |

Pickers support fuzzy search — start typing to filter, ↑/↓ to navigate, Enter to commit, Esc to dismiss.

**Keymap.**

| Key | Action |
|---|---|
| `Enter` | Submit message |
| `Ctrl+J` | Newline inside the editor |
| `Ctrl+C` | Cancel the in-flight turn (or quit when idle) |
| `Esc` | Close the active overlay / picker |
| `↑` / `↓` | Move cursor in pickers; PageUp / PageDown for 5-step jumps |

**Theming.** Two themes ship by default. Set `cli.tui.theme` in `~/.pythinker-ai/config.json` or pass `--theme`. Both themes provide separate prompt_toolkit chrome styles and Rich content styles so the chat panel and the surrounding UI stay visually consistent.

## 🧪 WebUI (Development)

> [!NOTE]
> The WebUI development workflow currently requires a source checkout and is not yet shipped together with the official packaged release. See the [WebUI README](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/webui/README.md) for full WebUI development docs and build steps.

**1. Enable the WebSocket channel in `~/.pythinker-ai/config.json`**

```json
{ "channels": { "websocket": { "enabled": true } } }
```

**2. Start the gateway**

```bash
pythinker-ai gateway
```

**3. Start the WebUI dev server**

```bash
cd webui
bun install
bun run dev
```

## 🏗️ Architecture

<p align="center">
  <img src="https://cdn.jsdelivr.net/gh/mohamed-elkholy95/Pythinker-ai@main/webui/public/brand/arctecture.webp" alt="Pythinker architecture" width="800">
</p>

🤖 Pythinker stays tiny by centering everything around a tiny agent loop: messages come in from chat apps, the LLM decides when tools are needed, and memory or skills are pulled in only as context instead of becoming a heavy orchestration layer. That keeps the core path readable and easy to extend, while still letting you add channels, tools, memory, and deployment options without turning the system into a monolith.

See [`docs/ARCHITECTURE.md`](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/ARCHITECTURE.md) for a forensic walkthrough of the runtime.

## ✨ Features

<table align="center">
  <tr align="center">
    <th><p align="center">📈 24/7 Real-Time Market Analysis</p></th>
    <th><p align="center">🚀 Full-Stack Software Engineer</p></th>
    <th><p align="center">📅 Smart Daily Routine Manager</p></th>
    <th><p align="center">📚 Personal Knowledge Assistant</p></th>
  </tr>
  <tr>
    <td align="center">Discovery • Insights • Trends</td>
    <td align="center">Develop • Deploy • Scale</td>
    <td align="center">Schedule • Automate • Organize</td>
    <td align="center">Learn • Memory • Reasoning</td>
  </tr>
</table>

## 📚 Docs

Browse the [repo docs](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/README.md) for the current GitHub development version.

- Talk to Pythinker from familiar chat apps: [Chat Apps](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/chat-apps.md)
- Configure providers, web search, MCP, and runtime behavior: [Configuration](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/configuration.md)
- Integrate Pythinker with local tools and automations: [OpenAI-Compatible API](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/openai-api.md) · [Python SDK](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/python-sdk.md)
- Run Pythinker with Docker or as a Linux service: [Deployment](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/deployment.md)
- Deeper dives: [Architecture](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/ARCHITECTURE.md) · [Memory](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/memory.md) · [Multiple Instances](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/multiple-instances.md) · [Channel Plugin Guide](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/docs/channel-plugin-guide.md)

## 🤝 Contribute & Roadmap

PRs welcome! The codebase is intentionally small and readable. 🤗

### Branching Strategy

| Branch | Purpose |
|--------|---------|
| `main` | Stable releases — bug fixes and minor improvements |
| `dev` | Experimental features — new features and breaking changes |

**Unsure which branch to target?** See [CONTRIBUTING.md](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/CONTRIBUTING.md) for details.

**Releases** — When publishing a new version, keep the README “What's new” callout and [CHANGELOG.md](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/CHANGELOG.md) section in sync with the exact release version.

**Roadmap** — Pick an item and [open a PR](https://github.com/mohamed-elkholy95/Pythinker-ai/pulls)!

- **Multi-modal** — See and hear (images, voice, video)
- **Long-term memory** — Never forget important context
- **Better reasoning** — Multi-step planning and reflection
- **More integrations** — Calendar and more
- **Self-improvement** — Learn from feedback and mistakes

## 🔐 Security

Found a vulnerability? Please **do not open a public issue**. Follow the private disclosure process in [`SECURITY.md`](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/SECURITY.md).

## 📄 License

Pythinker is released under the [MIT License](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/LICENSE). Third-party components redistributed with the project are listed in [`THIRD_PARTY_NOTICES.md`](https://github.com/mohamed-elkholy95/Pythinker-ai/blob/main/THIRD_PARTY_NOTICES.md).

<p align="center">
  <em>Thanks for visiting ✨ Pythinker!</em>
</p>

<p align="center">
  <img src="https://visitor-badge.laobi.icu/badge?page_id=mohamed-elkholy95.Pythinker-ai" alt="Visitors">
</p>
