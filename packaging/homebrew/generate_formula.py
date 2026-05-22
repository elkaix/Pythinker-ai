"""Generate a Homebrew formula for pythinker-ai.

Pythinker pulls in cryptography, pydantic-core, jiter, tiktoken, rpds-py,
primp, Pillow, lxml, and other packages with Rust or C extensions. Brew's
`Language::Python::Virtualenv` enforces ``--no-binary :all: --only-binary
:none:`` on every resource install, which means each sdist must compile from
source — including bootstrapping maturin from a Rust sdist inside the PEP 517
build env. That path is fragile in practice (maturin's sdist install dies
silently in build isolation even with Rust + OpenSSL on the host).

We side-step the whole compile chain: the formula provisions a plain venv
and runs ``pip install`` directly with binary wheels allowed, so PyPI's
prebuilt arm64/x86_64 macOS wheels are used. Reproducibility comes from the
``pythinker-ai==<version>`` pin plus pythinker-ai's own pyproject.toml dep
constraints. This is acceptable for a single-maintainer Tier 2 tap (not a
homebrew-core formula, where source-only is required).

Assumption: every transitive runtime dependency publishes a macOS arm64 +
Python 3.12 wheel to PyPI. True for the current dependency surface; if a
future resource gains a wheel gap, pip will fall back to a source build and
we'll need to revisit (either add the native dep here or pin around the
gap).

Usage:
    python packaging/homebrew/generate_formula.py <package> > Formula/<pkg>.rb
"""

from __future__ import annotations

import json
import sys
import urllib.request
from importlib.metadata import distributions
from typing import Any

PYPI_JSON = "https://pypi.org/pypi/{pkg}/{ver}/json"

DESC = "Tiny async agent framework with chat channels, memory, MCP, and an OpenAI-compatible API"
HOMEPAGE = "https://github.com/mohamed-elkholy95/Pythinker-ai"
LICENSE_LITERAL = "MIT"


def fetch_sdist(name: str, version: str) -> tuple[str, str]:
    """Return ``(sdist_url, sha256)`` for the release on PyPI."""
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
    target_version: str | None = None
    for dist in distributions():
        name = normalized_name(dist.metadata["Name"] or "")
        if name == normalized_name(target_pkg):
            target_version = dist.version
            break
    if target_version is None:
        print(f"::error::{target_pkg} not installed in active venv", file=sys.stderr)
        return 1

    target_url, target_sha = fetch_sdist(target_pkg, target_version)

    # pythinker-ai -> PythinkerAi (Ruby CamelCase).
    klass = "".join(part.capitalize() for part in target_pkg.replace("_", "-").split("-"))
    out: list[str] = []
    out.append(f"class {klass} < Formula")
    out.append(f'  desc "{DESC}"')
    out.append(f'  homepage "{HOMEPAGE}"')
    out.append(f'  url "{target_url}"')
    out.append(f'  sha256 "{target_sha}"')
    out.append(f'  license "{LICENSE_LITERAL}"')
    out.append("")
    out.append('  depends_on "python@3.12"')
    out.append("")
    # Both pythinker-ai and the sibling pythinker-code formula install a
    # `bin/pythinker` console script (see [project.scripts] in each
    # project's pyproject.toml). Without `conflicts_with`, the second
    # `brew install` crashes with the opaque error:
    #   "Could not symlink bin/pythinker, target already exists".
    out.append('  conflicts_with "pythinker-code",')
    out.append('    because: "both install a `pythinker` executable into bin/"')
    out.append("")
    out.append("  def install")
    out.append("    # Provision a plain venv and let pip resolve prebuilt wheels for")
    out.append("    # the Rust/C-extension dependency tree (cryptography, pydantic-core,")
    out.append("    # jiter, tiktoken, rpds-py, primp, Pillow, lxml, …). Using")
    out.append("    # `virtualenv_install_with_resources` would force `--no-binary :all:`")
    out.append("    # and require bootstrapping maturin from a Rust sdist inside PEP 517")
    out.append("    # build isolation, which is the failure mode this formula is escaping.")
    out.append('    python = Formula["python@3.12"].opt_libexec/"bin/python3"')
    out.append('    system python, "-m", "venv", libexec')
    # Install from `buildpath` — the sdist brew already downloaded and
    # verified via `sha256`. pip builds pythinker-ai (pure Python) from
    # the local source and resolves every transitive dependency from
    # PyPI as a prebuilt wheel.
    out.append('    system libexec/"bin/pip", "install", "--no-warn-script-location", buildpath')
    out.append('    bin.install_symlink libexec/"bin/pythinker"')
    out.append("  end")
    out.append("")
    out.append("  test do")
    out.append(
        f'    assert_match "{target_version}", shell_output("#{{bin}}/pythinker --version")'
    )
    out.append("  end")
    out.append("end")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: generate_formula.py <package-name>", file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
