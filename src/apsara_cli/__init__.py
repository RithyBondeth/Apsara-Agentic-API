from importlib.metadata import PackageNotFoundError, version as _package_version

from apsara_cli.cli.parser import main

__all__ = ["main", "__version__"]

try:
    # Single source of truth is pyproject.toml; reading it back from the
    # installed metadata keeps this from drifting on release.
    __version__ = _package_version("apsara-agentic")
except PackageNotFoundError:  # pragma: no cover - running from a source tree
    __version__ = "0.0.0+dev"
