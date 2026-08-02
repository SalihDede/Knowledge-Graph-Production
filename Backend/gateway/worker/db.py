from __future__ import annotations

import os

from accounts.database import create_database


def get_database_url() -> str:
    return os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://kg:kg@postgres:5432/knowledge_graph",
    )


def build_session_factory():
    """Fresh engine + sessionmaker per task invocation.

    Each Celery task run drives its own `asyncio.run(...)` event loop; asyncpg
    connections are bound to the loop that created them, so reusing a
    module-level engine across invocations would break on the second task.
    """
    return create_database(get_database_url())
