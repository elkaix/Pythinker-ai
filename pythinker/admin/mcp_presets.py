"""MCP preset catalog and safe setup helpers for admin surfaces."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pythinker.config.loader import load_config
from pythinker.config.paths import get_runtime_subdir
from pythinker.config.schema import MCPServerConfig
from pythinker.utils.helpers import ensure_dir

_PRESET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

FieldTarget = tuple[Literal["env", "header", "arg", "url_param"], str]


class McpPresetError(ValueError):
    """User-facing MCP preset failure."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass(frozen=True)
class McpPresetField:
    name: str
    label: str
    target: FieldTarget
    env_var: str = ""
    secret: bool = True
    required: bool = True
    placeholder: str = ""


@dataclass(frozen=True)
class McpPreset:
    name: str
    display_name: str
    category: str
    description: str
    transport: Literal["stdio", "sse", "streamableHttp"]
    server: MCPServerConfig
    fields: tuple[McpPresetField, ...] = ()
    requires: str = ""
    docs_url: str = ""
    brand_color: str = "#64748B"
    note: str = ""


MCP_PRESETS: tuple[McpPreset, ...] = (
    McpPreset(
        name="playwright",
        display_name="Playwright",
        category="browser",
        description="Automate and inspect local browsers through Playwright MCP.",
        docs_url="https://github.com/microsoft/playwright-mcp",
        transport="stdio",
        requires="Node.js and npx",
        brand_color="#2EAD33",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@playwright/mcp@latest"],
            tool_timeout=60,
        ),
    ),
    McpPreset(
        name="context7",
        display_name="Context7",
        category="docs",
        description="Fetch current library documentation and examples.",
        docs_url="https://context7.com/",
        transport="stdio",
        requires="Node.js and npx; optional CONTEXT7_API_KEY",
        brand_color="#111827",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@upstash/context7-mcp@latest"],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="context7_api_key",
                label="Context7 API key",
                target=("arg", "--api-key"),
                env_var="CONTEXT7_API_KEY",
                required=False,
                placeholder="ctx7_...",
            ),
        ),
    ),
    McpPreset(
        name="firecrawl",
        display_name="Firecrawl",
        category="web",
        description="Search, scrape, and crawl web pages through Firecrawl MCP.",
        docs_url="https://docs.firecrawl.dev/",
        transport="stdio",
        requires="Node.js, npx, and FIRECRAWL_API_KEY",
        brand_color="#FC5D3D",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "firecrawl-mcp"],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="firecrawl_api_key",
                label="Firecrawl API key",
                target=("env", "FIRECRAWL_API_KEY"),
                env_var="FIRECRAWL_API_KEY",
                placeholder="fc-...",
            ),
        ),
    ),
    McpPreset(
        name="github",
        display_name="GitHub",
        category="developer",
        description="Inspect repositories, issues, pull requests, and related GitHub data.",
        docs_url="https://github.com/github/github-mcp-server",
        transport="stdio",
        requires="Docker and GITHUB_PERSONAL_ACCESS_TOKEN",
        brand_color="#181717",
        server=MCPServerConfig(
            type="stdio",
            command="docker",
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "ghcr.io/github/github-mcp-server",
            ],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="github_token",
                label="GitHub token",
                target=("env", "GITHUB_PERSONAL_ACCESS_TOKEN"),
                env_var="GITHUB_PERSONAL_ACCESS_TOKEN",
                placeholder="ghp_...",
            ),
        ),
    ),
    McpPreset(
        name="microsoft-learn",
        display_name="Microsoft Learn",
        category="docs",
        description="Search Microsoft Learn documentation through its hosted MCP endpoint.",
        docs_url="https://learn.microsoft.com/",
        transport="streamableHttp",
        requires="Network access",
        brand_color="#0078D4",
        server=MCPServerConfig(
            type="streamableHttp",
            url="https://learn.microsoft.com/api/mcp",
            tool_timeout=60,
        ),
    ),
    McpPreset(
        name="brave-search",
        display_name="Brave Search",
        category="search",
        description="Search the web through Brave Search MCP.",
        docs_url="https://brave.com/search/api/",
        transport="stdio",
        requires="Node.js, npx, and BRAVE_API_KEY",
        brand_color="#FB542B",
        server=MCPServerConfig(
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-brave-search"],
            tool_timeout=60,
        ),
        fields=(
            McpPresetField(
                name="brave_api_key",
                label="Brave API key",
                target=("env", "BRAVE_API_KEY"),
                env_var="BRAVE_API_KEY",
                placeholder="BSA...",
            ),
        ),
    ),
)


def _preset_by_name(name: str) -> McpPreset:
    if _PRESET_NAME_RE.match(name or "") is None:
        raise McpPresetError("invalid MCP preset name")
    for preset in MCP_PRESETS:
        if preset.name == name:
            return preset
    raise McpPresetError("unknown MCP preset", status=404)


def _clone_server(server: MCPServerConfig) -> MCPServerConfig:
    return MCPServerConfig.model_validate(server.model_dump(mode="json"))


def _with_managed_stdio_cwd(name: str, cfg: MCPServerConfig) -> MCPServerConfig:
    if cfg.command and (cfg.type in (None, "stdio")) and not cfg.cwd:
        cfg.cwd = str(ensure_dir(get_runtime_subdir("mcp") / name))
    return cfg


def _arg_value(args: list[str], flag: str) -> str | None:
    prefix = f"{flag}="
    for index, item in enumerate(args):
        if item == flag and index + 1 < len(args):
            return args[index + 1]
        if item.startswith(prefix):
            return item[len(prefix) :]
    return None


