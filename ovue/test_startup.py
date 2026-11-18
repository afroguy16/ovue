"""Check that both documented package entry points reach the same CLI."""

import subprocess
import sys
from pathlib import Path


def test_package_entrypoints_display_the_same_cli_help() -> None:
    """Show that ``ovue`` and ``python -m ovue`` use the same command parser."""
    module_result = subprocess.run(
        [sys.executable, "-m", "ovue", "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    executable = Path(sys.executable).with_name("ovue")
    command_result = subprocess.run(
        [str(executable), "--help"],
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert module_result.returncode == 0
    assert command_result.returncode == 0
    assert module_result.stdout == command_result.stdout
    assert "usage: ovue" in module_result.stdout
    assert "start the HTTP and SSE service" in module_result.stdout
