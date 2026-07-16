"""Deterministic ResearchRun proposal provider."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from services.worker.app.contracts import (
    ClaimVersionProposal,
    ContentVersion,
    EvidenceProposal,
    ResearchRun,
    ResearchRunState,
    WorkerDomainAdapter,
)
from services.worker.app.pipelines.digests import deterministic_id, sha256_text

INJECTION_PATTERNS = {
    "instruction_override": re.compile(
        r"ignore (all )?(previous|system|developer) instructions", re.I
    ),
    "tool_abuse": re.compile(r"\b(call|run|execute)\b.*\b(shell|terminal|bash|tool)\b", re.I),
    "data_exfiltration": re.compile(
        r"\b(exfiltrate|leak|print|reveal)\b.*\b(token|secret|credential|key)\b", re.I
    ),
    "policy_change": re.compile(
        r"\b(change|disable|bypass)\b.*\b(policy|watchlist|approval)\b", re.I
    ),
}


@dataclass(frozen=True, slots=True)
class DeterministicResearchResult:
    evidence: list[EvidenceProposal]
    claims: list[ClaimVersionProposal]
    injection_flags: tuple[str, ...]


class DeterministicResearchRunner:
    def __init__(
        self, domain: WorkerDomainAdapter, generator_version: str = "deterministic-research-v1"
    ) -> None:
        self.domain = domain
        self.generator_version = generator_version

    def run(
        self,
        run_id: str,
        content_versions: list[ContentVersion],
        worker_attempt_id: str | None = None,
        lease_for: timedelta = timedelta(seconds=120),
    ) -> DeterministicResearchResult:
        run = self.domain.get_research_run(run_id)
        trace_id = deterministic_id("trace", run_id, run.run_input_manifest_digest)
        task_id = deterministic_id("task", run_id, "deterministic_evidence_scan")
        self.domain.transition_research_run(run_id, ResearchRunState.RUNNING, worker_attempt_id)
        self.domain.append_run_event(
            run_id,
            "task.started",
            {"task_id": task_id, "task_type": "deterministic_evidence_scan", "status": "running"},
            trace_id,
        )
        if worker_attempt_id:
            self.domain.heartbeat_research_run(
                run_id, worker_attempt_id, datetime.now(tz=UTC), lease_for
            )

        evidence = self._propose_evidence(run, content_versions)
        all_flags = tuple(sorted({flag for item in evidence for flag in item.injection_flags}))

        claims: list[ClaimVersionProposal] = []
        if all_flags:
            self.domain.append_run_event(
                run_id,
                "review.required",
                {
                    "target_type": "ResearchRun",
                    "target_id": run.id,
                    "reason_code": "prompt_injection_marker",
                    "safe_summary": ",".join(all_flags),
                },
                trace_id,
            )
        if evidence:
            claims = [self._propose_claim(run, evidence)]
        if not evidence:
            self.domain.append_run_event(
                run_id,
                "review.required",
                {
                    "target_type": "ResearchRun",
                    "target_id": run.id,
                    "reason_code": "no_evidence_found",
                },
                trace_id,
            )

        self.domain.append_run_event(
            run_id,
            "task.completed",
            {"task_id": task_id, "task_type": "deterministic_evidence_scan", "status": "completed"},
            trace_id,
        )
        if worker_attempt_id:
            self.domain.heartbeat_research_run(
                run_id, worker_attempt_id, datetime.now(tz=UTC), lease_for
            )
        self.domain.append_run_event(
            run_id,
            "review.required",
            {
                "target_type": "ResearchRun",
                "target_id": run.id,
                "reason_code": "human_review_required_before_brief",
                "safe_summary": (
                    "EvidenceReview and ClaimReview are required before any synthesis "
                    "or Brief command."
                ),
            },
            trace_id,
        )
        if evidence and claims:
            self.domain.persist_research_proposals(
                run_id, evidence, claims, None, worker_attempt_id
            )
        self.domain.transition_research_run(run_id, ResearchRunState.COMPLETED, worker_attempt_id)
        return DeterministicResearchResult(evidence, claims, all_flags)

    def _propose_evidence(
        self, run: ResearchRun, versions: list[ContentVersion]
    ) -> list[EvidenceProposal]:
        proposals: list[EvidenceProposal] = []
        for version in versions:
            flags = scan_injection(version.normalized_body)
            quote_start, quote_end = _quote_span(version.normalized_body)
            quote = version.normalized_body[quote_start:quote_end]
            if not quote:
                continue
            stance = (
                "opposes"
                if re.search(r"\b(clearer|improved|willing to pay|not a problem)\b", quote, re.I)
                else "supports"
            )
            proposals.append(
                EvidenceProposal(
                    id=deterministic_id("evidence", run.id, version.id, quote_start, quote_end),
                    workspace_id=run.workspace_id,
                    investigation_id=run.investigation_id,
                    research_run_id=run.id,
                    content_version_id=version.id,
                    quote_start=quote_start,
                    quote_end=quote_end,
                    quote_text_digest=sha256_text(quote),
                    stance=stance,
                    extraction_method="deterministic_rule",
                    injection_flags=flags,
                    data_authenticity=run.data_authenticity,
                )
            )
        return proposals

    def _propose_claim(
        self, run: ResearchRun, evidence: list[EvidenceProposal]
    ) -> ClaimVersionProposal:
        support_count = sum(1 for item in evidence if item.stance == "supports")
        opposition_count = sum(1 for item in evidence if item.stance == "opposes")
        confidence_level = "medium" if opposition_count else "high"
        limitations = ["Deterministic proposal; requires human review."]
        if opposition_count:
            limitations.append("Counter-evidence is present and reduces confidence.")
        claim_id = deterministic_id("claim", run.id, tuple(item.id for item in evidence))
        claim_version_id = deterministic_id(
            "claim-version", claim_id, support_count, opposition_count
        )
        return ClaimVersionProposal(
            id=claim_version_id,
            claim_id=claim_id,
            research_run_id=run.id,
            text=(
                "Observed source content indicates a product risk that should be "
                "reviewed by the PM."
            ),
            confidence_level=confidence_level,
            confidence_inputs={
                "support_count": support_count,
                "opposition_count": opposition_count,
                "calibration_status": "uncalibrated",
            },
            limitations=tuple(limitations),
            evidence_ids=tuple(item.id for item in evidence),
            generation_method="deterministic",
            generator_version=self.generator_version,
            data_authenticity=run.data_authenticity,
            suggestion_origin="deterministic_rule",
        )


def _quote_span(body: str) -> tuple[int, int]:
    stripped = body.strip()
    if not stripped:
        return (0, 0)
    first_sentence = re.search(r"(.{20,240}?)(?:[.!?]\s|$)", stripped, re.S)
    quote = first_sentence.group(1).strip() if first_sentence else stripped[:240]
    start = body.find(quote)
    return (max(start, 0), max(start, 0) + len(quote))


def scan_injection(body: str) -> tuple[str, ...]:
    return tuple(
        sorted(name for name, pattern in INJECTION_PATTERNS.items() if pattern.search(body))
    )
