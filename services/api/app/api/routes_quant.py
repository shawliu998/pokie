from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse

from packages.contracts.enums import DataAuthenticity
from packages.contracts.quant import (
    QUANT_MARKET_RUN_CONTRACT_VERSION,
    QuantAgentPlan,
    QuantArtifactResponse,
    QuantBinanceSpotFetchRequest,
    QuantConnectorDirectoryResponse,
    QuantCorporateActionsAttestation,
    QuantDatasetImportRequest,
    QuantDatasetPreviewResponse,
    QuantDatasetResponse,
    QuantExperimentResponse,
    QuantFixtureCommandRequest,
    QuantKrakenSpotFetchRequest,
    QuantMarketBinanceFetchRequest,
    QuantMarketDataProvenance,
    QuantMarketDatasetCadenceQuality,
    QuantMarketDatasetEvidence,
    QuantMarketDatasetV2ImportRequest,
    QuantMarketDatasetV2PreviewResponse,
    QuantMarketDatasetV2Response,
    QuantMarketRunV2CreateRequest,
    QuantMarketRunV2Response,
    QuantNasdaqEquityFetchRequest,
    QuantPlanApproveRequest,
    QuantPlanChangesRequest,
    QuantProjectCreateRequest,
    QuantProjectResponse,
    QuantProviderResponseAttestation,
    QuantRunCancelRequest,
    QuantRunCreateRequest,
    QuantRunResponse,
    QuantRunRetryRequest,
    QuantSplitEventSummary,
    QuantStrategyReportExportRequest,
    QuantStrategyReportExportResponse,
    QuantStreamResetEvent,
    decode_quant_event,
    encode_quant_sse,
)
from packages.contracts.quant.enums import QuantRunMode
from services.api.app.core.auth import WorkspaceContext, require_owner
from services.api.app.core.errors import invalid_state
from services.api.app.modules.quant.binance_market_data import (
    BinanceMarketDataClient,
    BinanceMarketDataError,
)
from services.api.app.modules.quant.binance_market_data_v2 import (
    BinanceMarketDataV2Client,
    BinanceMarketDataV2Error,
)
from services.api.app.modules.quant.evidence_export import build_strategy_evidence_bundle_export
from services.api.app.modules.quant.kraken_market_data_v2 import (
    KRAKEN_SPOT_CONNECTOR_VERSION,
    KRAKEN_SPOT_DOCUMENTATION_REFERENCE,
    KRAKEN_SPOT_TERMS_REFERENCE,
    KrakenMarketDataV2Client,
    KrakenMarketDataV2Error,
)
from services.api.app.modules.quant.nasdaq_market_data import (
    MAX_HISTORY_LIMIT,
    NasdaqMarketDataClient,
    NasdaqMarketDataError,
)
from services.api.app.modules.quant.report_export import build_strategy_report_export
from services.api.app.modules.quant.snapshot import (
    apply_fixture_command,
    quant_agent_workspace_snapshot,
    quant_workspace_fixture,
)
from services.api.app.modules.quant.store import get_quant_store
from services.worker.app.quant_agent.provider import (
    QuantAgentProviderError,
    load_quant_agent_provider,
)

router = APIRouter(prefix="/v1/quant")
Ctx = Annotated[WorkspaceContext, Depends(require_owner)]


def _store():
    return get_quant_store()


def _binance_market_data_client() -> BinanceMarketDataClient:
    return BinanceMarketDataClient()


def _binance_market_data_v2_client() -> BinanceMarketDataV2Client:
    return BinanceMarketDataV2Client()


def _kraken_market_data_v2_client() -> KrakenMarketDataV2Client:
    return KrakenMarketDataV2Client()


def _nasdaq_market_data_client() -> NasdaqMarketDataClient:
    return NasdaqMarketDataClient()


def _generate_agent_plan(research_goal: str) -> QuantAgentPlan:
    try:
        provider = load_quant_agent_provider()
        return provider.plan(research_goal)
    except QuantAgentProviderError:
        # A plan is produced before the run exists, so there is no durable run
        # on which an Agent provider fallback could be attributed. Runtime
        # fallback remains available only through the audited worker path.
        raise invalid_state("The configured Agent provider could not generate a plan.") from None


def _generate_revised_agent_plan(research_goal: str, change_request: str) -> QuantAgentPlan:
    return _generate_agent_plan(
        f"{research_goal}\n\nUser-requested plan change: {change_request.strip()}"
    )


