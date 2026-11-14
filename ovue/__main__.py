"""Allow ``python -m ovue`` to use the same entry point as ``ovue``."""

from ovue.cli import main

# Run the CLI only when Python executes this module directly.
if __name__ == "__main__":
    main()