def _with_arg_value(args: list[str], flag: str, value: str) -> list[str]:
    out: list[str] = []
    skip_next = False
    prefix = f"{flag}="
    for item in args:
        if skip_next:
            skip_next = False
            continue
        if item == flag:
            skip_next = True
            continue
        if item.startswith(prefix):
            continue
        out.append(item)
    out.extend([flag, value])
    return out


def _field_value(field: McpPresetField, cfg: MCPServerConfig | None) -> str | None:
    if cfg is None:
        return None
    target_kind, target_name = field.target
    if target_kind == "env":
        return cfg.env.get(target_name) or None
    if target_kind == "header":
        return cfg.headers.get(target_name) or None
    if target_kind == "arg":
        return _arg_value(list(cfg.args), target_name)
    if target_kind == "url_param" and cfg.url:
        from urllib.parse import parse_qs, urlsplit

        values = parse_qs(urlsplit(cfg.url).query).get(target_name)
        return values[0] if values else None
    return None


def _field_configured(field: McpPresetField, cfg: MCPServerConfig | None) -> bool:
    return bool(_field_value(field, cfg) or (field.env_var and os.environ.get(field.env_var)))


def _field_payload(field: McpPresetField, cfg: MCPServerConfig | None) -> dict[str, Any]:
    return {
        "name": field.name,
        "label": field.label,
        "secret": field.secret,
        "required": field.required,
        "configured": _field_configured(field, cfg),
        "placeholder": field.placeholder,
        "env_var": field.env_var,
    }


def _field_input(query: dict[str, list[str]], field: McpPresetField) -> str | None:
    values = query.get(field.name)
    if values:
        value = values[0].strip()
        if value:
            return value
    if field.env_var and os.environ.get(field.env_var):
        return f"${{{field.env_var}}}"
    return None


def materialize_preset(preset: McpPreset, query: dict[str, list[str]]) -> MCPServerConfig:
    cfg = _clone_server(preset.server)
    for field_spec in preset.fields:
        value = _field_input(query, field_spec)
        if field_spec.required and not value:
            raise McpPresetError(f"missing {field_spec.label}")
        if not value:
            continue
        target_kind, target_name = field_spec.target
        if target_kind == "env":
            cfg.env[target_name] = value
        elif target_kind == "header":
            cfg.headers[target_name] = value
        elif target_kind == "arg":
            cfg.args = _with_arg_value(list(cfg.args), target_name, value)
        else:
            raise McpPresetError("URL parameter presets are not supported yet")
    return _with_managed_stdio_cwd(preset.name, cfg)


def _command_available(command: str) -> bool:
    if not command:
        return False
    if shutil.which(command):
        return True
    path = Path(command).expanduser()
    return path.exists() and path.is_file()


def _status_for(preset: McpPreset, cfg: MCPServerConfig | None) -> str:
    if cfg is None:
        return "not_installed"
    if any(field.required and not _field_configured(field, cfg) for field in preset.fields):
        return "missing_credentials"
    if cfg.command and not _command_available(cfg.command):
        return "missing_dependency"
    return "configured"


def _connection_summary(cfg: MCPServerConfig | None) -> str:
    if cfg is None:
        return ""
    if cfg.command:
        return " ".join([cfg.command, *cfg.args[:2]]).strip()
    if cfg.url:
        from urllib.parse import urlsplit, urlunsplit

        parsed = urlsplit(cfg.url)
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return ""


def mcp_presets_payload(config_path: Path | None = None) -> dict[str, Any]:
    config = load_config(config_path)
    rows = []
    for preset in MCP_PRESETS:
        cfg = config.tools.mcp_servers.get(preset.name)
        status = _status_for(preset, cfg)
        rows.append(
            {
                "name": preset.name,
                "display_name": preset.display_name,
                "category": preset.category,
                "description": preset.description,
                "docs_url": preset.docs_url,
                "transport": preset.transport,
                "requires": preset.requires,
                "note": preset.note,
                "installed": cfg is not None,
                "configured": cfg is not None and status != "missing_credentials",
                "available": status == "configured",
                "status": status,
                "brand_color": preset.brand_color,
                "required_fields": [_field_payload(field, cfg) for field in preset.fields],
                "connection_summary": _connection_summary(cfg),
                "enabled_tools": list(cfg.enabled_tools) if cfg is not None else ["*"],
                "source": "preset",
            }
        )
    known = {preset.name for preset in MCP_PRESETS}
    for name, cfg in sorted(config.tools.mcp_servers.items()):
        if name in known:
            continue
        rows.append(
            {
                "name": name,
                "display_name": name,
                "category": "custom",
                "description": "Custom MCP server from config.",
                "docs_url": "",
                "transport": cfg.type or ("stdio" if cfg.command else "streamableHttp"),
                "requires": "",
                "note": "",
                "installed": True,
                "configured": True,
                "available": bool(cfg.command or cfg.url),
                "status": "configured",
                "brand_color": "#64748B",
                "required_fields": [],
                "connection_summary": _connection_summary(cfg),
                "enabled_tools": list(cfg.enabled_tools),
                "source": "custom",
            }
        )
    return {"presets": rows, "installed_count": len(config.tools.mcp_servers)}


def normalize_mcp_preset_mentions(raw: Any, config_path: Path | None = None) -> list[dict[str, Any]]:
    """Sanitize structured MCP capability mentions from clients."""
    if not isinstance(raw, list):
        return []
    known = {preset.name for preset in MCP_PRESETS}
    known.update(load_config(config_path).tools.mcp_servers)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip().lower()
        if name in seen or name not in known or _PRESET_NAME_RE.match(name) is None:
            continue
        row: dict[str, Any] = {"name": name}
        for key in ("display_name", "category", "transport", "configured"):
            value = item.get(key)
            if isinstance(value, (str, bool)):
                row[key] = value
        out.append(row)
        seen.add(name)
    return out
