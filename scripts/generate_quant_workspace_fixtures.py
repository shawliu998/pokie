"""Regenerate the browser fixture bundle from the server-owned projection."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.api.app.modules.quant.snapshot import (  # noqa: E402
    FIXTURE_STATES,
    quant_workspace_fixture,
)

OUTPUT = ROOT / "apps/mac/e2e/fixtures/quant-workspace-fixtures.json"
MAC_OUTPUT = ROOT / "apps/mac/src/features/quant/quant-fixture.generated.json"


def main() -> None:
    bundle = {state: quant_workspace_fixture(state) for state in sorted(FIXTURE_STATES)}
    OUTPUT.write_text(
        json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    MAC_OUTPUT.write_text(
        json.dumps(
            bundle["quant-completed"],
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
