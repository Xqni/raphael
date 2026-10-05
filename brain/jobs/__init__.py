"""Job package: re-exports the shared SQLite connection (brain.memory owns
the schema — jobs + journal tables live there)."""
from brain.memory import get_conn  # noqa: F401
