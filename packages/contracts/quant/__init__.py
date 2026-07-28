"""Quant surface contracts."""

# ruff: noqa: F401 - this module intentionally re-exports the public contract surface.
# pyright: reportUnusedImport=false, reportUnsupportedDunderAll=false

from .agent import (
    CreateCandidateArguments,
    FinishResearchArguments,
    QuantAgentAction,
    QuantAgentDecision,
    QuantAgentPlan,
    QuantAgentPlanStep,
    QuantEvidenceReplanDecision,
    QuantResearchDecision,
    QuantResearchDecisionDeviation,
    QuantStrategyScopeDecision,
    ReviseCandidateArguments,
    RunBacktestArguments,
)
from .context import (
    QuantAgentBudget,
    QuantAgentCandidateContext,
    QuantAgentComparisonCandidateEvidence,
    QuantAgentComparisonContext,
    QuantAgentContext,
    QuantExecutablePlanContext,
    QuantIterationCandidateFeedback,
    QuantIterationDeltas,
    QuantIterationFeedback,
    QuantIterationImprovementReference,
    QuantIterationMetrics,
    QuantIterationNoveltyConstraint,
    QuantIterationRemainingBudget,
    QuantIterationStopSignal,
    QuantIterationTrainingSplit,
    QuantIterationWalkForwardAggregate,
    QuantRefinementSeedCandidate,
    QuantRefinementSeedContext,
    QuantResearchMemoryCandidate,
    QuantResearchMemoryContext,
    QuantResearchMemorySource,
)
from .csv_market_data import (
    QUANT_MARKET_OHLCV_CSV_PARSER_VERSION,
    parse_market_ohlcv_csv,
)
from .csv_ohlcv import QUANT_OHLCV_CSV_PARSER_VERSION, parse_ohlcv_csv
from .data import (
    QUANT_DAILY_BAR_SCHEMA_VERSION,
    QuantDailyBar,
    QuantDailyBarDataset,
    QuantDailyBarInterval,
    QuantDatasetProvenance,
)
from .enums import (
    QuantArtifactKind,
    QuantArtifactReviewStatus,
    QuantExperimentVerdict,
    QuantPlanDecision,
    QuantProjectStatus,
    QuantRunEventType,
    QuantRunMode,
    QuantRunState,
    QuantStreamControlEventType,
    assert_quant_enum_compatibility,
)
from .events import (
    QUANT_EVENT_PERSISTENCE_TO_WIRE,
    QUANT_EVENT_SAFE_COPY,
    UNKNOWN_EVENT_SAFE_SUMMARY,
    QuantRunEvent,
    QuantRunEventPayload,
    QuantStreamResetEvent,
    UnknownQuantRunEvent,
    decode_quant_event,
    encode_quant_heartbeat,
    encode_quant_sse,
    safe_event_copy,
)
from .learning import (
    QUANT_LEARNING_TRACE_SCHEMA_VERSION,
    QUANT_REPAIR_MEMORY_MAX_ENTRIES,
    QUANT_REPAIR_MEMORY_MAX_SOURCE_TRACES,
    QUANT_REPAIR_MEMORY_REUSE_SCHEMA_VERSION,
    QUANT_REPAIR_MEMORY_SCHEMA_VERSION,
    QuantLearningEventRef,
    QuantLearningFieldDelta,
    QuantLearningTrace,
    QuantLearningViolation,
    QuantRepairMemory,
    QuantRepairMemoryEntry,
    QuantRepairMemoryReuseReceipt,
    QuantToolIdentity,
)
from .market_data import (
    EXCHANGE_MARKET_CALENDARS,
    QUANT_MARKET_BAR_SCHEMA_VERSION,
    NonNegativeMarketVolume,
    PositiveMarketPrice,
    QuantBarInterval,
    QuantMarketBar,
    QuantMarketBarDataset,
    QuantMarketCalendar,
    QuantMarketDataProvenance,
    QuantMarketDatasetCadenceQuality,
    QuantMarketDatasetEvidence,
    QuantMarketSession,
    daily_bar_dataset_to_market_dataset,
    market_bar_label_is_consistent,
    market_bar_transition_is_consistent,
    market_calendar_metadata,
    periods_per_year_for,
)
from .quality import (
    QUANT_DATA_QUALITY_POLICY_VERSION,
    QUANT_DATA_QUALITY_SCHEMA_VERSION,
    QuantDataQualityIssue,
    QuantDatasetDataQuality,
    assess_daily_bar_quality,
)
from .robustness import (
    QuantRobustnessArtifactIdentity,
    QuantRobustnessCandidateIdentity,
    QuantRobustnessCostScenario,
    QuantRobustnessDatasetIdentity,
    QuantRobustnessMetrics,
    QuantRobustnessParameterNeighbor,
    QuantRobustnessSensitivity,
    QuantRobustnessTrainingSplitIdentity,
)
from .schemas import (
    QUANT_MARKET_RUN_CONTRACT_VERSION,
    QuantArtifactResponse,
    QuantBinanceSpotFetchRequest,
    QuantConnectorDirectoryResponse,
    QuantCorporateActionsAttestation,
    QuantDatasetImportRequest,
    QuantDatasetPreviewBar,
    QuantDatasetPreviewResponse,
    QuantDatasetResponse,
    QuantDatasetSourceMetadata,
    QuantExperimentResponse,
    QuantFixtureCommandRequest,
    QuantKrakenSpotFetchRequest,
    QuantMarketBinanceFetchRequest,
    QuantMarketDatasetV2ImportRequest,
    QuantMarketDatasetV2PreviewResponse,
    QuantMarketDatasetV2Response,
    QuantMarketPlanApproveRequest,
    QuantMarketRunV2CreateRequest,
    QuantMarketRunV2Response,
    QuantNasdaqEquityFetchRequest,
    QuantPlanApproveRequest,
    QuantPlanChangesRequest,
    QuantPlanDecisionResponse,
    QuantProjectCreateRequest,
    QuantProjectResponse,
    QuantProviderResponseAttestation,
    QuantRunCancelRequest,
    QuantRunCreateRequest,
    QuantRunResponse,
    QuantRunRetryRequest,
    QuantSplitEventSummary,
    QuantStrategyEvidenceBundleExportRequest,
    QuantStrategyEvidenceBundleExportResponse,
    QuantStrategyReportExportRequest,
    QuantStrategyReportExportResponse,
    QuantStrategyReportMarkdownExportRequest,
    QuantStrategyReportMarkdownExportResponse,
    QuantWorkspaceTradeProjection,
)
from .series import (
    QuantResearchLoopPolicy,
    QuantResearchSeriesContext,
    QuantResearchSeriesControl,
    QuantResearchSeriesDecision,
    research_loop_policy_digest,
)
from .tools import (
    QUANT_AGENT_TOOL_REGISTRY,
    QUANT_AGENT_TOOL_REGISTRY_VERSION,
    QuantEmptyToolArguments,
    QuantToolObservation,
    QuantToolRepair,
    QuantToolRepairViolation,
    quant_tool_identity,
    quant_tool_input_model,
    quant_tool_version,
    validate_quant_tool_arguments,
)

# Robustness sensitivity and verified-learning state are immutable internal
# contracts, not request/response schemas. Keep explicit imports available to
# the service while excluding them from the REST/OpenAPI registry.
__all__ = [
    name
    for name in globals()
    if not name.startswith("_")
    and not name.startswith("QuantRobustness")
    and not name.startswith("QuantLearning")
    and not name.startswith("QuantRepairMemory")
    and name not in {"QuantEmptyToolArguments", "QuantToolIdentity"}
]
