"""Generate a Homebrew formula for pythinker-ai from the active venv.

Replaces the unmaintained `homebrew-pypi-poet` (last release in 2024, breaks
on every modern setuptools / lxml release). We inspect the installed
distributions with `importlib.metadata`, fetch each one's sdist URL + SHA-256
from PyPI's JSON API, and emit the formula with proper `resource` stanzas.

Usage:
    python packaging/homebrew/generate_formula.py <package> > Formula/<pkg>.rb

The active interpreter (or venv) must already have the target package and
all its runtime dependencies installed.
"""

from __future__ import annotations

import json
import sys
import textwrap
import urllib.request
from importlib.metadata import distributions
from typing import Any

PYPI_JSON = "https://pypi.org/pypi/{pkg}/{ver}/json"

DESC = "Tiny async agent framework with chat channels, memory, MCP, and an OpenAI-compatible API"
HOMEPAGE = "https://github.com/mohamed-elkholy95/Pythinker-ai"
LICENSE_LITERAL = "MIT"


def fetch_sdist(name: str, version: str) -> tuple[str, str]:
    """Return (sdist_url, sha256) for the named release on PyPI.

    Falls back to the first wheel if no sdist is published (rare but happens for
    pure-binary packages). Brew handles both — wheels are noted with a comment.
    """
    url = PYPI_JSON.format(pkg=name, ver=version)
    with urllib.request.urlopen(url, timeout=30) as resp:  # nosec B310 — fixed scheme
        payload: dict[str, Any] = json.loads(resp.read())
    files = payload.get("urls") or []
    sdist = next((f for f in files if f.get("packagetype") == "sdist"), None)
    if sdist is None:
        sdist = next((f for f in files if f.get("packagetype") == "bdist_wheel"), None)
    if sdist is None:
        raise RuntimeError(f"No distributable found for {name}=={version} on PyPI")
    return sdist["url"], sdist["digests"]["sha256"]


def normalized_name(raw: str) -> str:
    return raw.lower().replace("_", "-")


def main(target_pkg: str) -> int:
    seen: dict[str, str] = {}
    target_version: str | None = None
    target_url: str | None = None
    target_sha: str | None = None

    for dist in distributions():
        name = normalized_name(dist.metadata["Name"] or "")
        if not name or name in seen:
            continue
        ver = dist.version
        seen[name] = ver

    if normalized_name(target_pkg) not in seen:
        print(f"::error::{target_pkg} not installed in active venv", file=sys.stderr)
        return 1

    target_version = seen.pop(normalized_name(target_pkg))
    target_url, target_sha = fetch_sdist(target_pkg, target_version)

    # Stable order: alphabetical for review-friendliness.
    resources: list[tuple[str, str, str, str]] = []
    for name, ver in sorted(seen.items()):
        try:
            url, sha = fetch_sdist(name, ver)
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError, RuntimeError) as exc:
            print(f"::warning::skipping {name}=={ver}: {exc}", file=sys.stderr)
            continue
        resources.append((name, ver, url, sha))

    # Build the formula. PythonAi -> CamelCase pythinker-ai => PythinkerAi.
    klass = "".join(part.capitalize() for part in target_pkg.replace("_", "-").split("-"))
    out = []
    out.append(f"class {klass} < Formula")
    out.append("  include Language::Python::Virtualenv")
    out.append("")
    out.append(f'  desc "{DESC}"')
    out.append(f'  homepage "{HOMEPAGE}"')
    out.append(f'  url "{target_url}"')
    out.append(f'  sha256 "{target_sha}"')
    out.append(f'  license "{LICENSE_LITERAL}"')
    out.append("")
    out.append('  depends_on "python@3.12"')
    out.append("")
    # Both pythinker-ai and the sibling pythinker-code formula install a
    # `bin/pythinker` console script (see [project.scripts] in each project's
    # pyproject.toml). Without `conflicts_with`, the second `brew install`
    # crashes with the opaque error:
    #   "Could not symlink bin/pythinker, target already exists".
    # Declaring it on either side is enough for brew to refuse cleanly.
    out.append('  conflicts_with "pythinker-code",')
    out.append('    because: "both install a `pythinker` executable into bin/"')
    out.append("")
    for name, _ver, url, sha in resources:
        out.append(f'  resource "{name}" do')
        out.append(f'    url "{url}"')
        out.append(f'    sha256 "{sha}"')
        out.append("  end")
        out.append("")
    out.append("  def install")
    out.append("    virtualenv_install_with_resources")
    out.append("  end")
    out.append("")
    out.append("  test do")
    out.append(f'    assert_match "{target_version}", shell_output("#{{bin}}/pythinker --version")')
    out.append("  end")
    out.append("end")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: generate_formula.py <package-name>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
