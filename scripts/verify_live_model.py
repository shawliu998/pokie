#!/usr/bin/env python3
"""Run one redacted DeepSeek smoke over synthetic, non-sensitive source text."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from uuid import uuid4

from services.worker.app.contracts import (
    ContentVersion,
    DataAuthenticity,
    ResearchRun,
    ResearchRunState,
)
from services.worker.app.pipelines.digests import sha256_text
from services.worker.app.pipelines.model_research import (
    PROMPT_REFS,
    DeepSeekResearchRunner,
    ModelProviderError,
)
from services.worker.app.storage import InMemoryDomainAdapter


def main() -> int:
    domain = InMemoryDomainAdapter()
    try:
        runner = DeepSeekResearchRunner.from_env(domain)
    except ModelProviderError as error:
        print(
            f"live-model-smoke=FAIL error={error.__class__.__name__} reason={error}",
            file=sys.stderr,
        )
        return 1

    body = (
        "Three reviewed onboarding sessions reported that unclear permission previews delayed "
        "workspace setup. One administrator said the preview helped confirm access before launch."
    )
    version = ContentVersion(
        id=str(uuid4()),
        workspace_id=str(uuid4()),
        content_item_id=str(uuid4()),
        version_number=1,
        content_digest=sha256_text(body),
        normalized_title="Synthetic permission preview research",
        normalized_body=body,
        captured_at=datetime.now(tz=UTC),
        parser_version="live-model-smoke-v1",
        canonical_url=None,
        author=None,
        data_authenticity=DataAuthenticity.SEED,
    )
    run = ResearchRun(
        id=str(uuid4()),
        workspace_id=version.workspace_id,
        investigation_id=str(uuid4()),
        investigation_scope_version_id=str(uuid4()),
        state=ResearchRunState.QUEUED,
        graph_version="deepseek-model-research-v1",
        run_input_manifest_digest="sha256:" + "a" * 64,
        source_manifest_id=str(uuid4()),
        content_version_ids=(version.id,),
        data_authenticity=DataAuthenticity.SEED,
        provider="deepseek",
        model=runner.config.model,
        prompt_refs=PROMPT_REFS,
        question="Should the product team prioritize clearer permission execution previews?",
    )
    domain.research_runs[run.id] = run
    domain.content_versions[version.id] = version
    try:
        result = runner.run(run.id, [version])
    except ModelProviderError as error:
        print(
            f"live-model-smoke=FAIL error={error.__class__.__name__} reason={error}",
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            f"live-model-smoke=FAIL error={error.__class__.__name__}",
            file=sys.stderr,
        )
        return 1

    if (
        domain.research_runs[run.id].state is not ResearchRunState.COMPLETED
        or not result.evidence
        or not result.claims
        or any(item.content_version_id != version.id for item in result.evidence)
        or any(item.generation_method != "model" for item in result.claims)
    ):
        print("live-model-smoke=FAIL error=INTEGRITY_CHECK", file=sys.stderr)
        return 1
    print(
        "live-model-smoke=PASS "
        f"evidence={len(result.evidence)} claims={len(result.claims)} "
        f"graph_nodes={len(result.graph_nodes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
