"""Cartha CLI package."""


def main() -> None:  # pragma: no cover
    import sys

    argv = sys.argv[1:]

    if not argv:
        sys.argv = [sys.argv[0]]
        from .commands.help import print_root_help

        print_root_help()
        raise SystemExit(0)

    if argv[0] in {"-h", "--help"}:
        original = sys.argv[:]
        sys.argv = [sys.argv[0]]
        from .commands.help import print_root_help

        print_root_help()
        sys.argv = original
        raise SystemExit(0)

    original = sys.argv[:]
    sanitized = [original[0]] + [arg for arg in argv if arg not in {"-h", "--help"}]
    sys.argv = sanitized
    from .main import app

    sys.argv = original
    app()


__all__ = ["main"]