@router.get("/workspace-snapshot")
def get_workspace_snapshot(context: Ctx) -> dict[str, Any]:
    # Dependency resolution is intentional: the fixture is still scoped behind
    # the authenticated workspace API even though its content is deterministic.
    return quant_agent_workspace_snapshot(
        workspace_id=context.workspace_id
    ) or quant_workspace_fixture(workspace_id=context.workspace_id)


@router.post(
    "/strategy-report-exports/preview",
    response_model=QuantStrategyReportExportResponse,
)
def preview_strategy_report_export(
    body: QuantStrategyReportExportRequest, context: Ctx
) -> dict[str, Any]:
    if body.export_type == "strategy_evidence_bundle_json":
        return build_strategy_evidence_bundle_export(
            workspace_id=context.workspace_id,
            run_id=str(body.run_id),
            candidate_id=str(body.candidate_id),
        )
    return build_strategy_report_export(
        workspace_id=context.workspace_id,
        run_id=str(body.run_id),
        candidate_id=str(body.candidate_id),
    )


@router.post("/workspace-snapshot/commands")
def command_workspace_snapshot(body: QuantFixtureCommandRequest, context: Ctx) -> dict[str, Any]:
    if body.command == "start_auto_research":
        goal = body.payload.get("goal")
        if not isinstance(goal, str) or not goal.strip() or len(goal.strip()) > 2_000:
            raise invalid_state("Auto Research requires a goal from 1 to 2,000 characters.")
        dataset_id = body.payload.get("dataset_id")
        if dataset_id is not None and not isinstance(dataset_id, str):
            raise invalid_state("dataset_id must be text when supplied.")
        store = _store()
        store.validate_dataset_for_run(workspace_id=context.workspace_id, dataset_id=dataset_id)
        projects = store.list_projects(workspace_id=context.workspace_id)
        project = (
            projects[0]
            if projects
            else store.create_project(
                workspace_id=context.workspace_id,
                name="Autonomous SPY Research",
                objective=goal.strip(),
            )
        )
        store.create_run(
            workspace_id=context.workspace_id,
            project_id=project.id,
            question=goal.strip(),
            mode=QuantRunMode.AUTO,
            expected_project_row_version=project.row_version,
            agent_plan=_generate_agent_plan(goal.strip()),
            dataset_id=dataset_id,
        )
        snapshot = quant_agent_workspace_snapshot(workspace_id=context.workspace_id)
        if snapshot is None:  # pragma: no cover - creation above is authoritative
            raise invalid_state("The autonomous run could not be projected.")
        return snapshot
    dynamic_snapshot = quant_agent_workspace_snapshot(workspace_id=context.workspace_id)
    if dynamic_snapshot is not None and body.command in {
        "approve_plan",
        "request_plan_changes",
        "cancel_run",
        "retry_run",
    }:
        store = _store()
        run = store.get_run(
            workspace_id=context.workspace_id,
            run_id=dynamic_snapshot["run"]["id"],
        )
        if body.command == "approve_plan":
            store.approve_plan(
                workspace_id=context.workspace_id,
                run_id=run.id,
                expected_row_version=body.expected_row_version,
                plan_revision=run.plan_revision,
                reason="Approved from the Mac workspace.",
            )
        elif body.command == "request_plan_changes":
            change_request = body.payload.get("change_request", "Revise the bounded plan.")
            if not isinstance(change_request, str):
                raise invalid_state("Plan change request must be text.")
            research_goal = store.prepare_plan_changes(
                workspace_id=context.workspace_id,
                run_id=run.id,
                expected_row_version=body.expected_row_version,
                plan_revision=run.plan_revision,
            )
            store.request_plan_changes(
                workspace_id=context.workspace_id,
                run_id=run.id,
                expected_row_version=body.expected_row_version,
                plan_revision=run.plan_revision,
                change_request=change_request,
                agent_plan=(
                    _generate_revised_agent_plan(research_goal, change_request)
                    if research_goal is not None
                    else None
                ),
            )
        elif body.command == "cancel_run":
            store.cancel_run(
                workspace_id=context.workspace_id,
                run_id=run.id,
                expected_row_version=body.expected_row_version,
                reason="Stopped from the Mac workspace.",
            )
        else:
            store.retry_run(
                workspace_id=context.workspace_id,
                run_id=run.id,
                expected_row_version=body.expected_row_version,
                reason="Retried from the Mac workspace.",
            )
        refreshed = quant_agent_workspace_snapshot(workspace_id=context.workspace_id)
        if refreshed is None:  # pragma: no cover
            raise invalid_state("The autonomous run projection is unavailable.")
        return refreshed
    try:
        return apply_fixture_command(
            workspace_id=context.workspace_id,
            command=body.command,
            expected_row_version=body.expected_row_version,
            payload=body.payload,
        )
    except ValueError as exc:
        raise invalid_state(str(exc)) from exc


