"""Command-line entry point for Ovue administration and serving."""

# Import argparse for the initial command-line interface.
import argparse


# Define the package command entry point.
def main() -> None:
    # Create the top-level Ovue command parser.
    parser = argparse.ArgumentParser(prog="ovue")
    # Add a helpful description to the command's help output.
    parser.description = "Agent-seat message channel."
    # Parse arguments and let argparse display help or usage errors.
    parser.parse_args()
