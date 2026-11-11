"""Persistence adapters for Ovue."""

# Export the SQLite adapter as the storage package's public interface.
from ovue.storage.sqlite import Storage

# Declare the intentionally small public storage API.
__all__ = ["Storage"]
