"""Allow ``python -m ovue`` to use the same entry point as ``ovue``."""

from ovue.cli import main

if __name__ == "__main__":
    main()
