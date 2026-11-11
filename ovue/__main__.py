"""Allow ``python -m ovue`` to use the same entry point as ``ovue``."""

# Import the command-line entry point from the package.
from ovue.cli import main


# Run the CLI only when Python executes this module directly.
if __name__ == "__main__":
    main()
