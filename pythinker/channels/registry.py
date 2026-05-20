"""Auto-discovery for built-in channel modules and external plugins."""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from pythinker.channels.base import BaseChannel

_INTERNAL = frozenset({"base", "manager", "registry"})


def discover_channel_names() -> list[str]:
    """Return all built-in channel module names by scanning the package (zero imports).

    Channels may be either flat modules (``pythinker/channels/telegram.py``) or
    packages (``pythinker/channels/websocket/``); the websocket carve-out moved
    one of the built-ins from the former shape into the latter, so we accept
    both ``ispkg`` cases here.
    """
    import pythinker.channels as pkg

    return [
        name
        for _, name, _ispkg in pkgutil.iter_modules(pkg.__path__)
        if name not in _INTERNAL
    ]


def load_channel_class(module_name: str) -> type[BaseChannel]:
    """Import *module_name* and return the first BaseChannel subclass found."""
    from pythinker.channels.base import BaseChannel as _Base

    mod = importlib.import_module(f"pythinker.channels.{module_name}")
    for attr in dir(mod):
        obj = getattr(mod, attr)
        if isinstance(obj, type) and issubclass(obj, _Base) and obj is not _Base:
            return obj
    raise ImportError(f"No BaseChannel subclass in pythinker.channels.{module_name}")


def discover_plugins(
    enabled_names: set[str] | None = None,
) -> dict[str, type[BaseChannel]]:
    """Discover external channel plugins registered via entry_points.

    When *enabled_names* is given, only plugins whose name is in that set
    are loaded — avoids importing SDK-heavy plugins that are not in use.
    """
    from importlib.metadata import entry_points

    plugins: dict[str, type[BaseChannel]] = {}
    for ep in entry_points(group="pythinker.channels"):
        if enabled_names is not None and ep.name not in enabled_names:
            continue
        try:
            cls = ep.load()
            plugins[ep.name] = cls
        except Exception as e:
            logger.warning("Failed to load channel plugin '{}': {}", ep.name, e)
    return plugins


def discover_enabled(
    enabled_names: set[str],
    *,
    _names: list[str] | None = None,
    _include_all_external: bool = False,
) -> dict[str, type[BaseChannel]]:
    """Return channels whose module names are in *enabled_names*.

    Uses cheap ``pkgutil.iter_modules`` to list names, then imports only
    those that match — skipping the heavy third-party SDK imports of
    unneeded channels.
    """
    names = _names if _names is not None else discover_channel_names()
    result: dict[str, type[BaseChannel]] = {}
    for modname in names:
        if modname not in enabled_names:
            continue
        try:
            result[modname] = load_channel_class(modname)
        except ImportError as e:
            logger.debug("Skipping built-in channel '{}': {}", modname, e)

    external = discover_plugins(None if _include_all_external else enabled_names)
    shadowed = set(external) & set(result)
    if shadowed:
        logger.warning("Plugin(s) shadowed by built-in channels (ignored): {}", shadowed)
    result.update({k: v for k, v in external.items() if k not in shadowed})

    return result


def discover_all() -> dict[str, type[BaseChannel]]:
    """Return all channels: built-in (pkgutil) merged with external (entry_points).

    Built-in channels take priority — an external plugin cannot shadow a built-in name.
    """
    names = discover_channel_names()
    return discover_enabled(set(names), _names=names, _include_all_external=True)


def get_channel_config_fields(name: str) -> dict[str, object] | None:
    """Return optional config workbench metadata exported by a channel module."""
    try:
        channel_cls = load_channel_class(name)
    except ImportError:
        return None
    module = importlib.import_module(channel_cls.__module__)
    metadata = getattr(module, "CONFIG_FIELDS", None)
    return metadata if isinstance(metadata, dict) else None
