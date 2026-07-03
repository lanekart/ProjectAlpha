"""Command-line interface for Project Alpha."""

import platform

from alpha.version import __version__


def main() -> None:
    """Application entry point."""
    print("=" * 60)
    print(f"Project Alpha v{__version__}")
    print("Professional NSE Trading Intelligence Platform")
    print("=" * 60)
    print(f"Python      : {platform.python_version()}")
    print("Environment : Development")
    print("Status      : Ready")
    print("=" * 60)


if __name__ == "__main__":
    main()