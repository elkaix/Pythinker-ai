# Install and Quick Start

## Install

Use the native installer for your OS:

```bash
# macOS / Linux / WSL
curl -fsSL https://pythinker.com/ai | bash
```

```powershell
# Windows PowerShell
irm https://pythinker.com/ai.ps1 | iex
```

The native installers download the latest GitHub Release artifact, verify its
SHA-256 sidecar, install `pythinker-ai`, and put it on your `PATH`.

### Alternative installers

| Tool | Command | Notes |
|---|---|---|
| Homebrew | `brew install mohamed-elkholy95/pythinker/pythinker-ai` | macOS package-manager path. |
| `uv` | `uv tool install pythinker-ai` | Isolated Python tool install; useful for Python-first setups. |
| `pipx` | `pipx install pythinker-ai` | Equivalent to `uv tool install`, slower. Requires `pipx` from your OS package manager (`sudo dnf install pipx`, `sudo apt install pipx`, `brew install pipx`). |
| `pip --user` | `pip install --user pythinker-ai` | Not isolated. May need `~/.local/bin` on `PATH` manually. |
| Source | `git clone … && uv sync --all-extras` | For contributors — editable install. |

> [!WARNING]
> Don't run `pip install pythinker-ai` into system Python on Fedora 38+, Debian 12+, Ubuntu 23.04+, or Homebrew macOS. [PEP 668](https://peps.python.org/pep-0668/) blocks it by default, and the workarounds tend to break your system Python. Use the native installer or `uv tool install` instead.

### Update to latest version

```bash
pythinker-ai update
pythinker-ai --version
```

**Using WhatsApp?** Rebuild the local bridge after upgrading:

```bash
rm -rf ~/.pythinker-ai/bridge
pythinker-ai channels login whatsapp
```

### Verify install

```bash
pythinker-ai doctor
```

`doctor` checks Python version, install path + `PATH` membership, config validity, workspace writability, and OAuth token presence for your default provider. If anything is wrong, it prints the exact command to fix it. Run this first whenever something doesn't work.

## Quick Start

```bash
pythinker-ai onboard                           # guided setup; writes ~/.pythinker-ai/config.json
pythinker-ai tui                               # full-screen chat
```

That's it. `pythinker-ai onboard` walks through a visual terminal wizard: welcome/security notice, QuickStart vs Manual, provider/auth, model, workspace, optional channels, redacted review, and a post-save health check. QuickStart defaults to **OpenAI Codex via ChatGPT OAuth** when you choose that provider.

### Using a different provider or model?

Edit `~/.pythinker-ai/config.json`:

```json
{
  "agents": {
    "defaults": {
      "model": "openai-codex/gpt-5.5"
    }
  }
}
```

Provider is auto-detected from the model prefix (`openai-codex/…`, `anthropic/…`, `openrouter/…`, `deepseek/…`, etc.). For the full catalog of 25+ providers, required API keys, and model-specific options, see [`configuration.md`](./configuration.md). For web search, see the [web-search section](./configuration.md#web-search).

### Full-screen TUI chat

For a richer interactive experience, run `pythinker-ai tui` (alias
`pythinker-ai chat`). It opens a full-screen chat with slash-command
pickers for sessions, models, providers, and themes. The onboarding
success screen recommends this first. The CLI `pythinker-ai agent` remains
the right tool for one-shot prompts and scripts.

### Troubleshooting

- **`pythinker-ai` command not found** — run `python -m pythinker doctor` for a diagnosis; usually `~/.local/bin` isn't on your `PATH`. `uv tool update-shell` fixes it.
- **Anything else broken** — `pythinker-ai doctor` is the one-stop diagnostic. Paste its output in a GitHub issue if you need help.