@router.post("/projects", response_model=QuantProjectResponse, status_code=201)
def create_project(body: QuantProjectCreateRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    project = store.create_project(
        workspace_id=context.workspace_id,
        name=body.name,
        objective=body.objective,
    )
    return QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(
        mode="json"
    )


@router.get("/projects", response_model=list[QuantProjectResponse])
def list_projects(context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    return [
        QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(
            mode="json"
        )
        for project in store.list_projects(workspace_id=context.workspace_id)
    ]


@router.get("/projects/{project_id}", response_model=QuantProjectResponse)
def get_project(project_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    project = store.get_project(workspace_id=context.workspace_id, project_id=str(project_id))
    return QuantProjectResponse.model_validate(store.to_project_response(project)).model_dump(
        mode="json"
    )


@router.post("/datasets/import-csv", response_model=QuantDatasetResponse, status_code=201)
def import_dataset_csv(body: QuantDatasetImportRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    try:
        record = store.import_dataset_csv(
            workspace_id=context.workspace_id,
            name=body.name,
            symbol=body.symbol,
            csv_text=body.csv_text,
            file_name=body.file_name,
            source_name=body.source_name,
            source_reference=body.source_reference,
            market_calendar=body.market_calendar,
            time_zone=body.time_zone,
            price_adjustment=body.price_adjustment,
        )
    except ValueError as exc:
        raise invalid_state(str(exc)) from exc
    return QuantDatasetResponse.model_validate(store.to_dataset_response(record)).model_dump(
        mode="json"
    )


@router.post(
    "/datasets/fetch-binance-spot",
    response_model=QuantDatasetResponse,
    status_code=201,
)
def fetch_binance_spot_dataset(body: QuantBinanceSpotFetchRequest, context: Ctx) -> dict[str, Any]:
    try:
        fetched = _binance_market_data_client().fetch_daily_klines(
            symbol=body.symbol,
            limit=body.limit,
        )
        record = _store().import_dataset_csv(
            workspace_id=context.workspace_id,
            name=body.name or f"{body.symbol} Binance Spot daily",
            symbol=body.symbol,
            csv_text=fetched.csv_text,
            source_kind="provider_fetch",
            source_name="Binance Spot public market data",
            source_reference=fetched.source_reference,
            provider_id="binance_spot",
            provider_response_digest=fetched.provider_response_digest,
            provider_response_attestations=(
                QuantProviderResponseAttestation(
                    kind="daily_bars",
                    digest=fetched.provider_response_digest,
                    source_reference=fetched.source_reference,
                ),
            ),
            price_adjustment_verification_status="not_applicable",
            retrieved_at=fetched.retrieved_at,
            requested_limit=fetched.requested_limit,
            returned_bar_count=fetched.returned_bar_count,
            dropped_incomplete_count=fetched.dropped_incomplete_count,
            normalization_note=fetched.normalization_note,
            attestation_status="provider_retrieved",
            market_calendar="24x7",
            time_zone="UTC",
            price_adjustment="unadjusted",
        )
    except (BinanceMarketDataError, ValueError) as exc:
        raise invalid_state(str(exc)) from exc
    return QuantDatasetResponse.model_validate(_store().to_dataset_response(record)).model_dump(
        mode="json"
    )


@router.post(
    "/datasets/fetch-nasdaq-equity",
    response_model=QuantDatasetResponse,
    status_code=201,
)
def fetch_nasdaq_equity_dataset(
    body: QuantNasdaqEquityFetchRequest, context: Ctx
) -> dict[str, Any]:
    cutoff = datetime.now(tz=UTC).date() - timedelta(days=1)
    start = cutoff - timedelta(days=body.lookback_days)
    try:
        fetched = _nasdaq_market_data_client().fetch_daily_bars(
            symbol=body.symbol,
            from_date=start,
            to_date=cutoff,
            limit=MAX_HISTORY_LIMIT,
        )
        if fetched.bar_count < 252:
            raise ValueError("Nasdaq history returned fewer than 252 closed daily bars.")
        history_reference = fetched.source_reference
        info_reference = f"nasdaq:{body.symbol}:info?assetclass=stocks"
        dividends_reference = f"nasdaq:{body.symbol}:dividends?assetclass=stocks"
        splits_reference = "nasdaq:calendar/splits"
        record = _store().import_dataset_csv(
            workspace_id=context.workspace_id,
            name=body.name or f"{body.symbol} Nasdaq daily",
            symbol=body.symbol,
            csv_text=fetched.csv_text,
            source_kind="provider_fetch",
            source_name=f"Nasdaq historical quotes · {fetched.company_name}",
            source_reference=history_reference,
            provider_id="nasdaq_equity",
            provider_response_digest=fetched.historical_response_digest,
            provider_response_attestations=(
                QuantProviderResponseAttestation(
                    kind="daily_bars",
                    digest=fetched.historical_response_digest,
                    source_reference=history_reference,
                ),
                QuantProviderResponseAttestation(
                    kind="instrument_info",
                    digest=fetched.info_response_digest,
                    source_reference=info_reference,
                ),
                QuantProviderResponseAttestation(
                    kind="dividends",
                    digest=fetched.dividends_response_digest,
                    source_reference=dividends_reference,
                ),
                QuantProviderResponseAttestation(
                    kind="splits",
                    digest=fetched.splits_response_digest,
                    source_reference=splits_reference,
                ),
            ),
            corporate_actions_attestation=QuantCorporateActionsAttestation(
                dividends_status="retrieved_unverified",
                splits_status="retrieved_unverified",
                coverage_start=fetched.dividend_coverage_start,
                coverage_end=fetched.dividend_coverage_end,
                dividend_coverage_start=fetched.dividend_coverage_start,
                dividend_coverage_end=fetched.dividend_coverage_end,
                split_coverage_start=fetched.split_coverage_start,
                split_coverage_end=fetched.split_coverage_end,
                split_snapshot_as_of=fetched.split_snapshot_as_of,
                split_completeness_status="current_snapshot_only",
                split_reconciliation_status="not_attempted",
                dividend_event_count=fetched.dividend_row_count,
                split_event_count=fetched.split_event_count,
                split_events=tuple(
                    QuantSplitEventSummary(
                        effective_date=event.execution_date,
                        ratio_numerator=Decimal(event.ratio.split(":", maxsplit=1)[0]),
                        ratio_denominator=Decimal(event.ratio.split(":", maxsplit=1)[1]),
                    )
                    for event in fetched.split_events
                ),
                note=(
                    "Dividend rows were retrieved from Nasdaq and retained as response evidence; "
                    "split events are a current/future calendar snapshot only, not proof of "
                    "historical completeness, and prices remain unadjusted."
                ),
            ),
            price_adjustment_verification_status="not_applicable",
            retrieved_at=fetched.retrieved_at,
            requested_limit=MAX_HISTORY_LIMIT,
            returned_bar_count=fetched.bar_count,
            dropped_incomplete_count=0,
            normalization_note=(
                "Nasdaq dollar and thousands separators were removed; MM/DD/YYYY dates were "
                "normalized to ISO order. Prices remain unadjusted and dividends were not "
                "applied to OHLCV rows. Split evidence is a point-in-time calendar snapshot."
            ),
            attestation_status="provider_retrieved",
            market_calendar="XNAS",
            time_zone="America/New_York",
            price_adjustment="unadjusted",
        )
    except (NasdaqMarketDataError, ValueError) as exc:
        raise invalid_state(str(exc)) from exc
    return QuantDatasetResponse.model_validate(_store().to_dataset_response(record)).model_dump(
        mode="json"
    )


@router.get("/datasets", response_model=list[QuantDatasetResponse])
def list_datasets(context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    return [
        QuantDatasetResponse.model_validate(store.to_dataset_response(record)).model_dump(
            mode="json"
        )
        for record in store.list_datasets(workspace_id=context.workspace_id)
    ]


@router.get("/datasets/{dataset_id}/preview", response_model=QuantDatasetPreviewResponse)
def get_dataset_preview(
    dataset_id: str,
    context: Ctx,
    max_points: int = Query(default=240, ge=50, le=400),
) -> dict[str, Any]:
    preview = _store().dataset_preview(
        workspace_id=context.workspace_id,
        dataset_id=dataset_id,
        max_points=max_points,
    )
    return QuantDatasetPreviewResponse.model_validate(preview).model_dump(mode="json")


@router.post(
    "/datasets/v2/import-csv",
    response_model=QuantMarketDatasetV2Response,
    status_code=201,
)
def import_market_dataset_v2_csv(
    body: QuantMarketDatasetV2ImportRequest, context: Ctx
) -> dict[str, Any]:
    try:
        record = _store().import_market_dataset_v2_csv(
            workspace_id=context.workspace_id,
            name=body.name,
            symbol=body.symbol,
            interval=body.interval,
            csv_text=body.csv_text,
            file_name=body.file_name,
            source_name=body.source_name,
            source_reference=body.source_reference,
        )
    except ValueError as exc:
        raise invalid_state(str(exc)) from exc
    return QuantMarketDatasetV2Response.model_validate(
        _store().to_market_dataset_v2_response(record)
    ).model_dump(mode="json")


@router.get("/connectors", response_model=list[QuantConnectorDirectoryResponse])
def list_quant_connectors(context: Ctx) -> list[dict[str, Any]]:
    del context
    connector = QuantConnectorDirectoryResponse(
        data_authenticity=DataAuthenticity.GENERATED,
        connector_id=KRAKEN_SPOT_CONNECTOR_VERSION,
        provider="kraken_spot",
        display_name="Kraken Spot public OHLC",
        source_kind="market_bars",
        supported_symbols=("BTCUSD", "BTCUSDT", "ETHUSD", "ETHUSDT"),
        supported_intervals=("4h", "1D"),
        minimum_recent_bars={"4h": 548, "1D": 252},
        maximum_recent_bars=719,
        fetch_endpoint="/v1/quant/connectors/kraken-spot-ohlc-v1/fetch",
        connector_version=KRAKEN_SPOT_CONNECTOR_VERSION,
        source_terms_url=KRAKEN_SPOT_TERMS_REFERENCE,
        source_documentation_url=KRAKEN_SPOT_DOCUMENTATION_REFERENCE,
    )
    return [connector.model_dump(mode="json")]


@router.post(
    "/connectors/kraken-spot-ohlc-v1/fetch",
    response_model=QuantMarketDatasetV2Response,
    status_code=201,
)
def fetch_market_dataset_v2_kraken(
    body: QuantKrakenSpotFetchRequest, context: Ctx
) -> dict[str, Any]:
    try:
        fetched = _kraken_market_data_v2_client().fetch_market_bars(
            symbol=body.symbol,
            interval=body.interval,
            limit=body.limit,
        )
        evidence = QuantMarketDatasetEvidence(
            source_kind=QuantMarketDataProvenance.PROVIDER_FETCH,
            source_name="Kraken Spot public OHLC",
            source_reference=fetched.evidence.source_reference,
            retrieved_at_utc=fetched.evidence.retrieved_at_utc,
            requested_bar_count=fetched.evidence.requested_bar_count,
            returned_bar_count=fetched.evidence.returned_bar_count,
            retained_bar_count=fetched.evidence.retained_bar_count,
            closed_dropped_count=fetched.evidence.closed_dropped_count,
            deduplicated_count=fetched.evidence.deduplicated_count,
            page_raw_sha256=fetched.evidence.page_raw_sha256,
            batch_digest=fetched.evidence.batch_digest,
            termination_reason=fetched.evidence.termination_reason,
            target_satisfied=fetched.evidence.target_satisfied,
            normalizer_version=fetched.evidence.normalizer_version,
            connector_version=fetched.evidence.connector_version,
            source_request_digest=fetched.evidence.source_request_digest,
            terms_reference=fetched.evidence.terms_reference,
        )
        quality = QuantMarketDatasetCadenceQuality(
            status="blocked" if fetched.quality.status == "blocked" else "accepted",
            cadence_gap_count=fetched.quality.cadence_gap_count,
            normalization_note=fetched.quality.normalization_note,
        )
        record = _store().import_market_dataset_v2(
            workspace_id=context.workspace_id,
            name=body.name or f"{body.symbol} Kraken Spot {body.interval.value}",
            dataset=fetched.dataset,
            evidence=evidence,
            quality=quality,
        )
    except (KrakenMarketDataV2Error, ValueError) as exc:
        raise invalid_state(str(exc)) from exc
    return QuantMarketDatasetV2Response.model_validate(
        _store().to_market_dataset_v2_response(record)
    ).model_dump(mode="json")


@router.post(
    "/datasets/v2/fetch-binance",
    response_model=QuantMarketDatasetV2Response,
    status_code=201,
)
def fetch_market_dataset_v2_binance(
    body: QuantMarketBinanceFetchRequest, context: Ctx
) -> dict[str, Any]:
    try:
        fetched = _binance_market_data_v2_client().fetch_market_bars(
            symbol=body.symbol,
            interval=body.interval,
            limit=body.limit,
        )
        evidence = QuantMarketDatasetEvidence(
            source_kind=QuantMarketDataProvenance.PROVIDER_FETCH,
            source_name="Binance Spot public market data",
            source_reference=fetched.evidence.source_reference,
            retrieved_at_utc=fetched.evidence.retrieved_at_utc,
            requested_bar_count=fetched.evidence.requested_bar_count,
            returned_bar_count=fetched.evidence.returned_bar_count,
            retained_bar_count=fetched.evidence.retained_bar_count,
            closed_dropped_count=fetched.evidence.closed_dropped_count,
            deduplicated_count=fetched.evidence.deduplicated_count,
            page_raw_sha256=fetched.evidence.page_raw_sha256,
            batch_digest=fetched.evidence.batch_digest,
            termination_reason=fetched.evidence.termination_reason.value,
            target_satisfied=fetched.evidence.target_satisfied,
            normalizer_version=fetched.evidence.normalizer_version,
        )
        quality = QuantMarketDatasetCadenceQuality(
            status="blocked" if fetched.quality.status == "blocked" else "accepted",
            cadence_gap_count=fetched.quality.cadence_gap_count,
            normalization_note=fetched.quality.normalization_note,
        )
        record = _store().import_market_dataset_v2(
            workspace_id=context.workspace_id,
            name=body.name or f"{body.symbol} Binance Spot {body.interval.value}",
            dataset=fetched.dataset,
            evidence=evidence,
            quality=quality,
        )
    except (BinanceMarketDataV2Error, ValueError) as exc:
        raise invalid_state(str(exc)) from exc
    return QuantMarketDatasetV2Response.model_validate(
        _store().to_market_dataset_v2_response(record)
    ).model_dump(mode="json")


@router.get("/datasets/v2", response_model=list[QuantMarketDatasetV2Response])
def list_market_datasets_v2(context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    return [
        QuantMarketDatasetV2Response.model_validate(
            store.to_market_dataset_v2_response(record)
        ).model_dump(mode="json")
        for record in store.list_market_datasets_v2(workspace_id=context.workspace_id)
    ]


@router.get("/datasets/v2/{dataset_id}/preview", response_model=QuantMarketDatasetV2PreviewResponse)
def get_market_dataset_v2_preview(
    dataset_id: str,
    context: Ctx,
    max_points: int = Query(default=240, ge=1, le=400),
) -> dict[str, Any]:
    preview = _store().market_dataset_v2_preview(
        workspace_id=context.workspace_id,
        dataset_id=dataset_id,
        max_points=max_points,
    )
    return QuantMarketDatasetV2PreviewResponse.model_validate(preview).model_dump(mode="json")


@router.get("/datasets/v2/{dataset_id}", response_model=QuantMarketDatasetV2Response)
def get_market_dataset_v2(dataset_id: str, context: Ctx) -> dict[str, Any]:
    store = _store()
    record = store.get_market_dataset_v2(workspace_id=context.workspace_id, dataset_id=dataset_id)
    return QuantMarketDatasetV2Response.model_validate(
        store.to_market_dataset_v2_response(record)
    ).model_dump(mode="json")


@router.post("/market-runs", response_model=QuantMarketRunV2Response, status_code=201)
def create_market_run(body: QuantMarketRunV2CreateRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    store.validate_market_run_create(
        workspace_id=context.workspace_id,
        project_id=str(body.project_id),
        expected_project_row_version=body.expected_project_row_version,
        dataset_id=body.dataset_id,
        research_start_utc=body.research_start_utc,
        research_end_utc=body.research_end_utc,
        parent_run_id=str(body.parent_run_id) if body.parent_run_id else None,
        seed_candidate_id=str(body.seed_candidate_id) if body.seed_candidate_id else None,
        refinement_reason=body.refinement_reason,
    )
    run = store.create_market_run(
        workspace_id=context.workspace_id,
        project_id=str(body.project_id),
        question=body.question,
        mode=body.mode,
        expected_project_row_version=body.expected_project_row_version,
        agent_plan=_generate_agent_plan(body.question),
        dataset_id=body.dataset_id,
        research_start_utc=body.research_start_utc,
        research_end_utc=body.research_end_utc,
        parent_run_id=str(body.parent_run_id) if body.parent_run_id else None,
        seed_candidate_id=str(body.seed_candidate_id) if body.seed_candidate_id else None,
        refinement_reason=body.refinement_reason,
        research_loop=body.research_loop,
    )
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.get("/market-runs", response_model=list[QuantMarketRunV2Response])
def list_market_runs(
    context: Ctx,
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    store = _store()
    runs = store.list_market_runs(
        workspace_id=context.workspace_id,
        project_id=str(project_id) if project_id else None,
    )
    return [
        QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
            mode="json"
        )
        for run in runs[:limit]
    ]


@router.get("/market-runs/{run_id}", response_model=QuantMarketRunV2Response)
def get_market_run(run_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.get_market_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.post(
    "/market-runs/{run_id}/approve-plan",
    response_model=QuantMarketRunV2Response,
)
def approve_market_run_plan(
    run_id: UUID, body: QuantPlanApproveRequest, context: Ctx
) -> dict[str, Any]:
    store = _store()
    run = store.approve_market_run_plan(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        reason=body.reason,
    )
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.post(
    "/market-runs/{run_id}/request-plan-changes",
    response_model=QuantMarketRunV2Response,
)
def request_market_run_plan_changes(
    run_id: UUID, body: QuantPlanChangesRequest, context: Ctx
) -> dict[str, Any]:
    store = _store()
    research_goal = store.prepare_market_run_plan_changes(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
    )
    run = store.request_market_run_plan_changes(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        change_request=body.change_request,
        agent_plan=(
            _generate_revised_agent_plan(research_goal, body.change_request)
            if research_goal is not None
            else None
        ),
    )
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.post("/market-runs/{run_id}/cancel", response_model=QuantMarketRunV2Response)
def cancel_market_run(run_id: UUID, body: QuantRunCancelRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.cancel_market_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.post(
    "/market-runs/{run_id}/retry",
    response_model=QuantMarketRunV2Response,
    status_code=201,
)
def retry_market_run(run_id: UUID, body: QuantRunRetryRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.retry_market_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantMarketRunV2Response.model_validate(store.to_market_run_response(run)).model_dump(
        mode="json"
    )


@router.post("/runs", response_model=QuantRunResponse, status_code=201)
def create_run(body: QuantRunCreateRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    store.validate_dataset_for_run(
        workspace_id=context.workspace_id,
        dataset_id=body.dataset_id,
        research_start=body.research_start,
        research_end=body.research_end,
    )
    run = store.create_run(
        workspace_id=context.workspace_id,
        project_id=str(body.project_id),
        question=body.question,
        mode=body.mode,
        expected_project_row_version=body.expected_project_row_version,
        agent_plan=_generate_agent_plan(body.question),
        dataset_id=body.dataset_id,
        research_start=body.research_start,
        research_end=body.research_end,
        parent_run_id=str(body.parent_run_id) if body.parent_run_id else None,
        seed_candidate_id=str(body.seed_candidate_id) if body.seed_candidate_id else None,
        refinement_reason=body.refinement_reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.get("/runs", response_model=list[QuantRunResponse])
def list_runs(
    context: Ctx,
    project_id: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> list[dict[str, Any]]:
    store = _store()
    runs = store.list_legacy_runs(
        workspace_id=context.workspace_id, project_id=str(project_id) if project_id else None
    )
    return [
        QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")
        for run in runs[:limit]
    ]


@router.get("/runs/{run_id}", response_model=QuantRunResponse)
def get_run(run_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.get_legacy_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.get("/runs/{run_id}/workspace-snapshot")
def get_run_workspace_snapshot(run_id: UUID, context: Ctx) -> dict[str, Any]:
    """Return the complete, read-only UI projection for one retained run."""

    snapshot = quant_agent_workspace_snapshot(workspace_id=context.workspace_id, run_id=str(run_id))
    if snapshot is None:  # pragma: no cover - the requested run implies history exists
        raise invalid_state("The requested Quant run has no workspace snapshot.")
    snapshot["run"]["legalCommands"] = []
    snapshot["composerLegalCommands"] = []
    return snapshot


@router.post("/runs/{run_id}/approve-plan", response_model=QuantRunResponse)
def approve_plan(run_id: UUID, body: QuantPlanApproveRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.approve_plan(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/request-plan-changes", response_model=QuantRunResponse)
def request_plan_changes(
    run_id: UUID, body: QuantPlanChangesRequest, context: Ctx
) -> dict[str, Any]:
    store = _store()
    research_goal = store.prepare_plan_changes(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
    )
    run = store.request_plan_changes(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        plan_revision=body.plan_revision,
        change_request=body.change_request,
        agent_plan=(
            _generate_revised_agent_plan(research_goal, body.change_request)
            if research_goal is not None
            else None
        ),
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/cancel", response_model=QuantRunResponse)
def cancel_run(run_id: UUID, body: QuantRunCancelRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.cancel_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.post("/runs/{run_id}/retry", response_model=QuantRunResponse, status_code=201)
def retry_run(run_id: UUID, body: QuantRunRetryRequest, context: Ctx) -> dict[str, Any]:
    store = _store()
    run = store.retry_run(
        workspace_id=context.workspace_id,
        run_id=str(run_id),
        expected_row_version=body.expected_row_version,
        reason=body.reason,
    )
    return QuantRunResponse.model_validate(store.to_run_response(run)).model_dump(mode="json")


@router.get("/runs/{run_id}/events")
def stream_run_events(
    run_id: UUID,
    context: Ctx,
    last_event_id: Annotated[str | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    store = _store()
    run = store.get_run(workspace_id=context.workspace_id, run_id=str(run_id))
    after_sequence = 0
    if last_event_id:
        try:
            after_sequence = next(
                event["sequence"]
                for event in store.events_for_run(
                    workspace_id=context.workspace_id, run_id=str(run_id)
                )
                if event["event_id"] == last_event_id
            )
        except StopIteration:
            if run.market_run_contract_version == QUANT_MARKET_RUN_CONTRACT_VERSION:
                snapshot_url = f"/v1/quant/market-runs/{run.id}"
            elif run.runtime_interval is not None:
                snapshot_url = f"/v1/quant/runs/{run.id}/workspace-snapshot"
            else:
                snapshot_url = f"/v1/quant/runs/{run.id}"
            reset = QuantStreamResetEvent(
                snapshot_url=snapshot_url,
                latest_sequence=run.latest_sequence,
            )
            return StreamingResponse(
                iter([encode_quant_sse(reset)]), media_type="text/event-stream"
            )

    def generate() -> Iterator[str]:
        for event in store.events_for_run(
            workspace_id=context.workspace_id, run_id=str(run_id), after_sequence=after_sequence
        ):
            yield encode_quant_sse(decode_quant_event(event))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/artifacts", response_model=list[QuantArtifactResponse])
def list_artifacts(run_id: UUID, context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    artifacts = store.artifacts_for_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return [
        QuantArtifactResponse.model_validate(store.to_artifact_response(artifact)).model_dump(
            mode="json"
        )
        for artifact in artifacts
    ]


@router.get("/artifacts/{artifact_id}", response_model=QuantArtifactResponse)
def get_artifact(artifact_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    artifact = store.get_artifact(workspace_id=context.workspace_id, artifact_id=str(artifact_id))
    return QuantArtifactResponse.model_validate(store.to_artifact_response(artifact)).model_dump(
        mode="json"
    )


@router.get("/runs/{run_id}/experiments", response_model=list[QuantExperimentResponse])
def list_experiments(run_id: UUID, context: Ctx) -> list[dict[str, Any]]:
    store = _store()
    experiments = store.experiments_for_run(workspace_id=context.workspace_id, run_id=str(run_id))
    return [
        QuantExperimentResponse.model_validate(store.to_experiment_response(experiment)).model_dump(
            mode="json"
        )
        for experiment in experiments
    ]


@router.get("/experiments/{experiment_id}", response_model=QuantExperimentResponse)
def get_experiment(experiment_id: UUID, context: Ctx) -> dict[str, Any]:
    store = _store()
    experiment = store.get_experiment(
        workspace_id=context.workspace_id, experiment_id=str(experiment_id)
    )
    return QuantExperimentResponse.model_validate(
        store.to_experiment_response(experiment)
    ).model_dump(mode="json")
