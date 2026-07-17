from __future__ import annotations

import sys


def test_quant_agent_imports_do_not_load_fixture_script() -> None:
    """Normal quant-agent worker code must not depend on the Phase 0 fixture script."""
    modules_before = set(sys.modules)

    # Import the normal quant-agent worker surface.
    from services.worker.app.pipelines import quant_agent  # noqa: F401
    from services.worker.app.quant_agent import (  # noqa: F401
        provider,
        runner,
        tool_registry,
    )

    loaded = set(sys.modules) - modules_before
    assert "packages.contracts.quant.runtime" not in loaded
    assert "build_quant_script" not in {
        name for module in loaded for name in getattr(sys.modules[module], "__dict__", {})
    }
