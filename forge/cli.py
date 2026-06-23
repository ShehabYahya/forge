from __future__ import annotations

import argparse
import sys
from typing import NoReturn

from . import __version__


def _fail(message: str) -> NoReturn:
    print(f"forge: {message}", file=sys.stderr)
    sys.exit(1)


def _mcp() -> None:
    from .mcp_server import run_mcp

    run_mcp()


def _bridge() -> None:
    from .plugin.bridge import run_bridge

    run_bridge()


def _version() -> None:
    print(__version__)


def _install_main(args: argparse.Namespace) -> None:
    from .distribution import DistributionService

    svc = DistributionService(config_root=args.config_root)
    svc.install(version=args.version, release_base=args.release_base)


def _doctor_main(args: argparse.Namespace) -> None:
    from .distribution import DistributionService

    svc = DistributionService(config_root=args.config_root)
    ok = svc.doctor()
    if not ok:
        sys.exit(1)


def _uninstall_main(args: argparse.Namespace) -> None:
    from .distribution import DistributionService

    svc = DistributionService(config_root=args.config_root)
    svc.uninstall()


def _purge_main(args: argparse.Namespace) -> None:
    from .distribution import DistributionService

    svc = DistributionService()
    svc.purge(force=args.force)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forge",
        description="Forge runtime control layer",
    )
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("mcp", help="Start MCP stdio server")
    sub.add_parser("bridge", help="Start bridge protocol on stdin/stdout")
    sub.add_parser("version", help="Print version and exit")

    install = sub.add_parser("install", help="Install Forge globally into OpenCode")
    install.add_argument("--version", default=None, help="Forge version to install")
    install.add_argument("--config-root", default=None,
                         help="OpenCode config root directory")
    install.add_argument("--release-base", default=None,
                         help="GitHub release base URL")

    doctor = sub.add_parser("doctor", help="Verify installation integrity")
    doctor.add_argument("--config-root", default=None,
                        help="OpenCode config root directory")

    uninstall = sub.add_parser("uninstall", help="Remove Forge integration")
    uninstall.add_argument("--config-root", default=None,
                           help="OpenCode config root directory")

    purge = sub.add_parser("purge", help="Remove Forge runtime data")
    purge.add_argument("--force", action="store_true",
                       help="Skip confirmation prompt")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "mcp" or args.command is None:
        _mcp()
    elif args.command == "bridge":
        _bridge()
    elif args.command == "version":
        _version()
    elif args.command == "install":
        _install_main(args)
    elif args.command == "doctor":
        _doctor_main(args)
    elif args.command == "uninstall":
        _uninstall_main(args)
    elif args.command == "purge":
        _purge_main(args)
    else:
        _fail(f"unknown command: {args.command}")


if __name__ == "__main__":
    main()
