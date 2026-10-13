"""Allow the managed runtime host to run as ``python -m cross_embodiment.cli``."""

from . import main


if __name__ == "__main__":
    raise SystemExit(main())
