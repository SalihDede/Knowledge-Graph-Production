from __future__ import annotations

import os
import subprocess
import sys

GATEWAY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_import(statement: str) -> subprocess.CompletedProcess:
    # PYTHONSAFEPATH=1 (set by some sandboxes/CI images) stops Python from
    # implicitly adding cwd to sys.path for `-c`, which would make this check
    # fail for a reason unrelated to what it's testing. Setting PYTHONPATH
    # explicitly works regardless of that setting.
    env = {**os.environ, "PYTHONPATH": GATEWAY_ROOT}
    return subprocess.run(
        [sys.executable, "-c", statement],
        cwd=GATEWAY_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_worker_celery_app_imports_standalone() -> None:
    """`celery -A worker.celery_app worker` imports worker.celery_app as the
    very first module in a fresh process. If anything in that import chain
    pulls a specific name out of a partially-initialized module (rather than
    a bare module reference), it only fails in that exact ordering -- every
    other test in this suite imports `documents`/`triples` first, which
    hides the bug. Regression test for that failure mode.
    """
    result = _run_import("import worker.celery_app")
    assert result.returncode == 0, result.stderr


def test_documents_routes_imports_standalone() -> None:
    result = _run_import("import documents.routes")
    assert result.returncode == 0, result.stderr
