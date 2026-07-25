import type {
  BacktestMetrics,
  CandidateVerdict,
  DatasetCsvSource,
  DatasetDataQuality,
  DatasetProviderFetchSource,
  DatasetSnapshot,
  DatasetSource,
  GeneralizationMetrics,
  GeneralizationSplit,
  MarketBar,
  QuantArtifact,
  QuantArtifactType,
  QuantAuthenticity,
  QuantCandidate,
  QuantCandidateEvolution,
  QuantCommand,
  QuantCompatibility,
  QuantKernelCheck,
  QuantKernelResult,
  QuantLimits,
  QuantLiveCandidate,
  QuantLiveResearch,
  QuantMarketDatasetQuality,
  QuantOwner,
  QuantPlanStep,
  QuantExecutableResearchPlan,
  QuantResearchMemoryProjection,
  QuantResearchMode,
  QuantResearchProject,
  QuantResearchRun,
  QuantResearchScope,
  QuantRunEvent,
  QuantRunState,
  QuantStrategyScopeDecision,
  QuantStepStatus,
  ResearchGeneralization,
  ResearchReport,
  ResearchWalkForward,
  QuantRobustnessMetrics,
  QuantRobustnessSensitivity,
  StrategyPerformancePoint,
  StrategyPerformanceSeries,
  TradeRecord,
  QuantWorkspaceSnapshot,
  WalkForwardFold,
  WalkForwardMarketRegime,
  WalkForwardRegimeSummary,
} from './quant-domain';
import { assertQuantMarketDatasetCadence } from './quant-market-parser';

/**
 * The workspace snapshot currently has no explicit schema field, so the
 * top-level `version` string is used as the compatibility discriminator.
 * Phase 1A is the current server-owned projection. The Phase 0 fixture remains
 * readable so checked E2E fixtures and offline diagnostics do not break.
 */
export const QUANT_WORKSPACE_SUPPORTED_VERSION = 'Phase 1A · autonomous-agent-v1';
export const QUANT_WORKSPACE_SUPPORTED_VERSIONS = new Set([
  QUANT_WORKSPACE_SUPPORTED_VERSION,
  'Phase 0 · server-fixture-v1',
]);

export interface QuantWorkspaceSnapshotParseResult {
  snapshot: QuantWorkspaceSnapshot | null;
  compatibility: QuantCompatibility;
}

export class QuantWorkspaceCompatibilityError extends Error {
  readonly compatibility: QuantCompatibility;

  constructor(compatibility: QuantCompatibility) {
    const summary = compatibility.warnings.length
      ? compatibility.warnings.join('; ')
      : `Unsupported workspace snapshot schema version "${compatibility.schemaVersion}"`;
    super(`Quant workspace snapshot is not supported: ${summary}`);
    this.name = 'QuantWorkspaceCompatibilityError';
    this.compatibility = compatibility;
  }
}

type Ctx = {
  missingFields: string[];
  unknownFields: string[];
  warnings: string[];
};

function emptyCtx(): Ctx {
  return { missingFields: [], unknownFields: [], warnings: [] };
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isStrictDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const date = new Date(`${value}T00:00:00.000Z`);
  return !Number.isNaN(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function isStrictUtcTimestamp(value: string): boolean {
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|\+00:00)$/.exec(value);
  if (!parts) return false;
  const [year, month, day, hour, minute, second] = parts.slice(1, 7).map(Number);
  const date = new Date(0);
  date.setUTCFullYear(year!, month! - 1, day!);
  date.setUTCHours(hour!, minute!, second!, 0);
  return date.getUTCFullYear() === year
    && date.getUTCMonth() === month! - 1
    && date.getUTCDate() === day
    && date.getUTCHours() === hour
    && date.getUTCMinutes() === minute
    && date.getUTCSeconds() === second;
}

function joinPath(prefix: string, key: string | number): string {
  return prefix === '' ? String(key) : `${prefix}.${key}`;
}

function requiredString(value: unknown, path: string, ctx: Ctx): string | null {
  if (typeof value === 'string') return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a string`);
  return null;
}

function requiredNonEmptyString(value: unknown, path: string, ctx: Ctx): string | null {
  if (typeof value === 'string' && value.length > 0) return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a non-empty string`);
  return null;
}

function optionalString(value: unknown, path: string, ctx: Ctx): string | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === 'string') return value;
  ctx.warnings.push(`${path} has an invalid string value and will be ignored`);
  return undefined;
}

function nullableString(value: unknown, path: string, ctx: Ctx): string | null | undefined {
  if (value === null) return null;
  if (typeof value === 'string') return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a string or null`);
  return undefined;
}

function requiredFiniteNumber(value: unknown, path: string, ctx: Ctx): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a finite number`);
  return null;
}

function requiredNonNegativeInteger(value: unknown, path: string, ctx: Ctx): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value >= 0) return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a non-negative integer`);
  return null;
}

function requiredPositiveInteger(value: unknown, path: string, ctx: Ctx): number | null {
  if (typeof value === 'number' && Number.isInteger(value) && value > 0) return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a positive integer`);
  return null;
}

function optionalFiniteNumber(value: unknown, path: string, ctx: Ctx): number | undefined {
  if (value === undefined || value === null) return undefined;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  ctx.warnings.push(`${path} has an invalid number value and will be ignored`);
  return undefined;
}

function nullableFiniteNumber(value: unknown, path: string, ctx: Ctx): number | null | undefined {
  if (value === null) return null;
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a finite number or null`);
  return undefined;
}

function requiredBoolean(value: unknown, path: string, ctx: Ctx): boolean | null {
  if (typeof value === 'boolean') return value;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be a boolean`);
  return null;
}

function requiredFalse(value: unknown, path: string, ctx: Ctx): false | null {
  if (value === false) return false;
  ctx.missingFields.push(path);
  ctx.warnings.push(`${path} must be false`);
  return null;
}

function requiredEnum<T extends string>(allowed: readonly T[]) {
  return (value: unknown, path: string, ctx: Ctx): T | null => {
    if (typeof value !== 'string') {
      ctx.missingFields.push(path);
      ctx.warnings.push(`${path} must be a string`);
      return null;
    }
    if (allowed.includes(value as T)) return value as T;
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} has unsupported value "${value}"`);
    return null;
  };
}

function requiredEnumWithUnknown<T extends string>(allowed: readonly T[]) {
  return (value: unknown, path: string, ctx: Ctx): T | 'unknown' | null => {
    if (typeof value !== 'string') {
      ctx.missingFields.push(path);
      ctx.warnings.push(`${path} must be a string`);
      return null;
    }
    if (allowed.includes(value as T)) return value as T;
    ctx.warnings.push(`${path} has unrecognized value "${value}"; mapped to 'unknown'`);
    return 'unknown';
  };
}

function optionalEnum<T extends string>(allowed: readonly T[]) {
  return (value: unknown, path: string, ctx: Ctx): T | undefined => {
    if (value === undefined || value === null) return undefined;
    if (typeof value === 'string' && allowed.includes(value as T)) return value as T;
    ctx.warnings.push(`${path} has an unrecognized enum value and will be ignored`);
    return undefined;
  };
}

function requiredLiteral<T extends string>(literal: T) {
  return (value: unknown, path: string, ctx: Ctx): T | null => {
    if (value === literal) return literal;
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} must be ${literal}`);
    return null;
  };
}

function requiredArray<T>(parseItem: (value: unknown, path: string, ctx: Ctx) => T | null) {
  return (value: unknown, path: string, ctx: Ctx): T[] | null => {
    if (!Array.isArray(value)) {
      ctx.missingFields.push(path);
      ctx.warnings.push(`${path} must be an array`);
      return null;
    }
    const out: T[] = [];
    for (let i = 0; i < value.length; i++) {
      const item = parseItem(value[i], joinPath(path, i), ctx);
      if (item === null) {
        ctx.missingFields.push(joinPath(path, i));
        return null;
      }
      out.push(item);
    }
    return out;
  };
}

function optionalArray<T>(parseItem: (value: unknown, path: string, ctx: Ctx) => T | null | undefined) {
  return (value: unknown, path: string, ctx: Ctx): T[] | undefined => {
    if (value === undefined || value === null) return undefined;
    if (!Array.isArray(value)) {
      ctx.warnings.push(`${path} has an invalid array value and will be ignored`);
      return undefined;
    }
    const out: T[] = [];
    for (let i = 0; i < value.length; i++) {
      const item = parseItem(value[i], joinPath(path, i), ctx);
      if (item == null) continue;
      out.push(item);
    }
    return out;
  };
}

function parseObject<T>(
  value: unknown,
  path: string,
  ctx: Ctx,
  knownKeys: Set<string>,
  build: (obj: Record<string, unknown>, path: string) => T | null,
): T | null {
  if (!isPlainObject(value)) {
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} must be an object`);
    return null;
  }
  for (const key of Object.keys(value)) {
    if (!knownKeys.has(key)) ctx.unknownFields.push(joinPath(path, key));
  }
  return build(value, path);
}

function parseStrictObject<T>(
  value: unknown,
  path: string,
  ctx: Ctx,
  knownKeys: Set<string>,
  build: (obj: Record<string, unknown>, path: string) => T | null,
): T | null {
  if (!isPlainObject(value)) {
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} must be an object`);
    return null;
  }
  const unknownKeys = Object.keys(value).filter((key) => !knownKeys.has(key));
  if (unknownKeys.length > 0) {
    for (const key of unknownKeys) ctx.unknownFields.push(joinPath(path, key));
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} contains unsupported fields`);
    return null;
  }
  return build(value, path);
}

const AUTHENTICITY_VALUES: readonly QuantAuthenticity[] = ['synthetic_fixture', 'imported', 'collected'];
const RESEARCH_MODES: readonly QuantResearchMode[] = ['ask', 'plan', 'auto_research'];
const RUN_STATES: readonly Exclude<QuantRunState, 'unknown'>[] = [
  'draft',
  'planning',
  'waiting_plan_approval',
  'queued',
  'loading_data',
  'generating_candidates',
  'running_experiments',
  'repairing',
  'validating',
  'generating_report',
  'waiting_for_review',
  'completed',
  'failed',
  'cancelled',
];
const OWNERS: readonly QuantOwner[] = ['user', 'system', 'agent', 'validator'];
const STEP_STATUSES: readonly QuantStepStatus[] = ['pending', 'active', 'waiting', 'completed', 'failed', 'skipped'];
const CANDIDATE_VERDICTS: readonly CandidateVerdict[] = ['promising', 'inconclusive', 'rejected', 'invalid'];
const ARTIFACT_TYPES: readonly QuantArtifactType[] = [
  'research_scope',
  'dataset_snapshot',
  'strategy_spec',
  'backtest_result',
  'equity_curve',
  'trade_log',
  'validation_report',
  'research_report',
  'execution_log',
];
const ARTIFACT_STATUSES = ['draft', 'ready', 'reviewed', 'rejected'] as const;
const COMMANDS: readonly QuantCommand[] = [
  'ask',
  'generate_plan',
  'start_auto_research',
  'run_fixture',
  'approve_plan',
  'request_plan_changes',
  'approve_execution',
  'cancel_run',
  'retry_run',
  'complete_review',
  'start_new_run',
];
const GENERALIZATION_STATUSES = ['pass', 'fail', 'inconclusive', 'not_evaluated'] as const;
const WALK_FORWARD_STATUSES = ['completed', 'not_evaluated'] as const;
const WALK_FORWARD_FOLD_STATUSES = ['pass', 'fail', 'inconclusive', 'not_evaluated'] as const;
const KERNEL_CHECK_STATUSES = ['available', 'verified'] as const;
const MARKERS = ['entry', 'exit', 'market', 'earnings', 'policy', 'macro'] as const;
const CALENDAR_VALUES = ['unknown', 'weekday', '24x7', 'XNYS', 'XNAS', 'XSHG', 'XSHE'] as const;
const PRICE_ADJUSTMENTS = ['unknown', 'unadjusted', 'split_adjusted', 'total_return_adjusted'] as const;
const DATASET_CONTRACTS = ['legacy-daily-v1', 'market-v2'] as const;
const RUN_CONTRACTS = ['legacy-daily-v1', 'market-v2-private', 'market-v2-public'] as const;
const CANDIDATE_FAMILIES = ['sma_crossover', 'rsi_mean_reversion', 'breakout'] as const;
const MARKET_DATASET_FIELDS = ['periodsPerYear', 'marketCalendar', 'marketSession', 'timeZone', 'runtimeDescriptorDigest', 'sealedSplitDigest', 'recordDigest'] as const;
const MARKET_KERNEL_FIELDS = ['interval', 'periodsPerYear', 'runtimeDescriptorDigest', 'sealedSplitDigest'] as const;
const MARKET_RUN_FIELDS = ['schemaVersion', 'datasetDigest', 'interval', 'periodsPerYear', 'researchStartUtc', 'researchEndUtc', 'runtimeDescriptorDigest', 'sealedSplitDigest'] as const;

function rangeHasTimestamp(value: unknown): boolean {
  if (!isPlainObject(value)) return false;
  return [value.start, value.end].some((item) => typeof item === 'string' && item.includes('T'));
}

function hasMarketSnapshotSignal(obj: Record<string, unknown>): boolean {
  const dataset = isPlainObject(obj.dataset) ? obj.dataset : {};
  const run = isPlainObject(obj.run) ? obj.run : {};
  const scope = isPlainObject(obj.scope) ? obj.scope : {};
  const kernel = isPlainObject(obj.kernelCheck) ? obj.kernelCheck : {};
  const report = isPlainObject(obj.report) ? obj.report : {};
  const generalization = isPlainObject(report.generalization) ? report.generalization : {};
  const split = isPlainObject(generalization.split) ? generalization.split : {};
  return dataset.contract === 'market-v2'
    || dataset.schemaVersion === 'quant-market-bars-v2'
    || run.contract === 'market-v2-private'
    || run.contract === 'market-v2-public'
    || MARKET_RUN_FIELDS.some((key) => run[key] !== undefined)
    || scope.interval === '1h'
    || scope.interval === '4h'
    || dataset.interval === '1h'
    || dataset.interval === '4h'
    || rangeHasTimestamp(scope.dateRange)
    || rangeHasTimestamp(dataset.dateRange)
    || MARKET_DATASET_FIELDS.some((key) => dataset[key] !== undefined)
    || MARKET_KERNEL_FIELDS.some((key) => kernel[key] !== undefined)
    || report.datasetContext !== undefined
    || ['interval', 'periodsPerYear', 'cutoffTimestampUtc', 'rangeStartUtc', 'rangeEndUtc', 'descriptorDigest', 'sealDigest'].some((key) => split[key] !== undefined);
}

function hasExplicitLegacySnapshotSignal(obj: Record<string, unknown>): boolean {
  const dataset = isPlainObject(obj.dataset) ? obj.dataset : {};
  const run = isPlainObject(obj.run) ? obj.run : {};
  return dataset.contract === 'legacy-daily-v1'
    || dataset.schemaVersion === 'quant-daily-bars-v1'
    || run.contract === 'legacy-daily-v1';
}

function parseBacktestMetrics(value: unknown, path: string, ctx: Ctx): BacktestMetrics | null {
  return parseObject(value, path, ctx, new Set(['annualizedReturn', 'maxDrawdown', 'sharpe', 'trades']), (obj) => {
    let ok = true;
    const annualizedReturn = requiredFiniteNumber(obj.annualizedReturn, joinPath(path, 'annualizedReturn'), ctx);
    const maxDrawdown = requiredFiniteNumber(obj.maxDrawdown, joinPath(path, 'maxDrawdown'), ctx);
    const sharpe = requiredFiniteNumber(obj.sharpe, joinPath(path, 'sharpe'), ctx);
    const trades = requiredFiniteNumber(obj.trades, joinPath(path, 'trades'), ctx);
    if (annualizedReturn === null || maxDrawdown === null || sharpe === null || trades === null) ok = false;
    if (!ok) return null;
    return {
      annualizedReturn: annualizedReturn!,
      maxDrawdown: maxDrawdown!,
      sharpe: sharpe!,
      trades: trades!,
    };
  });
}

function parseNullableBacktestMetrics(value: unknown, path: string, ctx: Ctx): BacktestMetrics | null | undefined {
  if (value === null) return null;
  const parsed = parseBacktestMetrics(value, path, ctx);
  return parsed ?? undefined;
}

function parseResearchProject(value: unknown, path: string, ctx: Ctx): QuantResearchProject | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'latestRunId', 'title', 'goal', 'symbol', 'updatedAt', 'statusLabel', 'needsAction']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const latestRunId = optionalString(obj.latestRunId, joinPath(path, 'latestRunId'), ctx);
      const title = requiredString(obj.title, joinPath(path, 'title'), ctx);
      const goal = requiredString(obj.goal, joinPath(path, 'goal'), ctx);
      const symbol = requiredString(obj.symbol, joinPath(path, 'symbol'), ctx);
      const updatedAt = requiredString(obj.updatedAt, joinPath(path, 'updatedAt'), ctx);
      const statusLabel = requiredString(obj.statusLabel, joinPath(path, 'statusLabel'), ctx);
      const needsAction = requiredBoolean(obj.needsAction, joinPath(path, 'needsAction'), ctx);
      if (id === null || title === null || goal === null || symbol === null || updatedAt === null || statusLabel === null || needsAction === null) {
        ok = false;
      }
      if (!ok) return null;
      return {
        id: id!,
        ...(latestRunId ? { latestRunId } : {}),
        title: title!,
        goal: goal!,
        symbol: symbol!,
        updatedAt: updatedAt!,
        statusLabel: statusLabel!,
        needsAction: needsAction!,
      };
    },
  );
}

function parseDateRange(value: unknown, path: string, ctx: Ctx): { start: string; end: string } | null {
  return parseObject(value, path, ctx, new Set(['start', 'end']), (obj) => {
    const start = requiredString(obj.start, joinPath(path, 'start'), ctx);
    const end = requiredString(obj.end, joinPath(path, 'end'), ctx);
    if (start === null || end === null) return null;
    return { start: start!, end: end! };
  });
}

function parseResearchScope(value: unknown, path: string, ctx: Ctx): QuantResearchScope | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['version', 'symbol', 'market', 'interval', 'dateRange', 'benchmark', 'assumptions']),
    (obj) => {
      let ok = true;
      const version = requiredFiniteNumber(obj.version, joinPath(path, 'version'), ctx);
      const symbol = requiredString(obj.symbol, joinPath(path, 'symbol'), ctx);
      const market = requiredString(obj.market, joinPath(path, 'market'), ctx);
      const interval = requiredEnum(['1h', '4h', '1D'] as const)(obj.interval, joinPath(path, 'interval'), ctx);
      const dateRange = parseDateRange(obj.dateRange, joinPath(path, 'dateRange'), ctx);
      const benchmark = requiredString(obj.benchmark, joinPath(path, 'benchmark'), ctx);
      const assumptions = requiredArray(requiredString)(obj.assumptions, joinPath(path, 'assumptions'), ctx);
      if (version === null || symbol === null || market === null || interval === null || dateRange === null || benchmark === null || assumptions === null) {
        ok = false;
      }
      if (!ok) return null;
      return {
        version: version!,
        symbol: symbol!,
        market: market!,
        interval: interval!,
        dateRange: dateRange!,
        benchmark: benchmark!,
        assumptions: assumptions!,
      };
    },
  );
}

function parseResearchRun(value: unknown, path: string, ctx: Ctx): QuantResearchRun | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set([
      'id',
      'rowVersion',
      'attemptNumber',
      'state',
      'mode',
      'currentStepId',
      'latestSequence',
      'startedAt',
      'completedAt',
      'usedExperiments',
      'usedRepairAttempts',
      'agentIteration',
      'maxAgentIterations',
      'provider',
      'model',
      'legalCommands',
      'traceRef',
      'retryOfRunId',
      'continuedFrom',
      'contract',
      'planRevision',
    ]),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const rowVersion = requiredFiniteNumber(obj.rowVersion, joinPath(path, 'rowVersion'), ctx);
      const attemptNumber = requiredFiniteNumber(obj.attemptNumber, joinPath(path, 'attemptNumber'), ctx);
      const state = requiredEnumWithUnknown(RUN_STATES)(obj.state, joinPath(path, 'state'), ctx);
      const mode = requiredEnum(RESEARCH_MODES)(obj.mode, joinPath(path, 'mode'), ctx);
      const currentStepId = requiredString(obj.currentStepId, joinPath(path, 'currentStepId'), ctx);
      const latestSequence = requiredFiniteNumber(obj.latestSequence, joinPath(path, 'latestSequence'), ctx);
      const startedAt = requiredString(obj.startedAt, joinPath(path, 'startedAt'), ctx);
      const completedAt = nullableString(obj.completedAt, joinPath(path, 'completedAt'), ctx);
      const usedExperiments = requiredFiniteNumber(obj.usedExperiments, joinPath(path, 'usedExperiments'), ctx);
      const usedRepairAttempts = requiredFiniteNumber(obj.usedRepairAttempts, joinPath(path, 'usedRepairAttempts'), ctx);
      const agentIteration = requiredFiniteNumber(obj.agentIteration, joinPath(path, 'agentIteration'), ctx);
      const maxAgentIterations = requiredFiniteNumber(obj.maxAgentIterations, joinPath(path, 'maxAgentIterations'), ctx);
      const provider = requiredString(obj.provider, joinPath(path, 'provider'), ctx);
      const model = nullableString(obj.model, joinPath(path, 'model'), ctx);
      const legalCommands = requiredArray(requiredEnum(COMMANDS))(obj.legalCommands, joinPath(path, 'legalCommands'), ctx);
      const traceRef = requiredString(obj.traceRef, joinPath(path, 'traceRef'), ctx);
      const retryOfRunId = optionalString(obj.retryOfRunId, joinPath(path, 'retryOfRunId'), ctx);
      const contract = obj.contract === undefined
        ? 'legacy-daily-v1'
        : requiredEnum(RUN_CONTRACTS)(obj.contract, joinPath(path, 'contract'), ctx);
      const planRevision = optionalFiniteNumber(obj.planRevision, joinPath(path, 'planRevision'), ctx);
      const continuedFrom = obj.continuedFrom === undefined || obj.continuedFrom === null ? undefined : parseObject(
        obj.continuedFrom,
        joinPath(path, 'continuedFrom'),
        ctx,
        new Set(['parentRunId', 'seedCandidateId', 'candidateName', 'sourceQuestion', 'reason']),
        (lineage) => {
          const parentRunId = requiredString(lineage.parentRunId, joinPath(path, 'continuedFrom.parentRunId'), ctx);
          const seedCandidateId = requiredString(lineage.seedCandidateId, joinPath(path, 'continuedFrom.seedCandidateId'), ctx);
          const candidateName = requiredString(lineage.candidateName, joinPath(path, 'continuedFrom.candidateName'), ctx);
          const sourceQuestion = requiredString(lineage.sourceQuestion, joinPath(path, 'continuedFrom.sourceQuestion'), ctx);
          const reason = requiredString(lineage.reason, joinPath(path, 'continuedFrom.reason'), ctx);
          if (parentRunId === null || seedCandidateId === null || candidateName === null || sourceQuestion === null || reason === null) return null;
          return { parentRunId, seedCandidateId, candidateName, sourceQuestion, reason };
        },
      );
      const runAnyNull =
        id === null ||
        rowVersion === null ||
        attemptNumber === null ||
        state === null ||
        mode === null ||
        currentStepId === null ||
        latestSequence === null ||
        startedAt === null ||
        completedAt === undefined ||
        usedExperiments === null ||
        usedRepairAttempts === null ||
        agentIteration === null ||
        maxAgentIterations === null ||
        provider === null ||
        model === undefined ||
        legalCommands === null ||
        traceRef === null ||
        contract === null;
      if (runAnyNull) ok = false;
      if (!ok) return null;
      const run: QuantResearchRun = {
        contract: contract!,
        id: id!,
        rowVersion: rowVersion!,
        attemptNumber: attemptNumber!,
        state: state!,
        mode: mode!,
        currentStepId: currentStepId!,
        latestSequence: latestSequence!,
        startedAt: startedAt!,
        completedAt: completedAt!,
        usedExperiments: usedExperiments!,
        usedRepairAttempts: usedRepairAttempts!,
        agentIteration: agentIteration!,
        maxAgentIterations: maxAgentIterations!,
        provider: provider!,
        model: model!,
        legalCommands: legalCommands!,
        traceRef: traceRef!,
      };
      if (planRevision !== undefined) run.planRevision = planRevision;
      if (retryOfRunId !== undefined) run.retryOfRunId = retryOfRunId;
      if (continuedFrom !== undefined && continuedFrom !== null) run.continuedFrom = continuedFrom;
      return run;
    },
  );
}

function parseLimits(value: unknown, path: string, ctx: Ctx): QuantLimits | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['maxExperiments', 'maxRepairAttempts', 'maxRuntimeMinutes', 'internetAccess', 'arbitraryPython', 'paperTrading']),
    (obj) => {
      let ok = true;
      const maxExperiments = requiredFiniteNumber(obj.maxExperiments, joinPath(path, 'maxExperiments'), ctx);
      const maxRepairAttempts = requiredFiniteNumber(obj.maxRepairAttempts, joinPath(path, 'maxRepairAttempts'), ctx);
      const maxRuntimeMinutes = requiredFiniteNumber(obj.maxRuntimeMinutes, joinPath(path, 'maxRuntimeMinutes'), ctx);
      const internetAccess = requiredFalse(obj.internetAccess, joinPath(path, 'internetAccess'), ctx);
      const arbitraryPython = requiredFalse(obj.arbitraryPython, joinPath(path, 'arbitraryPython'), ctx);
      const paperTrading = requiredFalse(obj.paperTrading, joinPath(path, 'paperTrading'), ctx);
      if (
        maxExperiments === null ||
        maxRepairAttempts === null ||
        maxRuntimeMinutes === null ||
        internetAccess === null ||
        arbitraryPython === null ||
        paperTrading === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      return {
        maxExperiments: maxExperiments!,
        maxRepairAttempts: maxRepairAttempts!,
        maxRuntimeMinutes: maxRuntimeMinutes!,
        internetAccess: internetAccess!,
        arbitraryPython: arbitraryPython!,
        paperTrading: paperTrading!,
      };
    },
  );
}

function parsePlanStep(value: unknown, path: string, ctx: Ctx): QuantPlanStep | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'title', 'description', 'owner', 'status', 'artifactCount', 'humanGate']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const title = requiredString(obj.title, joinPath(path, 'title'), ctx);
      const description = requiredString(obj.description, joinPath(path, 'description'), ctx);
      const owner = requiredEnum(OWNERS)(obj.owner, joinPath(path, 'owner'), ctx);
      const status = requiredEnum(STEP_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const artifactCount = requiredFiniteNumber(obj.artifactCount, joinPath(path, 'artifactCount'), ctx);
      const humanGate = requiredBoolean(obj.humanGate, joinPath(path, 'humanGate'), ctx);
      if (id === null || title === null || description === null || owner === null || status === null || artifactCount === null || humanGate === null) {
        ok = false;
      }
      if (!ok) return null;
      return {
        id: id!,
        title: title!,
        description: description!,
        owner: owner!,
        status: status!,
        artifactCount: artifactCount!,
        humanGate: humanGate!,
      };
    },
  );
}

function parseExecutableResearchPlan(
  value: unknown,
  path: string,
  ctx: Ctx,
): QuantExecutableResearchPlan | null | undefined {
  if (value === undefined || value === null) return undefined;
  return parseStrictObject(
    value,
    path,
    ctx,
    new Set(['candidateFamilies', 'selectionObjective', 'completionCriteria', 'objectiveSummary', 'strategyScope']),
    (obj, objectPath) => {
      const objectiveSummaryPresent = obj.objectiveSummary !== undefined;
      const objectiveSummary = objectiveSummaryPresent
        ? requiredString(obj.objectiveSummary, joinPath(objectPath, 'objectiveSummary'), ctx)
        : undefined;
      const candidateFamilies = requiredArray(requiredEnum(CANDIDATE_FAMILIES))(
        obj.candidateFamilies,
        joinPath(objectPath, 'candidateFamilies'),
        ctx,
      );
      const completionCriteria = requiredArray(requiredString)(
        obj.completionCriteria,
        joinPath(objectPath, 'completionCriteria'),
        ctx,
      );
      const selectionObjective = requiredEnum([
        'risk_adjusted_return',
        'total_return',
        'drawdown_control',
      ] as const)(
        obj.selectionObjective,
        joinPath(objectPath, 'selectionObjective'),
        ctx,
      );
      const strategyScope = parseStrategyScopeDecision(
        obj.strategyScope,
        joinPath(objectPath, 'strategyScope'),
        ctx,
      );
      if (!candidateFamilies || candidateFamilies.length > 3
        || new Set(candidateFamilies).size !== candidateFamilies.length) {
        ctx.missingFields.push(joinPath(objectPath, 'candidateFamilies'));
        ctx.warnings.push(`${joinPath(objectPath, 'candidateFamilies')} must contain no more than 3 unique supported families`);
        return null;
      }
      if (!completionCriteria || completionCriteria.length < 1 || completionCriteria.length > 8
        || completionCriteria.some((item) => !item.trim() || item !== item.trim())) {
        ctx.missingFields.push(joinPath(objectPath, 'completionCriteria'));
        ctx.warnings.push(`${joinPath(objectPath, 'completionCriteria')} must contain 1 to 8 non-empty criteria`);
        return null;
      }
      if (!selectionObjective || objectiveSummary === null || strategyScope === null) return null;
      if (!strategyScope && candidateFamilies.length < 1) {
        ctx.missingFields.push(joinPath(objectPath, 'candidateFamilies'));
        ctx.warnings.push(`${joinPath(objectPath, 'candidateFamilies')} must contain 1 to 3 unique supported families for a legacy plan`);
        return null;
      }
      if (strategyScope?.status === 'unsupported' && candidateFamilies.length !== 0) {
        ctx.missingFields.push(joinPath(objectPath, 'candidateFamilies'));
        ctx.warnings.push(`${joinPath(objectPath, 'candidateFamilies')} must be empty when strategy scope is unsupported`);
        return null;
      }
      if (strategyScope && strategyScope.status !== 'unsupported' && candidateFamilies.length < 1) {
        ctx.missingFields.push(joinPath(objectPath, 'candidateFamilies'));
        ctx.warnings.push(`${joinPath(objectPath, 'candidateFamilies')} must contain 1 to 3 unique supported families for an executable strategy scope`);
        return null;
      }
      return {
        candidateFamilies,
        selectionObjective,
        completionCriteria,
        ...(objectiveSummary !== undefined ? { objectiveSummary } : {}),
        ...(strategyScope !== undefined ? { strategyScope } : {}),
      };
    },
  );
}

function parseStrategyScopeDecision(
  value: unknown,
  path: string,
  ctx: Ctx,
): QuantStrategyScopeDecision | null | undefined {
  if (value === undefined) return undefined;
  return parseStrictObject(
    value,
    path,
    ctx,
    new Set(['schemaVersion', 'status', 'reason', 'proxyDescription', 'excludedBehaviors']),
    (obj, objectPath) => {
      const schemaVersion = requiredEnum(['quant-strategy-scope-v1'] as const)(
        obj.schemaVersion,
        joinPath(objectPath, 'schemaVersion'),
        ctx,
      );
      const status = requiredEnum(['supported', 'bounded_proxy', 'unsupported'] as const)(
        obj.status,
        joinPath(objectPath, 'status'),
        ctx,
      );
      const reason = requiredNonEmptyString(obj.reason, joinPath(objectPath, 'reason'), ctx);
      const proxyDescription = obj.proxyDescription === undefined || obj.proxyDescription === null
        ? undefined
        : requiredNonEmptyString(
          obj.proxyDescription,
          joinPath(objectPath, 'proxyDescription'),
          ctx,
        );
      const excludedBehaviors = requiredArray(requiredNonEmptyString)(
        obj.excludedBehaviors,
        joinPath(objectPath, 'excludedBehaviors'),
        ctx,
      );
      if (!schemaVersion || !status || !reason || proxyDescription === null || !excludedBehaviors) return null;
      if (reason !== reason.trim()
        || (proxyDescription !== undefined && proxyDescription !== proxyDescription.trim())
        || excludedBehaviors.some((item) => item !== item.trim())) {
        ctx.missingFields.push(path);
        ctx.warnings.push(`${path} text fields must be trimmed`);
        return null;
      }
      if (status === 'supported' && (proxyDescription !== undefined || excludedBehaviors.length !== 0)) {
        ctx.missingFields.push(path);
        ctx.warnings.push(`${path} supported decisions cannot declare a proxy or excluded behavior`);
        return null;
      }
      if (status === 'bounded_proxy' && (proxyDescription === undefined || excludedBehaviors.length < 1)) {
        ctx.missingFields.push(path);
        ctx.warnings.push(`${path} bounded proxy decisions require a proxy description and at least one excluded behavior`);
        return null;
      }
      if (status === 'unsupported' && (proxyDescription !== undefined || excludedBehaviors.length < 1)) {
        ctx.missingFields.push(path);
        ctx.warnings.push(`${path} unsupported decisions require at least one excluded behavior and cannot declare a proxy`);
        return null;
      }
      return {
        schemaVersion,
        status,
        reason,
        ...(proxyDescription !== undefined ? { proxyDescription } : {}),
        excludedBehaviors,
      };
    },
  );
}

function parseResearchMemoryProjection(
  value: unknown,
  path: string,
  ctx: Ctx,
): QuantResearchMemoryProjection | null | undefined {
  if (value === undefined) return undefined;
  if (!isPlainObject(value)) {
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} must be an object`);
    return null;
  }
  const knownKeys = new Set(['sourceRunCount', 'testedCandidateCount']);
  const unknownKeys = Object.keys(value).filter((key) => !knownKeys.has(key));
  if (unknownKeys.length > 0) {
    for (const key of unknownKeys) {
      const keyPath = joinPath(path, key);
      ctx.unknownFields.push(keyPath);
      ctx.missingFields.push(keyPath);
    }
    ctx.warnings.push(`${path} contains unsupported fields`);
    return null;
  }
  const sourceRunCount = requiredNonNegativeInteger(value.sourceRunCount, joinPath(path, 'sourceRunCount'), ctx);
  const testedCandidateCount = requiredNonNegativeInteger(value.testedCandidateCount, joinPath(path, 'testedCandidateCount'), ctx);
  if (sourceRunCount === null || testedCandidateCount === null) return null;
  if (sourceRunCount === 0 || testedCandidateCount === 0) {
    ctx.missingFields.push(path);
    ctx.warnings.push(`${path} counts must both be greater than zero when present`);
    return null;
  }
  return { sourceRunCount, testedCandidateCount };
}

function parseRunEvent(value: unknown, path: string, ctx: Ctx): QuantRunEvent | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'sequence', 'type', 'timestamp', 'actor', 'safeSummary', 'artifactId', 'action', 'expectedResult', 'candidateId', 'artifactIds']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const sequence = requiredFiniteNumber(obj.sequence, joinPath(path, 'sequence'), ctx);
      const type = requiredString(obj.type, joinPath(path, 'type'), ctx);
      const timestamp = requiredString(obj.timestamp, joinPath(path, 'timestamp'), ctx);
      const actor = requiredEnum(OWNERS)(obj.actor, joinPath(path, 'actor'), ctx);
      const safeSummary = requiredString(obj.safeSummary, joinPath(path, 'safeSummary'), ctx);
      const artifactId = optionalString(obj.artifactId, joinPath(path, 'artifactId'), ctx);
      const action = optionalString(obj.action, joinPath(path, 'action'), ctx);
      const expectedResult = optionalString(obj.expectedResult, joinPath(path, 'expectedResult'), ctx);
      const candidateId = optionalString(obj.candidateId, joinPath(path, 'candidateId'), ctx);
      const artifactIds = optionalArray(optionalString)(obj.artifactIds, joinPath(path, 'artifactIds'), ctx);
      if (id === null || sequence === null || type === null || timestamp === null || actor === null || safeSummary === null) {
        ok = false;
      }
      if (!ok) return null;
      const event: QuantRunEvent = {
        id: id!,
        sequence: sequence!,
        type: type!,
        timestamp: timestamp!,
        actor: actor!,
        safeSummary: safeSummary!,
      };
      if (artifactId !== undefined) event.artifactId = artifactId;
      if (action !== undefined) event.action = action;
      if (expectedResult !== undefined) event.expectedResult = expectedResult;
      if (candidateId !== undefined) event.candidateId = candidateId;
      if (artifactIds !== undefined) event.artifactIds = artifactIds;
      return event;
    },
  );
}

function parseArtifact(value: unknown, path: string, ctx: Ctx): QuantArtifact | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'type', 'title', 'summary', 'status', 'origin', 'authenticity', 'relatedLabel', 'digest']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const type = requiredEnum(ARTIFACT_TYPES)(obj.type, joinPath(path, 'type'), ctx);
      const title = requiredString(obj.title, joinPath(path, 'title'), ctx);
      const summary = requiredString(obj.summary, joinPath(path, 'summary'), ctx);
      const status = requiredEnum(ARTIFACT_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const origin = requiredString(obj.origin, joinPath(path, 'origin'), ctx);
      const authenticity = requiredEnum(AUTHENTICITY_VALUES)(obj.authenticity, joinPath(path, 'authenticity'), ctx);
      const relatedLabel = requiredString(obj.relatedLabel, joinPath(path, 'relatedLabel'), ctx);
      const digest = requiredString(obj.digest, joinPath(path, 'digest'), ctx);
      if (id === null || type === null || title === null || summary === null || status === null || origin === null || authenticity === null || relatedLabel === null || digest === null) {
        ok = false;
      }
      if (!ok) return null;
      return {
        id: id!,
        type: type!,
        title: title!,
        summary: summary!,
        status: status!,
        origin: origin!,
        authenticity: authenticity!,
        relatedLabel: relatedLabel!,
        digest: digest!,
      };
    },
  );
}

function parseDatasetDataQuality(value: unknown, path: string, ctx: Ctx): DatasetDataQuality | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set([
      'schemaVersion',
      'policyVersion',
      'status',
      'verificationStatus',
      'reportDigest',
      'datasetDigest',
      'barCount',
      'calendarGapCount',
      'largestCalendarGapDays',
      'unexpectedSessionCount',
      'zeroVolumeBarCount',
      'priceJumpCount',
      'issues',
      'notes',
    ]),
    (obj) => {
      let ok = true;
      const schemaVersion = requiredString(obj.schemaVersion, joinPath(path, 'schemaVersion'), ctx);
      const policyVersion = requiredString(obj.policyVersion, joinPath(path, 'policyVersion'), ctx);
      const status = requiredEnum(['passed', 'warning', 'blocked'] as const)(obj.status, joinPath(path, 'status'), ctx);
      const verificationStatus = requiredEnum(['checked', 'rejected'] as const)(obj.verificationStatus, joinPath(path, 'verificationStatus'), ctx);
      const reportDigest = requiredString(obj.reportDigest, joinPath(path, 'reportDigest'), ctx);
      const datasetDigest = requiredString(obj.datasetDigest, joinPath(path, 'datasetDigest'), ctx);
      const barCount = requiredFiniteNumber(obj.barCount, joinPath(path, 'barCount'), ctx);
      const calendarGapCount = requiredFiniteNumber(obj.calendarGapCount, joinPath(path, 'calendarGapCount'), ctx);
      const largestCalendarGapDays = requiredFiniteNumber(obj.largestCalendarGapDays, joinPath(path, 'largestCalendarGapDays'), ctx);
      const unexpectedSessionCount = optionalFiniteNumber(obj.unexpectedSessionCount, joinPath(path, 'unexpectedSessionCount'), ctx);
      const zeroVolumeBarCount = requiredFiniteNumber(obj.zeroVolumeBarCount, joinPath(path, 'zeroVolumeBarCount'), ctx);
      const priceJumpCount = requiredFiniteNumber(obj.priceJumpCount, joinPath(path, 'priceJumpCount'), ctx);
      const issues = requiredArray((v, p, c) =>
        parseObject(v, p, c, new Set(['code', 'severity', 'message', 'count']), (issueObj) => {
          let issueOk = true;
          const code = requiredString(issueObj.code, joinPath(p, 'code'), c);
          const severity = requiredString(issueObj.severity, joinPath(p, 'severity'), c);
          const message = requiredString(issueObj.message, joinPath(p, 'message'), c);
          const count = requiredFiniteNumber(issueObj.count, joinPath(p, 'count'), c);
          if (code === null || severity === null || message === null || count === null) issueOk = false;
          if (!issueOk) return null;
          return { code: code!, severity: severity!, message: message!, count: count! };
        }),
      )(obj.issues, joinPath(path, 'issues'), ctx);
      const notes = requiredArray(requiredString)(obj.notes, joinPath(path, 'notes'), ctx);
      if (
        schemaVersion === null ||
        policyVersion === null ||
        status === null ||
        verificationStatus === null ||
        reportDigest === null ||
        datasetDigest === null ||
        barCount === null ||
        calendarGapCount === null ||
        largestCalendarGapDays === null ||
        zeroVolumeBarCount === null ||
        priceJumpCount === null ||
        issues === null ||
        notes === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      const quality: DatasetDataQuality = {
        schemaVersion: schemaVersion!,
        policyVersion: policyVersion!,
        status: status!,
        verificationStatus: verificationStatus!,
        reportDigest: reportDigest!,
        datasetDigest: datasetDigest!,
        barCount: barCount!,
        calendarGapCount: calendarGapCount!,
        largestCalendarGapDays: largestCalendarGapDays!,
        zeroVolumeBarCount: zeroVolumeBarCount!,
        priceJumpCount: priceJumpCount!,
        issues: issues!,
        notes: notes!,
      };
      if (unexpectedSessionCount !== undefined) quality.unexpectedSessionCount = unexpectedSessionCount;
      return quality;
    },
  );
}

function parseMarketDatasetQuality(value: unknown, path: string, ctx: Ctx): QuantMarketDatasetQuality | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['status', 'cadenceGapCount', 'normalizationNote']),
    (obj) => {
      const status = requiredEnum(['accepted', 'blocked'] as const)(obj.status, joinPath(path, 'status'), ctx);
      const cadenceGapCount = requiredFiniteNumber(obj.cadenceGapCount, joinPath(path, 'cadenceGapCount'), ctx);
      const normalizationNote = requiredString(obj.normalizationNote, joinPath(path, 'normalizationNote'), ctx);
      if (status === null || cadenceGapCount === null || normalizationNote === null) return null;
      return { status, cadenceGapCount, normalizationNote };
    },
  );
}

function parseCsvSource(value: unknown, path: string, ctx: Ctx): DatasetCsvSource | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['kind', 'fileName', 'sourceName', 'sourceReference', 'submittedCsvDigest', 'marketCalendar', 'timeZone', 'priceAdjustment']),
    (obj) => {
      let ok = true;
      const kind = requiredLiteral('csv_upload')(obj.kind, joinPath(path, 'kind'), ctx);
      const fileName = nullableString(obj.fileName, joinPath(path, 'fileName'), ctx);
      const sourceName = requiredString(obj.sourceName, joinPath(path, 'sourceName'), ctx);
      const sourceReference = nullableString(obj.sourceReference, joinPath(path, 'sourceReference'), ctx);
      const submittedCsvDigest = nullableString(obj.submittedCsvDigest, joinPath(path, 'submittedCsvDigest'), ctx);
      const marketCalendar = optionalEnum(CALENDAR_VALUES)(obj.marketCalendar, joinPath(path, 'marketCalendar'), ctx);
      const timeZone = optionalString(obj.timeZone, joinPath(path, 'timeZone'), ctx);
      const priceAdjustment = requiredEnum(PRICE_ADJUSTMENTS)(obj.priceAdjustment, joinPath(path, 'priceAdjustment'), ctx);
      if (kind === null || fileName === null || sourceName === null || sourceReference === null || submittedCsvDigest === null || priceAdjustment === null) {
        ok = false;
      }
      if (!ok) return null;
      const source: DatasetCsvSource = {
        kind: kind!,
        fileName: fileName!,
        sourceName: sourceName!,
        sourceReference: sourceReference!,
        submittedCsvDigest: submittedCsvDigest!,
        priceAdjustment: priceAdjustment!,
      };
      if (marketCalendar !== undefined) source.marketCalendar = marketCalendar;
      if (timeZone !== undefined) source.timeZone = timeZone;
      return source;
    },
  );
}

function parseProviderSource(value: unknown, path: string, ctx: Ctx): DatasetProviderFetchSource | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set([
      'kind',
      'sourceName',
      'sourceReference',
      'submittedCsvDigest',
      'marketCalendar',
      'timeZone',
      'priceAdjustment',
      'providerId',
      'providerResponseAttestations',
      'retrievedAt',
      'requestedLimit',
      'returnedBarCount',
      'droppedIncompleteCount',
      'normalizationNote',
      'attestationStatus',
      'priceAdjustmentVerificationStatus',
      'corporateActionsAttestation',
    ]),
    (obj) => {
      let ok = true;
      const kind = requiredLiteral('provider_fetch')(obj.kind, joinPath(path, 'kind'), ctx);
      const sourceName = requiredString(obj.sourceName, joinPath(path, 'sourceName'), ctx);
      const sourceReference = nullableString(obj.sourceReference, joinPath(path, 'sourceReference'), ctx);
      const submittedCsvDigest = nullableString(obj.submittedCsvDigest, joinPath(path, 'submittedCsvDigest'), ctx);
      const marketCalendar = requiredEnum(CALENDAR_VALUES)(obj.marketCalendar, joinPath(path, 'marketCalendar'), ctx);
      const timeZone = requiredString(obj.timeZone, joinPath(path, 'timeZone'), ctx);
      const priceAdjustment = requiredEnum(PRICE_ADJUSTMENTS)(obj.priceAdjustment, joinPath(path, 'priceAdjustment'), ctx);
      const providerId = requiredString(obj.providerId, joinPath(path, 'providerId'), ctx);
      const providerResponseAttestations = requiredArray((v, p, c) =>
        parseObject(v, p, c, new Set(['kind', 'digest', 'sourceReference']), (attObj) => {
          let attOk = true;
          const attKind = requiredString(attObj.kind, joinPath(p, 'kind'), c);
          const digest = requiredString(attObj.digest, joinPath(p, 'digest'), c);
          const sourceReference = requiredString(attObj.sourceReference, joinPath(p, 'sourceReference'), c);
          if (attKind === null || digest === null || sourceReference === null) attOk = false;
          if (!attOk) return null;
          return { kind: attKind!, digest: digest!, sourceReference: sourceReference! };
        }),
      )(obj.providerResponseAttestations, joinPath(path, 'providerResponseAttestations'), ctx);
      const retrievedAt = requiredString(obj.retrievedAt, joinPath(path, 'retrievedAt'), ctx);
      const requestedLimit = requiredFiniteNumber(obj.requestedLimit, joinPath(path, 'requestedLimit'), ctx);
      const returnedBarCount = requiredFiniteNumber(obj.returnedBarCount, joinPath(path, 'returnedBarCount'), ctx);
      const droppedIncompleteCount = requiredFiniteNumber(obj.droppedIncompleteCount, joinPath(path, 'droppedIncompleteCount'), ctx);
      const normalizationNote = requiredString(obj.normalizationNote, joinPath(path, 'normalizationNote'), ctx);
      const attestationStatus = requiredString(obj.attestationStatus, joinPath(path, 'attestationStatus'), ctx);
      const priceAdjustmentVerificationStatus = optionalString(obj.priceAdjustmentVerificationStatus, joinPath(path, 'priceAdjustmentVerificationStatus'), ctx);
      const corporateActionsAttestation = parseCorporateActionsAttestation(obj.corporateActionsAttestation, joinPath(path, 'corporateActionsAttestation'), ctx);
      if (
        kind === null ||
        sourceName === null ||
        sourceReference === null ||
        submittedCsvDigest === null ||
        marketCalendar === null ||
        timeZone === null ||
        priceAdjustment === null ||
        providerId === null ||
        providerResponseAttestations === null ||
        retrievedAt === null ||
        requestedLimit === null ||
        returnedBarCount === null ||
        droppedIncompleteCount === null ||
        normalizationNote === null ||
        attestationStatus === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      const source: DatasetProviderFetchSource = {
        kind: kind!,
        sourceName: sourceName!,
        sourceReference: sourceReference!,
        submittedCsvDigest: submittedCsvDigest!,
        marketCalendar: marketCalendar!,
        timeZone: timeZone!,
        priceAdjustment: priceAdjustment!,
        providerId: providerId!,
        providerResponseAttestations: providerResponseAttestations!,
        retrievedAt: retrievedAt!,
        requestedLimit: requestedLimit!,
        returnedBarCount: returnedBarCount!,
        droppedIncompleteCount: droppedIncompleteCount!,
        normalizationNote: normalizationNote!,
        attestationStatus: attestationStatus!,
      };
      if (priceAdjustmentVerificationStatus !== undefined) source.priceAdjustmentVerificationStatus = priceAdjustmentVerificationStatus;
      if (corporateActionsAttestation !== undefined) source.corporateActionsAttestation = corporateActionsAttestation;
      return source;
    },
  );
}

function parseCorporateActionsAttestation(
  value: unknown,
  path: string,
  ctx: Ctx,
): DatasetProviderFetchSource['corporateActionsAttestation'] | undefined {
  if (value === undefined || value === null) return undefined;
  const parsed = parseObject(
    value,
    path,
    ctx,
    new Set([
      'dividendsStatus',
      'splitsStatus',
      'coverageStart',
      'coverageEnd',
      'dividendCoverageStart',
      'dividendCoverageEnd',
      'splitCoverageStart',
      'splitCoverageEnd',
      'splitSnapshotAsOf',
      'splitCompletenessStatus',
      'splitReconciliationStatus',
      'splitEvents',
      'dividendEventCount',
      'splitEventCount',
      'note',
    ]),
    (obj) => {
      let ok = true;
      const dividendsStatus = requiredString(obj.dividendsStatus, joinPath(path, 'dividendsStatus'), ctx);
      const splitsStatus = requiredString(obj.splitsStatus, joinPath(path, 'splitsStatus'), ctx);
      const coverageStart = nullableString(obj.coverageStart, joinPath(path, 'coverageStart'), ctx);
      const coverageEnd = nullableString(obj.coverageEnd, joinPath(path, 'coverageEnd'), ctx);
      const dividendCoverageStart = optionalString(obj.dividendCoverageStart, joinPath(path, 'dividendCoverageStart'), ctx);
      const dividendCoverageEnd = optionalString(obj.dividendCoverageEnd, joinPath(path, 'dividendCoverageEnd'), ctx);
      const splitCoverageStart = optionalString(obj.splitCoverageStart, joinPath(path, 'splitCoverageStart'), ctx);
      const splitCoverageEnd = optionalString(obj.splitCoverageEnd, joinPath(path, 'splitCoverageEnd'), ctx);
      const splitSnapshotAsOf = optionalString(obj.splitSnapshotAsOf, joinPath(path, 'splitSnapshotAsOf'), ctx);
      const splitCompletenessStatus = optionalString(obj.splitCompletenessStatus, joinPath(path, 'splitCompletenessStatus'), ctx);
      const splitReconciliationStatus = optionalString(obj.splitReconciliationStatus, joinPath(path, 'splitReconciliationStatus'), ctx);
      const splitEvents = optionalArray((v, p, c) =>
        parseObject(v, p, c, new Set(['effectiveDate', 'ratioNumerator', 'ratioDenominator']), (eventObj) => {
          let eventOk = true;
          const effectiveDate = requiredString(eventObj.effectiveDate, joinPath(p, 'effectiveDate'), c);
          const ratioNumerator = requiredFiniteNumber(eventObj.ratioNumerator, joinPath(p, 'ratioNumerator'), c);
          const ratioDenominator = requiredFiniteNumber(eventObj.ratioDenominator, joinPath(p, 'ratioDenominator'), c);
          if (effectiveDate === null || ratioNumerator === null || ratioDenominator === null) eventOk = false;
          if (!eventOk) return undefined;
          return { effectiveDate: effectiveDate!, ratioNumerator: ratioNumerator!, ratioDenominator: ratioDenominator! };
        }),
      )(obj.splitEvents, joinPath(path, 'splitEvents'), ctx);
      const dividendEventCount = nullableFiniteNumber(obj.dividendEventCount, joinPath(path, 'dividendEventCount'), ctx);
      const splitEventCount = nullableFiniteNumber(obj.splitEventCount, joinPath(path, 'splitEventCount'), ctx);
      const note = requiredString(obj.note, joinPath(path, 'note'), ctx);
      if (
        dividendsStatus === null ||
        splitsStatus === null ||
        coverageStart === null ||
        coverageEnd === null ||
        dividendEventCount === null ||
        splitEventCount === null ||
        note === null
      ) {
        ok = false;
      }
      if (!ok) return undefined;
      const attestation: NonNullable<DatasetProviderFetchSource['corporateActionsAttestation']> = {
        dividendsStatus: dividendsStatus!,
        splitsStatus: splitsStatus!,
        coverageStart: coverageStart!,
        coverageEnd: coverageEnd!,
        dividendEventCount: dividendEventCount!,
        splitEventCount: splitEventCount!,
        note: note!,
      };
      if (dividendCoverageStart !== undefined) attestation.dividendCoverageStart = dividendCoverageStart;
      if (dividendCoverageEnd !== undefined) attestation.dividendCoverageEnd = dividendCoverageEnd;
      if (splitCoverageStart !== undefined) attestation.splitCoverageStart = splitCoverageStart;
      if (splitCoverageEnd !== undefined) attestation.splitCoverageEnd = splitCoverageEnd;
      if (splitSnapshotAsOf !== undefined) attestation.splitSnapshotAsOf = splitSnapshotAsOf;
      if (splitCompletenessStatus !== undefined) attestation.splitCompletenessStatus = splitCompletenessStatus;
      if (splitReconciliationStatus !== undefined) attestation.splitReconciliationStatus = splitReconciliationStatus;
      if (splitEvents !== undefined) attestation.splitEvents = splitEvents;
      return attestation;
    },
  );
  return parsed ?? undefined;
}

function parseDatasetSource(value: unknown, path: string, ctx: Ctx): DatasetSource | undefined {
  if (value === undefined || value === null) return undefined;
  const kind = typeof (value as Record<string, unknown>).kind === 'string' ? ((value as Record<string, unknown>).kind as string) : null;
  if (kind === 'csv_upload') return parseCsvSource(value, path, ctx) ?? undefined;
  if (kind === 'provider_fetch') return parseProviderSource(value, path, ctx) ?? undefined;
  ctx.warnings.push(`${path} has unrecognized source kind "${kind ?? String(value)}" and will be ignored`);
  return undefined;
}

function parseDatasetSnapshot(value: unknown, path: string, ctx: Ctx, forceMarket = false): DatasetSnapshot | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'name', 'symbol', 'interval', 'dateRange', 'barCount', 'schemaVersion', 'parserVersion', 'digest', 'authenticity', 'createdAt', 'source', 'quality', 'periodsPerYear', 'marketCalendar', 'marketSession', 'timeZone', 'runtimeDescriptorDigest', 'sealedSplitDigest', 'contract', 'researchEligible', 'recordDigest']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const name = requiredString(obj.name, joinPath(path, 'name'), ctx);
      const symbol = requiredString(obj.symbol, joinPath(path, 'symbol'), ctx);
      const interval = requiredEnum(['1h', '4h', '1D'] as const)(obj.interval, joinPath(path, 'interval'), ctx);
      const dateRange = parseDateRange(obj.dateRange, joinPath(path, 'dateRange'), ctx);
      const barCount = requiredFiniteNumber(obj.barCount, joinPath(path, 'barCount'), ctx);
      const schemaVersion = requiredString(obj.schemaVersion, joinPath(path, 'schemaVersion'), ctx);
      const parserVersion = requiredString(obj.parserVersion, joinPath(path, 'parserVersion'), ctx);
      const digest = requiredString(obj.digest, joinPath(path, 'digest'), ctx);
      const authenticity = requiredEnum(AUTHENTICITY_VALUES)(obj.authenticity, joinPath(path, 'authenticity'), ctx);
      const createdAt = optionalString(obj.createdAt, joinPath(path, 'createdAt'), ctx);
      const contract = obj.contract === undefined
        ? undefined
        : requiredEnum(DATASET_CONTRACTS)(obj.contract, joinPath(path, 'contract'), ctx);
      const marketLike = forceMarket
        || contract === 'market-v2'
        || schemaVersion === 'quant-market-bars-v2'
        || interval === '1h'
        || interval === '4h'
        || rangeHasTimestamp(obj.dateRange)
        || MARKET_DATASET_FIELDS.some((key) => obj[key] !== undefined);
      if (
        id === null ||
        name === null ||
        symbol === null ||
        interval === null ||
        dateRange === null ||
        barCount === null ||
        schemaVersion === null ||
        parserVersion === null ||
        digest === null ||
        authenticity === null ||
        contract === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      if (marketLike) {
        if (contract === 'legacy-daily-v1' || schemaVersion !== 'quant-market-bars-v2') {
          ctx.missingFields.push(joinPath(path, 'schemaVersion'));
          ctx.warnings.push(`${path} market identity conflicts with its declared legacy contract or schema`);
          return null;
        }
        const periodsPerYear = requiredFiniteNumber(obj.periodsPerYear, joinPath(path, 'periodsPerYear'), ctx);
        const marketCalendar = requiredEnum(['unknown', 'weekday', '24x7', 'XNYS', 'XNAS', 'XSHG', 'XSHE'] as const)(obj.marketCalendar, joinPath(path, 'marketCalendar'), ctx);
        const marketSession = requiredEnum(['unknown', 'continuous', 'regular'] as const)(obj.marketSession, joinPath(path, 'marketSession'), ctx);
        const timeZone = requiredString(obj.timeZone, joinPath(path, 'timeZone'), ctx);
        const runtimeDescriptorDigest = requiredString(obj.runtimeDescriptorDigest, joinPath(path, 'runtimeDescriptorDigest'), ctx);
        const sealedSplitDigest = requiredString(obj.sealedSplitDigest, joinPath(path, 'sealedSplitDigest'), ctx);
        const sourceObj = isPlainObject(obj.source) ? obj.source : null;
        const marketQuality = parseMarketDatasetQuality(obj.quality, joinPath(path, 'quality'), ctx);
        if (!sourceObj || !marketQuality) {
          ctx.missingFields.push(!sourceObj ? joinPath(path, 'source') : joinPath(path, 'quality'));
          ctx.warnings.push(`${path} market dataset requires source and cadence quality`);
          return null;
        }
        const sourceKind = requiredEnum(['csv_upload', 'provider_fetch'] as const)(sourceObj.kind, joinPath(path, 'source.kind'), ctx);
        const sourceName = requiredString(sourceObj.sourceName, joinPath(path, 'source.sourceName'), ctx);
        const sourceReference = sourceObj.sourceReference === null ? null : optionalString(sourceObj.sourceReference, joinPath(path, 'source.sourceReference'), ctx) ?? null;
        const fileName = sourceObj.fileName === null ? null : optionalString(sourceObj.fileName, joinPath(path, 'source.fileName'), ctx) ?? null;
        const normalizerVersion = requiredString(sourceObj.normalizerVersion, joinPath(path, 'source.normalizerVersion'), ctx);
        if (periodsPerYear === null || marketCalendar === null || marketSession === null || timeZone === null || runtimeDescriptorDigest === null || sealedSplitDigest === null || sourceKind === null || sourceName === null || normalizerVersion === null) return null;
        try {
          assertQuantMarketDatasetCadence({
            intervalValue: interval!,
            periodsPerYear,
            calendar: marketCalendar,
            session: marketSession,
            timeZone,
            researchEligible: true,
          });
        } catch (error) {
          ctx.missingFields.push(joinPath(path, 'periodsPerYear'));
          ctx.warnings.push(`${path} market cadence is invalid: ${error instanceof Error ? error.message : String(error)}`);
          return null;
        }
        if (marketQuality.status !== 'accepted' || marketQuality.cadenceGapCount !== 0) {
          ctx.missingFields.push(joinPath(path, 'quality'));
          ctx.warnings.push(`${path} runtime market dataset must have accepted contiguous cadence quality`);
          return null;
        }
        const nullableInteger = (key: string) => typeof sourceObj[key] === 'number' && Number.isInteger(sourceObj[key]) && Number(sourceObj[key]) >= 0 ? Number(sourceObj[key]) : null;
        const retrievedAtUtc = sourceObj.retrievedAtUtc === null ? null : optionalString(sourceObj.retrievedAtUtc, joinPath(path, 'source.retrievedAtUtc'), ctx) ?? null;
        const terminationReason = sourceObj.terminationReason === null || sourceObj.terminationReason === undefined ? null : requiredEnum(['requested_limit', 'history_exhausted', 'page_cap'] as const)(sourceObj.terminationReason, joinPath(path, 'source.terminationReason'), ctx);
        const targetSatisfied = sourceObj.targetSatisfied === null || sourceObj.targetSatisfied === undefined ? null : requiredBoolean(sourceObj.targetSatisfied, joinPath(path, 'source.targetSatisfied'), ctx);
        return {
          contract: 'market-v2', id: id!, name: name!, symbol: symbol!, interval: interval!, dateRange: dateRange!, barCount: barCount!,
          schemaVersion: schemaVersion!, parserVersion: parserVersion!, digest: digest!, authenticity: authenticity!, researchEligible: marketQuality.status === 'accepted',
          ...(createdAt !== undefined ? { createdAt } : {}), periodsPerYear, marketCalendar, marketSession, timeZone,
          runtimeDescriptorDigest, sealedSplitDigest,
          source: { kind: sourceKind, fileName, sourceName, sourceReference, normalizerVersion, retrievedAtUtc, requestedBarCount: nullableInteger('requestedBarCount'), returnedBarCount: nullableInteger('returnedBarCount'), retainedBarCount: nullableInteger('retainedBarCount'), closedDroppedCount: nullableInteger('closedDroppedCount'), deduplicatedCount: nullableInteger('deduplicatedCount'), terminationReason, targetSatisfied, submittedCsvDigest: sourceObj.submittedCsvDigest === null ? null : optionalString(sourceObj.submittedCsvDigest, joinPath(path, 'source.submittedCsvDigest'), ctx), batchDigest: sourceObj.batchDigest === null ? null : optionalString(sourceObj.batchDigest, joinPath(path, 'source.batchDigest'), ctx) },
          quality: marketQuality,
        };
      }
      if (contract !== undefined && contract !== 'legacy-daily-v1') return null;
      if (interval !== '1D' || schemaVersion !== 'quant-daily-bars-v1') {
        ctx.missingFields.push(joinPath(path, 'schemaVersion'));
        ctx.warnings.push(`${path} legacy identity requires quant-daily-bars-v1 with interval 1D`);
        return null;
      }
      const source = parseDatasetSource(obj.source, joinPath(path, 'source'), ctx);
      const quality = obj.quality === undefined || obj.quality === null ? undefined : parseDatasetDataQuality(obj.quality, joinPath(path, 'quality'), ctx);
      const snapshot: DatasetSnapshot = {
        contract: 'legacy-daily-v1',
        id: id!,
        name: name!,
        symbol: symbol!,
        interval: interval!,
        dateRange: dateRange!,
        barCount: barCount!,
        schemaVersion: schemaVersion!,
        parserVersion: parserVersion!,
        digest: digest!,
        authenticity: authenticity!,
        researchEligible: barCount! >= 252 && quality?.status !== 'blocked',
      };
      if (createdAt !== undefined) snapshot.createdAt = createdAt;
      if (source !== undefined) snapshot.source = source;
      if (quality != null) snapshot.quality = quality;
      return snapshot;
    },
  );
}

function parseMarketBar(value: unknown, path: string, ctx: Ctx): MarketBar | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['date', 'open', 'high', 'low', 'close', 'volume', 'marker']),
    (obj) => {
      let ok = true;
      const date = requiredString(obj.date, joinPath(path, 'date'), ctx);
      const open = requiredFiniteNumber(obj.open, joinPath(path, 'open'), ctx);
      const high = requiredFiniteNumber(obj.high, joinPath(path, 'high'), ctx);
      const low = requiredFiniteNumber(obj.low, joinPath(path, 'low'), ctx);
      const close = requiredFiniteNumber(obj.close, joinPath(path, 'close'), ctx);
      const volume = requiredFiniteNumber(obj.volume, joinPath(path, 'volume'), ctx);
      const marker = optionalEnum(MARKERS)(obj.marker, joinPath(path, 'marker'), ctx);
      if (date === null || open === null || high === null || low === null || close === null || volume === null) ok = false;
      if (!ok) return null;
      const bar: MarketBar = {
        date: date!,
        open: open!,
        high: high!,
        low: low!,
        close: close!,
        volume: volume!,
      };
      if (marker !== undefined) bar.marker = marker;
      return bar;
    },
  );
}

function parseKernelResult(value: unknown, path: string, ctx: Ctx): QuantKernelResult | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'label', 'totalReturnPct', 'annualizedReturnPct', 'maxDrawdownPct', 'sharpe', 'tradeCount', 'finalEquity']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const label = requiredString(obj.label, joinPath(path, 'label'), ctx);
      const totalReturnPct = requiredFiniteNumber(obj.totalReturnPct, joinPath(path, 'totalReturnPct'), ctx);
      const annualizedReturnPct = requiredFiniteNumber(obj.annualizedReturnPct, joinPath(path, 'annualizedReturnPct'), ctx);
      const maxDrawdownPct = requiredFiniteNumber(obj.maxDrawdownPct, joinPath(path, 'maxDrawdownPct'), ctx);
      const sharpe = requiredFiniteNumber(obj.sharpe, joinPath(path, 'sharpe'), ctx);
      const tradeCount = requiredFiniteNumber(obj.tradeCount, joinPath(path, 'tradeCount'), ctx);
      const finalEquity = requiredFiniteNumber(obj.finalEquity, joinPath(path, 'finalEquity'), ctx);
      if (id === null || label === null || totalReturnPct === null || annualizedReturnPct === null || maxDrawdownPct === null || sharpe === null || tradeCount === null || finalEquity === null) {
        ok = false;
      }
      if (!ok) return null;
      return {
        id: id!,
        label: label!,
        totalReturnPct: totalReturnPct!,
        annualizedReturnPct: annualizedReturnPct!,
        maxDrawdownPct: maxDrawdownPct!,
        sharpe: sharpe!,
        tradeCount: tradeCount!,
        finalEquity: finalEquity!,
      };
    },
  );
}

function parseNullableKernelResult(value: unknown, path: string, ctx: Ctx): QuantKernelResult | null | undefined {
  if (value === null) return null;
  const parsed = parseKernelResult(value, path, ctx);
  return parsed ?? undefined;
}

function parseKernelCheck(value: unknown, path: string, ctx: Ctx): QuantKernelCheck | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['status', 'engineVersion', 'datasetId', 'datasetDigest', 'barCount', 'execution', 'feeRateBps', 'slippageRateBps', 'benchmark', 'strategies', 'limitations', 'interval', 'periodsPerYear', 'runtimeDescriptorDigest', 'sealedSplitDigest']),
    (obj) => {
      let ok = true;
      const status = requiredEnum(KERNEL_CHECK_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const engineVersion = requiredString(obj.engineVersion, joinPath(path, 'engineVersion'), ctx);
      const datasetId = requiredString(obj.datasetId, joinPath(path, 'datasetId'), ctx);
      const datasetDigest = requiredString(obj.datasetDigest, joinPath(path, 'datasetDigest'), ctx);
      const barCount = requiredFiniteNumber(obj.barCount, joinPath(path, 'barCount'), ctx);
      const execution = requiredLiteral('signal_at_close_fill_next_open')(obj.execution, joinPath(path, 'execution'), ctx);
      const feeRateBps = requiredFiniteNumber(obj.feeRateBps, joinPath(path, 'feeRateBps'), ctx);
      const slippageRateBps = requiredFiniteNumber(obj.slippageRateBps, joinPath(path, 'slippageRateBps'), ctx);
      const benchmark = parseNullableKernelResult(obj.benchmark, joinPath(path, 'benchmark'), ctx);
      const strategies = requiredArray(parseKernelResult)(obj.strategies, joinPath(path, 'strategies'), ctx);
      const limitations = requiredArray(requiredString)(obj.limitations, joinPath(path, 'limitations'), ctx);
      const interval = optionalEnum(['1h', '4h', '1D'] as const)(obj.interval, joinPath(path, 'interval'), ctx);
      const periodsPerYear = optionalFiniteNumber(obj.periodsPerYear, joinPath(path, 'periodsPerYear'), ctx);
      const runtimeDescriptorDigest = optionalString(obj.runtimeDescriptorDigest, joinPath(path, 'runtimeDescriptorDigest'), ctx);
      const sealedSplitDigest = optionalString(obj.sealedSplitDigest, joinPath(path, 'sealedSplitDigest'), ctx);
      if (
        status === null ||
        engineVersion === null ||
        datasetId === null ||
        datasetDigest === null ||
        barCount === null ||
        execution === null ||
        feeRateBps === null ||
        slippageRateBps === null ||
        benchmark === undefined ||
        strategies === null ||
        limitations === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      const check: QuantKernelCheck = {
        status: status!,
        engineVersion: engineVersion!,
        datasetId: datasetId!,
        datasetDigest: datasetDigest!,
        barCount: barCount!,
        execution: execution!,
        feeRateBps: feeRateBps!,
        slippageRateBps: slippageRateBps!,
        benchmark: benchmark!,
        strategies: strategies!,
        limitations: limitations!,
      };
      if (interval !== undefined) check.interval = interval;
      if (periodsPerYear !== undefined) check.periodsPerYear = periodsPerYear;
      if (runtimeDescriptorDigest !== undefined) check.runtimeDescriptorDigest = runtimeDescriptorDigest;
      if (sealedSplitDigest !== undefined) check.sealedSplitDigest = sealedSplitDigest;
      return check;
    },
  );
}

function parseCandidate(value: unknown, path: string, ctx: Ctx): QuantCandidate | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'name', 'parameters', 'verdict', 'verdictReason', 'metrics', 'strategySpecVersion', 'strategySpec', 'canSeedResearch', 'robustness', 'evolution']),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const name = requiredString(obj.name, joinPath(path, 'name'), ctx);
      const parameters = requiredString(obj.parameters, joinPath(path, 'parameters'), ctx);
      const verdict = requiredEnum(CANDIDATE_VERDICTS)(obj.verdict, joinPath(path, 'verdict'), ctx);
      const verdictReason = requiredString(obj.verdictReason, joinPath(path, 'verdictReason'), ctx);
      const metrics = parseBacktestMetrics(obj.metrics, joinPath(path, 'metrics'), ctx);
      const strategySpecVersion = requiredString(obj.strategySpecVersion, joinPath(path, 'strategySpecVersion'), ctx);
      const strategySpec = requiredString(obj.strategySpec, joinPath(path, 'strategySpec'), ctx);
      const canSeedResearch = obj.canSeedResearch === undefined ? undefined : requiredBoolean(obj.canSeedResearch, joinPath(path, 'canSeedResearch'), ctx);
      const robustness = requiredArray(requiredString)(obj.robustness, joinPath(path, 'robustness'), ctx);
      const evolution = obj.evolution === undefined ? undefined : parseObject(
        obj.evolution,
        joinPath(path, 'evolution'),
        ctx,
        new Set(['hypothesis', 'origin', 'changeRationale', 'feedbackReferenceCandidateId', 'feedbackReferenceCandidateName', 'comparisonRank', 'comparisonCandidateCount', 'selectionReason', 'replanRepair']),
        (evolutionObj) => {
          const hypothesis = requiredString(evolutionObj.hypothesis, joinPath(path, 'evolution.hypothesis'), ctx);
          const origin = requiredEnum(['initial', 'training_feedback'] as const)(evolutionObj.origin, joinPath(path, 'evolution.origin'), ctx);
          const changeRationale = nullableString(evolutionObj.changeRationale, joinPath(path, 'evolution.changeRationale'), ctx);
          const feedbackReferenceCandidateId = nullableString(evolutionObj.feedbackReferenceCandidateId, joinPath(path, 'evolution.feedbackReferenceCandidateId'), ctx);
          const feedbackReferenceCandidateName = nullableString(evolutionObj.feedbackReferenceCandidateName, joinPath(path, 'evolution.feedbackReferenceCandidateName'), ctx);
          const comparisonRank = nullableFiniteNumber(evolutionObj.comparisonRank, joinPath(path, 'evolution.comparisonRank'), ctx);
          const comparisonCandidateCount = nullableFiniteNumber(evolutionObj.comparisonCandidateCount, joinPath(path, 'evolution.comparisonCandidateCount'), ctx);
          const selectionReason = requiredString(evolutionObj.selectionReason, joinPath(path, 'evolution.selectionReason'), ctx);
          const replanRepair = evolutionObj.replanRepair === undefined ? undefined : parseStrictObject(
            evolutionObj.replanRepair,
            joinPath(path, 'evolution.replanRepair'),
            ctx,
            new Set(['rejectedAction', 'correctedAction', 'retainedInputs', 'outcome']),
            (repairObj) => {
              const rejectedAction = requiredLiteral('refine_parameters' as const)(repairObj.rejectedAction, joinPath(path, 'evolution.replanRepair.rejectedAction'), ctx);
              const correctedAction = requiredLiteral('switch_approved_family' as const)(repairObj.correctedAction, joinPath(path, 'evolution.replanRepair.correctedAction'), ctx);
              const retainedInputsBoolean = requiredBoolean(repairObj.retainedInputs, joinPath(path, 'evolution.replanRepair.retainedInputs'), ctx);
              const outcome = requiredLiteral('candidate_created' as const)(repairObj.outcome, joinPath(path, 'evolution.replanRepair.outcome'), ctx);
              if (rejectedAction === null || correctedAction === null || retainedInputsBoolean === null || outcome === null) return null;
              if (retainedInputsBoolean !== true) {
                ctx.missingFields.push(joinPath(path, 'evolution.replanRepair.retainedInputs'));
                ctx.warnings.push(`${joinPath(path, 'evolution.replanRepair.retainedInputs')} must be true`);
                return null;
              }
              const retainedInputs: true = retainedInputsBoolean;
              return { rejectedAction, correctedAction, retainedInputs, outcome };
            },
          );
          if (hypothesis === null || origin === null || changeRationale === undefined || feedbackReferenceCandidateId === undefined || feedbackReferenceCandidateName === undefined || comparisonRank === undefined || comparisonCandidateCount === undefined || selectionReason === null || replanRepair === null) return null;
          if ((comparisonRank === null) !== (comparisonCandidateCount === null) || (comparisonRank !== null && (!Number.isInteger(comparisonRank) || comparisonRank < 1 || comparisonCandidateCount === null || !Number.isInteger(comparisonCandidateCount) || comparisonCandidateCount < comparisonRank))) {
            ctx.missingFields.push(joinPath(path, 'evolution.comparisonRank'));
            ctx.warnings.push(`${joinPath(path, 'evolution')} comparison rank must be a valid 1-based position within its candidate count`);
            return null;
          }
          if (origin === 'training_feedback' && (!changeRationale || !feedbackReferenceCandidateId || !feedbackReferenceCandidateName)) {
            ctx.missingFields.push(joinPath(path, 'evolution.changeRationale'));
            ctx.warnings.push(`${joinPath(path, 'evolution')} feedback-driven candidates require their retained rationale and reference candidate`);
            return null;
          }
          const result: QuantCandidateEvolution = { hypothesis, origin, changeRationale, feedbackReferenceCandidateId, feedbackReferenceCandidateName, comparisonRank, comparisonCandidateCount, selectionReason };
          if (replanRepair !== undefined) result.replanRepair = replanRepair;
          return result;
        },
      );
      if (
        id === null ||
        name === null ||
        parameters === null ||
        verdict === null ||
        verdictReason === null ||
        metrics === null ||
        strategySpecVersion === null ||
        strategySpec === null ||
        canSeedResearch === null ||
        robustness === null ||
        evolution === null
      ) {
        ok = false;
      }
      if (!ok) return null;
      return {
        id: id!,
        name: name!,
        parameters: parameters!,
        verdict: verdict!,
        verdictReason: verdictReason!,
        metrics: metrics!,
        strategySpecVersion: strategySpecVersion!,
        strategySpec: strategySpec!,
        ...(canSeedResearch === true ? { canSeedResearch: true } : canSeedResearch === false ? { canSeedResearch: false } : {}),
        robustness: robustness!,
        ...(evolution ? { evolution } : {}),
      };
    },
  );
}

function parseLiveCandidate(value: unknown, path: string, ctx: Ctx): QuantLiveCandidate | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['id', 'ordinal', 'name', 'hypothesis', 'parameters', 'state', 'repairCount', 'metrics']),
    (obj) => {
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const ordinal = requiredFiniteNumber(obj.ordinal, joinPath(path, 'ordinal'), ctx);
      const name = requiredString(obj.name, joinPath(path, 'name'), ctx);
      const hypothesis = requiredString(obj.hypothesis, joinPath(path, 'hypothesis'), ctx);
      const parameters = requiredString(obj.parameters, joinPath(path, 'parameters'), ctx);
      const state = requiredEnum(['completed', 'running', 'queued', 'repairing', 'revised', 'failed'] as const)(obj.state, joinPath(path, 'state'), ctx);
      const repairCount = requiredFiniteNumber(obj.repairCount, joinPath(path, 'repairCount'), ctx);
      const metrics = parseNullableBacktestMetrics(obj.metrics, joinPath(path, 'metrics'), ctx);
      if (id === null || ordinal === null || name === null || hypothesis === null || parameters === null || state === null || repairCount === null || metrics === undefined) return null;
      return { id, ordinal, name, hypothesis, parameters, state, repairCount, metrics };
    },
  );
}

function parseNullableLiveResearch(value: unknown, path: string, ctx: Ctx): QuantLiveResearch | null | undefined {
  if (value === null) return null;
  return parseObject(
    value,
    path,
    ctx,
    new Set(['phase', 'phaseLabel', 'iteration', 'currentExperiment', 'latestResult', 'candidates', 'nextStep']),
    (obj) => {
      const phase = requiredEnumWithUnknown(RUN_STATES)(obj.phase, joinPath(path, 'phase'), ctx);
      const phaseLabel = requiredString(obj.phaseLabel, joinPath(path, 'phaseLabel'), ctx);
      const iteration = requiredFiniteNumber(obj.iteration, joinPath(path, 'iteration'), ctx);
      const currentExperiment = obj.currentExperiment === null ? null : parseLiveCandidate(obj.currentExperiment, joinPath(path, 'currentExperiment'), ctx);
      const latestResult = obj.latestResult === null ? null : parseLiveCandidate(obj.latestResult, joinPath(path, 'latestResult'), ctx);
      const candidates = requiredArray(parseLiveCandidate)(obj.candidates, joinPath(path, 'candidates'), ctx);
      const nextStep = requiredString(obj.nextStep, joinPath(path, 'nextStep'), ctx);
      if (
        phase === null ||
        phaseLabel === null ||
        iteration === null ||
        (currentExperiment === null && obj.currentExperiment !== null) ||
        (latestResult === null && obj.latestResult !== null) ||
        candidates === null ||
        nextStep === null
      ) {
        return null;
      }
      return { phase, phaseLabel, iteration, currentExperiment, latestResult, candidates, nextStep };
    },
  );
}

function parseTrade(value: unknown, path: string, ctx: Ctx, marketRuntime: boolean): TradeRecord | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(marketRuntime
      ? ['id', 'candidateId', 'entryDate', 'exitDate', 'returnPct', 'holdingBars', 'holdingElapsedSeconds', 'reason']
      : ['id', 'candidateId', 'entryDate', 'exitDate', 'returnPct', 'holdingDays', 'reason']),
    (obj) => {
      if ((marketRuntime && Object.hasOwn(obj, 'holdingDays'))
        || (!marketRuntime && (Object.hasOwn(obj, 'holdingBars') || Object.hasOwn(obj, 'holdingElapsedSeconds')))) {
        ctx.missingFields.push(path);
        ctx.warnings.push(`${path} mixes daily and market holding fields`);
        return null;
      }
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const candidateId = requiredString(obj.candidateId, joinPath(path, 'candidateId'), ctx);
      const entryDate = requiredString(obj.entryDate, joinPath(path, 'entryDate'), ctx);
      const exitDate = requiredString(obj.exitDate, joinPath(path, 'exitDate'), ctx);
      const returnPct = requiredFiniteNumber(obj.returnPct, joinPath(path, 'returnPct'), ctx);
      const reason = requiredString(obj.reason, joinPath(path, 'reason'), ctx);
      if (id === null || candidateId === null || entryDate === null || exitDate === null || returnPct === null || reason === null) {
        ok = false;
      }
      if (!ok) return null;
      const common = {
        id: id!,
        candidateId: candidateId!,
        entryDate: entryDate!,
        exitDate: exitDate!,
        returnPct: returnPct!,
        reason: reason!,
      };
      if (marketRuntime) {
        const holdingBars = requiredNonNegativeInteger(obj.holdingBars, joinPath(path, 'holdingBars'), ctx);
        const holdingElapsedSeconds = requiredNonNegativeInteger(obj.holdingElapsedSeconds, joinPath(path, 'holdingElapsedSeconds'), ctx);
        if (holdingBars === null || holdingElapsedSeconds === null) return null;
        return { ...common, holdingBars, holdingElapsedSeconds };
      }
      const holdingDays = requiredNonNegativeInteger(obj.holdingDays, joinPath(path, 'holdingDays'), ctx);
      return holdingDays === null ? null : { ...common, holdingDays };
    },
  );
}

function parsePerformancePoint(value: unknown, path: string, ctx: Ctx): StrategyPerformancePoint | null {
  return parseObject(value, path, ctx, new Set(['date', 'equity', 'drawdown']), (obj) => {
    const date = requiredString(obj.date, joinPath(path, 'date'), ctx);
    const equity = requiredFiniteNumber(obj.equity, joinPath(path, 'equity'), ctx);
    const drawdown = requiredFiniteNumber(obj.drawdown, joinPath(path, 'drawdown'), ctx);
    if (date === null || equity === null || drawdown === null) return null;
    return { date, equity, drawdown };
  });
}

function parsePerformanceSeries(value: unknown, path: string, ctx: Ctx): StrategyPerformanceSeries | null {
  return parseObject(value, path, ctx, new Set(['id', 'label', 'kind', 'points']), (obj) => {
    const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
    const label = requiredString(obj.label, joinPath(path, 'label'), ctx);
    const kind = requiredEnum(['candidate', 'benchmark'] as const)(obj.kind, joinPath(path, 'kind'), ctx);
    const points = requiredArray(parsePerformancePoint)(obj.points, joinPath(path, 'points'), ctx);
    if (id === null || label === null || kind === null || points === null) return null;
    return { id, label, kind, points };
  });
}

function parseGeneralizationSplit(value: unknown, path: string, ctx: Ctx): GeneralizationSplit | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['method', 'ruleVersion', 'trainBarCount', 'holdoutBarCount', 'cutoffDate', 'datasetId', 'datasetDigest', 'interval', 'periodsPerYear', 'cutoffTimestampUtc', 'rangeStartUtc', 'rangeEndUtc', 'descriptorDigest', 'sealDigest']),
    (obj) => {
      let ok = true;
      const method = requiredLiteral('chronological')(obj.method, joinPath(path, 'method'), ctx);
      const ruleVersion = requiredString(obj.ruleVersion, joinPath(path, 'ruleVersion'), ctx);
      const trainBarCount = requiredFiniteNumber(obj.trainBarCount, joinPath(path, 'trainBarCount'), ctx);
      const holdoutBarCount = requiredFiniteNumber(obj.holdoutBarCount, joinPath(path, 'holdoutBarCount'), ctx);
      const cutoffDate = requiredString(obj.cutoffDate, joinPath(path, 'cutoffDate'), ctx);
      const datasetId = requiredString(obj.datasetId, joinPath(path, 'datasetId'), ctx);
      const datasetDigest = requiredString(obj.datasetDigest, joinPath(path, 'datasetDigest'), ctx);
      const interval = optionalEnum(['1h', '4h', '1D'] as const)(obj.interval, joinPath(path, 'interval'), ctx);
      const periodsPerYear = optionalFiniteNumber(obj.periodsPerYear, joinPath(path, 'periodsPerYear'), ctx);
      const cutoffTimestampUtc = optionalString(obj.cutoffTimestampUtc, joinPath(path, 'cutoffTimestampUtc'), ctx);
      const rangeStartUtc = optionalString(obj.rangeStartUtc, joinPath(path, 'rangeStartUtc'), ctx);
      const rangeEndUtc = optionalString(obj.rangeEndUtc, joinPath(path, 'rangeEndUtc'), ctx);
      const descriptorDigest = optionalString(obj.descriptorDigest, joinPath(path, 'descriptorDigest'), ctx);
      const sealDigest = optionalString(obj.sealDigest, joinPath(path, 'sealDigest'), ctx);
      if (method === null || ruleVersion === null || trainBarCount === null || holdoutBarCount === null || cutoffDate === null || datasetId === null || datasetDigest === null) {
        ok = false;
      }
      if (!ok) return null;
      const split: GeneralizationSplit = {
        method: method!,
        ruleVersion: ruleVersion!,
        trainBarCount: trainBarCount!,
        holdoutBarCount: holdoutBarCount!,
        cutoffDate: cutoffDate!,
        datasetId: datasetId!,
        datasetDigest: datasetDigest!,
      };
      if (interval !== undefined) split.interval = interval;
      if (periodsPerYear !== undefined) split.periodsPerYear = periodsPerYear;
      if (cutoffTimestampUtc !== undefined) split.cutoffTimestampUtc = cutoffTimestampUtc;
      if (rangeStartUtc !== undefined) split.rangeStartUtc = rangeStartUtc;
      if (rangeEndUtc !== undefined) split.rangeEndUtc = rangeEndUtc;
      if (descriptorDigest !== undefined) split.descriptorDigest = descriptorDigest;
      if (sealDigest !== undefined) split.sealDigest = sealDigest;
      return split;
    },
  );
}

function parseGeneralizationMetrics(value: unknown, path: string, ctx: Ctx): GeneralizationMetrics | null {
  return parseObject(value, path, ctx, new Set(['candidate', 'benchmark']), (obj) => {
    const candidate = parseBacktestMetrics(obj.candidate, joinPath(path, 'candidate'), ctx);
    const benchmark = parseBacktestMetrics(obj.benchmark, joinPath(path, 'benchmark'), ctx);
    if (candidate === null || benchmark === null) return null;
    return { candidate: candidate!, benchmark: benchmark! };
  });
}

function parseGeneralization(value: unknown, path: string, ctx: Ctx): ResearchGeneralization | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['status', 'reason', 'selectedCandidateId', 'split', 'train', 'holdout']),
    (obj) => {
      let ok = true;
      const status = requiredEnum(GENERALIZATION_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const reason = requiredString(obj.reason, joinPath(path, 'reason'), ctx);
      const selectedCandidateId = obj.selectedCandidateId === undefined ? undefined : nullableString(obj.selectedCandidateId, joinPath(path, 'selectedCandidateId'), ctx);
      const split = parseGeneralizationSplit(obj.split, joinPath(path, 'split'), ctx);
      const train = obj.train === undefined || obj.train === null ? undefined : parseGeneralizationMetrics(obj.train, joinPath(path, 'train'), ctx);
      const holdout = obj.holdout === undefined || obj.holdout === null ? undefined : parseGeneralizationMetrics(obj.holdout, joinPath(path, 'holdout'), ctx);
      if (status === null || reason === null || split === null || selectedCandidateId === null) {
        ok = false;
      }
      if (!ok) return null;
      const generalization: ResearchGeneralization = {
        status: status!,
        reason: reason!,
        split: split!,
      };
      if (selectedCandidateId !== undefined) generalization.selectedCandidateId = selectedCandidateId;
      if (train != null) generalization.train = train;
      if (holdout != null) generalization.holdout = holdout;
      return generalization;
    },
  );
}

function parseWalkForwardFold(value: unknown, path: string, ctx: Ctx): WalkForwardFold | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['foldIndex', 'historyStart', 'historyEnd', 'evaluationStart', 'evaluationEnd', 'marketRegime', 'candidate', 'benchmark', 'status']),
    (obj) => {
      let ok = true;
      const foldIndex = requiredFiniteNumber(obj.foldIndex, joinPath(path, 'foldIndex'), ctx);
      const historyStart = requiredString(obj.historyStart, joinPath(path, 'historyStart'), ctx);
      const historyEnd = requiredString(obj.historyEnd, joinPath(path, 'historyEnd'), ctx);
      const evaluationStart = requiredString(obj.evaluationStart, joinPath(path, 'evaluationStart'), ctx);
      const evaluationEnd = requiredString(obj.evaluationEnd, joinPath(path, 'evaluationEnd'), ctx);
      const candidate = parseBacktestMetrics(obj.candidate, joinPath(path, 'candidate'), ctx);
      const benchmark = parseBacktestMetrics(obj.benchmark, joinPath(path, 'benchmark'), ctx);
      const status = requiredEnum(WALK_FORWARD_FOLD_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const marketRegime = obj.marketRegime === undefined ? undefined : parseWalkForwardMarketRegime(obj.marketRegime, joinPath(path, 'marketRegime'), ctx);
      if (foldIndex === null || historyStart === null || historyEnd === null || evaluationStart === null || evaluationEnd === null || candidate === null || benchmark === null || status === null) {
        ok = false;
      }
      if (!ok || (obj.marketRegime !== undefined && marketRegime === null)) return null;
      return {
        foldIndex: foldIndex!,
        historyStart: historyStart!,
        historyEnd: historyEnd!,
        evaluationStart: evaluationStart!,
        evaluationEnd: evaluationEnd!,
        candidate: candidate!,
        benchmark: benchmark!,
        status: status!,
        ...(marketRegime ? { marketRegime } : {}),
      };
    },
  );
}

function parseWalkForwardMarketRegime(value: unknown, path: string, ctx: Ctx): WalkForwardMarketRegime | null {
  return parseStrictObject(
    value,
    path,
    ctx,
    new Set(['label', 'trend', 'volatility', 'historyStart', 'historyEnd', 'historyBarCount', 'trailingReturn', 'annualizedVolatility']),
    (obj) => {
      const label = requiredString(obj.label, joinPath(path, 'label'), ctx);
      const trend = requiredEnum(['uptrend', 'downtrend', 'sideways'] as const)(obj.trend, joinPath(path, 'trend'), ctx);
      const volatility = requiredEnum(['high_volatility', 'normal_volatility'] as const)(obj.volatility, joinPath(path, 'volatility'), ctx);
      const historyStart = requiredString(obj.historyStart, joinPath(path, 'historyStart'), ctx);
      const historyEnd = requiredString(obj.historyEnd, joinPath(path, 'historyEnd'), ctx);
      const historyBarCount = requiredPositiveInteger(obj.historyBarCount, joinPath(path, 'historyBarCount'), ctx);
      const trailingReturn = requiredFiniteNumber(obj.trailingReturn, joinPath(path, 'trailingReturn'), ctx);
      const annualizedVolatility = requiredFiniteNumber(obj.annualizedVolatility, joinPath(path, 'annualizedVolatility'), ctx);
      if (label === null || trend === null || volatility === null || historyStart === null || historyEnd === null || historyBarCount === null || trailingReturn === null || annualizedVolatility === null) return null;
      if (label !== `${trend}_${volatility}`) {
        ctx.missingFields.push(joinPath(path, 'label'));
        ctx.warnings.push(`${joinPath(path, 'label')} must match its trend and volatility`);
        return null;
      }
      return { label, trend, volatility, historyStart, historyEnd, historyBarCount, trailingReturn, annualizedVolatility };
    },
  );
}

function parseWalkForwardRegimeSummary(value: unknown, path: string, ctx: Ctx): WalkForwardRegimeSummary | null {
  return parseStrictObject(
    value,
    path,
    ctx,
    new Set(['label', 'foldCount', 'candidateMedianReturn', 'benchmarkMedianReturn', 'candidateMedianDrawdown', 'benchmarkMedianDrawdown', 'candidateMedianSharpe', 'benchmarkMedianSharpe']),
    (obj) => {
      const label = requiredString(obj.label, joinPath(path, 'label'), ctx);
      const foldCount = requiredNonNegativeInteger(obj.foldCount, joinPath(path, 'foldCount'), ctx);
      const candidateMedianReturn = requiredFiniteNumber(obj.candidateMedianReturn, joinPath(path, 'candidateMedianReturn'), ctx);
      const benchmarkMedianReturn = requiredFiniteNumber(obj.benchmarkMedianReturn, joinPath(path, 'benchmarkMedianReturn'), ctx);
      const candidateMedianDrawdown = requiredFiniteNumber(obj.candidateMedianDrawdown, joinPath(path, 'candidateMedianDrawdown'), ctx);
      const benchmarkMedianDrawdown = requiredFiniteNumber(obj.benchmarkMedianDrawdown, joinPath(path, 'benchmarkMedianDrawdown'), ctx);
      const candidateMedianSharpe = requiredFiniteNumber(obj.candidateMedianSharpe, joinPath(path, 'candidateMedianSharpe'), ctx);
      const benchmarkMedianSharpe = requiredFiniteNumber(obj.benchmarkMedianSharpe, joinPath(path, 'benchmarkMedianSharpe'), ctx);
      if (label === null || foldCount === null || candidateMedianReturn === null || benchmarkMedianReturn === null || candidateMedianDrawdown === null || benchmarkMedianDrawdown === null || candidateMedianSharpe === null || benchmarkMedianSharpe === null) return null;
      return { label, foldCount, candidateMedianReturn, benchmarkMedianReturn, candidateMedianDrawdown, benchmarkMedianDrawdown, candidateMedianSharpe, benchmarkMedianSharpe };
    },
  );
}

function parseWalkForward(value: unknown, path: string, ctx: Ctx): ResearchWalkForward | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set(['method', 'ruleVersion', 'evaluationPartition', 'foldCount', 'windowBarCount', 'stateRuleVersion', 'stateLookbackBars', 'status', 'reason', 'folds', 'aggregate']),
    (obj) => {
      let ok = true;
      const method = requiredLiteral('expanding')(obj.method, joinPath(path, 'method'), ctx);
      const ruleVersion = requiredString(obj.ruleVersion, joinPath(path, 'ruleVersion'), ctx);
      const evaluationPartition = requiredLiteral('train')(obj.evaluationPartition, joinPath(path, 'evaluationPartition'), ctx);
      const foldCount = requiredFiniteNumber(obj.foldCount, joinPath(path, 'foldCount'), ctx);
      const windowBarCount = requiredFiniteNumber(obj.windowBarCount, joinPath(path, 'windowBarCount'), ctx);
      const stateRuleVersion = obj.stateRuleVersion === undefined ? undefined : requiredNonEmptyString(obj.stateRuleVersion, joinPath(path, 'stateRuleVersion'), ctx);
      const stateLookbackBars = obj.stateLookbackBars === undefined ? undefined : requiredPositiveInteger(obj.stateLookbackBars, joinPath(path, 'stateLookbackBars'), ctx);
      const status = requiredEnum(WALK_FORWARD_STATUSES)(obj.status, joinPath(path, 'status'), ctx);
      const reason = requiredString(obj.reason, joinPath(path, 'reason'), ctx);
      const folds = requiredArray(parseWalkForwardFold)(obj.folds, joinPath(path, 'folds'), ctx);
      const aggregate = parseObject(
        obj.aggregate,
        joinPath(path, 'aggregate'),
        ctx,
        new Set([
          'evaluatedFolds',
          'candidatePositiveReturnFolds',
          'candidateLowerDrawdownFolds',
          'candidateMedianReturn',
          'benchmarkMedianReturn',
          'candidateMedianDrawdown',
          'benchmarkMedianDrawdown',
          'candidateMedianSharpe',
          'benchmarkMedianSharpe',
          'distinctMarketRegimes',
          'regimeDiversityStatus',
          'byMarketRegime',
        ]),
        (aggObj) => {
          let aggOk = true;
          const evaluatedFolds = requiredFiniteNumber(aggObj.evaluatedFolds, joinPath(path, 'aggregate.evaluatedFolds'), ctx);
          const candidatePositiveReturnFolds = requiredFiniteNumber(aggObj.candidatePositiveReturnFolds, joinPath(path, 'aggregate.candidatePositiveReturnFolds'), ctx);
          const candidateLowerDrawdownFolds = requiredFiniteNumber(aggObj.candidateLowerDrawdownFolds, joinPath(path, 'aggregate.candidateLowerDrawdownFolds'), ctx);
          const candidateMedianReturn = requiredFiniteNumber(aggObj.candidateMedianReturn, joinPath(path, 'aggregate.candidateMedianReturn'), ctx);
          const benchmarkMedianReturn = requiredFiniteNumber(aggObj.benchmarkMedianReturn, joinPath(path, 'aggregate.benchmarkMedianReturn'), ctx);
          const candidateMedianDrawdown = requiredFiniteNumber(aggObj.candidateMedianDrawdown, joinPath(path, 'aggregate.candidateMedianDrawdown'), ctx);
          const benchmarkMedianDrawdown = requiredFiniteNumber(aggObj.benchmarkMedianDrawdown, joinPath(path, 'aggregate.benchmarkMedianDrawdown'), ctx);
          const candidateMedianSharpe = requiredFiniteNumber(aggObj.candidateMedianSharpe, joinPath(path, 'aggregate.candidateMedianSharpe'), ctx);
          const benchmarkMedianSharpe = requiredFiniteNumber(aggObj.benchmarkMedianSharpe, joinPath(path, 'aggregate.benchmarkMedianSharpe'), ctx);
          const distinctMarketRegimes = aggObj.distinctMarketRegimes === undefined ? undefined : requiredNonNegativeInteger(aggObj.distinctMarketRegimes, joinPath(path, 'aggregate.distinctMarketRegimes'), ctx);
          const regimeDiversityStatus = aggObj.regimeDiversityStatus === undefined ? undefined : requiredEnum(['covered', 'insufficient_regime_diversity'] as const)(aggObj.regimeDiversityStatus, joinPath(path, 'aggregate.regimeDiversityStatus'), ctx);
          const byMarketRegime = aggObj.byMarketRegime === undefined ? undefined : requiredArray(parseWalkForwardRegimeSummary)(aggObj.byMarketRegime, joinPath(path, 'aggregate.byMarketRegime'), ctx);
          if (
            evaluatedFolds === null ||
            candidatePositiveReturnFolds === null ||
            candidateLowerDrawdownFolds === null ||
            candidateMedianReturn === null ||
            benchmarkMedianReturn === null ||
            candidateMedianDrawdown === null ||
            benchmarkMedianDrawdown === null ||
            candidateMedianSharpe === null ||
            benchmarkMedianSharpe === null
          ) {
            aggOk = false;
          }
          if (!aggOk) return null;
          return {
            evaluatedFolds: evaluatedFolds!,
            candidatePositiveReturnFolds: candidatePositiveReturnFolds!,
            candidateLowerDrawdownFolds: candidateLowerDrawdownFolds!,
            candidateMedianReturn: candidateMedianReturn!,
            benchmarkMedianReturn: benchmarkMedianReturn!,
            candidateMedianDrawdown: candidateMedianDrawdown!,
            benchmarkMedianDrawdown: benchmarkMedianDrawdown!,
            candidateMedianSharpe: candidateMedianSharpe!,
            benchmarkMedianSharpe: benchmarkMedianSharpe!,
            ...(distinctMarketRegimes !== undefined && distinctMarketRegimes !== null ? { distinctMarketRegimes } : {}),
            ...(regimeDiversityStatus !== undefined && regimeDiversityStatus !== null ? { regimeDiversityStatus } : {}),
            ...(byMarketRegime !== undefined && byMarketRegime !== null ? { byMarketRegime } : {}),
          };
        },
      );
      if (
        method === null ||
        ruleVersion === null ||
        evaluationPartition === null ||
        foldCount === null ||
        windowBarCount === null ||
        status === null ||
        reason === null ||
        folds === null ||
        aggregate === null ||
        stateRuleVersion === null ||
        stateLookbackBars === null
      ) {
        ok = false;
      }
      const rawAggregate = isPlainObject(obj.aggregate) ? obj.aggregate : {};
      const hasRegimeFields = obj.stateRuleVersion !== undefined
        || obj.stateLookbackBars !== undefined
        || rawAggregate.distinctMarketRegimes !== undefined
        || rawAggregate.regimeDiversityStatus !== undefined
        || rawAggregate.byMarketRegime !== undefined
        || (Array.isArray(obj.folds) && obj.folds.some((fold) => isPlainObject(fold) && fold.marketRegime !== undefined));
      if (hasRegimeFields) {
        const summaries = aggregate?.byMarketRegime;
        const labels = folds?.map((fold) => fold.marketRegime?.label);
        const allFoldsHaveRegimes = labels?.every((label) => label !== undefined) ?? false;
        const uniqueSummaryLabels = summaries ? new Set(summaries.map((summary) => summary.label)) : new Set<string>();
        const regimeFoldCounts = new Map<string, number>();
        labels?.forEach((label) => { if (label) regimeFoldCounts.set(label, (regimeFoldCounts.get(label) ?? 0) + 1); });
        const summariesMatchFolds = summaries?.every((summary) => regimeFoldCounts.get(summary.label) === summary.foldCount) ?? false;
        const summariesCoverAllFoldLabels = summaries ? regimeFoldCounts.size === summaries.length : false;
        const summaryFoldCount = summaries?.reduce((total, summary) => total + summary.foldCount, 0) ?? -1;
        const statusMatchesCount = aggregate?.regimeDiversityStatus === (aggregate?.distinctMarketRegimes && aggregate.distinctMarketRegimes > 1 ? 'covered' : 'insufficient_regime_diversity');
        if (stateRuleVersion === undefined || stateRuleVersion === null || stateLookbackBars === undefined || stateLookbackBars === null || !allFoldsHaveRegimes || foldCount !== folds?.length || aggregate?.evaluatedFolds !== folds?.length || aggregate?.distinctMarketRegimes === undefined || aggregate.regimeDiversityStatus === undefined || summaries === undefined || summaries === null || aggregate.distinctMarketRegimes !== summaries.length || uniqueSummaryLabels.size !== summaries.length || !summariesMatchFolds || !summariesCoverAllFoldLabels || summaryFoldCount !== folds?.length || !statusMatchesCount) {
          ctx.missingFields.push(joinPath(path, 'regimeEvidence'));
          ctx.warnings.push(`${joinPath(path, 'regimeEvidence')} must be a complete, internally consistent authoritative projection`);
          return null;
        }
      }
      if (!ok) return null;
      return {
        method: method!,
        ruleVersion: ruleVersion!,
        evaluationPartition: evaluationPartition!,
        foldCount: foldCount!,
        windowBarCount: windowBarCount!,
        ...(stateRuleVersion !== undefined && stateRuleVersion !== null ? { stateRuleVersion } : {}),
        ...(stateLookbackBars !== undefined && stateLookbackBars !== null ? { stateLookbackBars } : {}),
        status: status!,
        reason: reason!,
        folds: folds!,
        aggregate: aggregate!,
      };
    },
  );
}

const ROBUSTNESS_PARAMETER_KEYS = {
  sma_crossover: ['fast_window', 'slow_window'],
  rsi_mean_reversion: ['period', 'entry_threshold', 'exit_threshold'],
  breakout: ['lookback_window'],
} as const;

function parseRobustnessMetrics(value: unknown, path: string, ctx: Ctx): QuantRobustnessMetrics | null {
  return parseStrictObject(value, path, ctx, new Set(['totalReturnPct', 'annualizedReturnPct', 'maximumDrawdownPct', 'sharpeRatio', 'tradeCount', 'winRatePct', 'finalEquity']), (obj) => {
    const totalReturnPct = requiredFiniteNumber(obj.totalReturnPct, joinPath(path, 'totalReturnPct'), ctx);
    const annualizedReturnPct = requiredFiniteNumber(obj.annualizedReturnPct, joinPath(path, 'annualizedReturnPct'), ctx);
    const maximumDrawdownPct = requiredFiniteNumber(obj.maximumDrawdownPct, joinPath(path, 'maximumDrawdownPct'), ctx);
    const sharpeRatio = requiredFiniteNumber(obj.sharpeRatio, joinPath(path, 'sharpeRatio'), ctx);
    const tradeCount = requiredNonNegativeInteger(obj.tradeCount, joinPath(path, 'tradeCount'), ctx);
    const winRatePct = requiredFiniteNumber(obj.winRatePct, joinPath(path, 'winRatePct'), ctx);
    const finalEquity = requiredFiniteNumber(obj.finalEquity, joinPath(path, 'finalEquity'), ctx);
    if (totalReturnPct === null || annualizedReturnPct === null || maximumDrawdownPct === null || sharpeRatio === null || tradeCount === null || winRatePct === null || finalEquity === null) return null;
    return { totalReturnPct, annualizedReturnPct, maximumDrawdownPct, sharpeRatio, tradeCount, winRatePct, finalEquity };
  });
}

function parseRobustnessParameters(value: unknown, path: string, ctx: Ctx, keys: readonly string[]): Record<string, number> | null {
  return parseStrictObject(value, path, ctx, new Set(keys), (obj) => {
    if (Object.keys(obj).join('|') !== keys.join('|')) {
      ctx.missingFields.push(path);
      ctx.warnings.push(`${path} must retain canonical parameter key order`);
      return null;
    }
    const result: Record<string, number> = {};
    for (const key of keys) {
      const number = requiredFiniteNumber(obj[key], joinPath(path, key), ctx);
      if (number === null) return null;
      result[key] = number;
    }
    return result;
  });
}

function parseRobustnessSensitivity(value: unknown, path: string, ctx: Ctx): QuantRobustnessSensitivity | null {
  return parseStrictObject(value, path, ctx, new Set(['schemaVersion', 'evaluationPartition', 'runId', 'reportArtifactId', 'candidate', 'finalTrainingComparison', 'dataset', 'interval', 'periodsPerYear', 'runtimeDescriptorDigest', 'trainingSplit', 'executionRuleVersion', 'samplerRuleVersion', 'costScenarios', 'parameterNeighbors', 'kernelCallCount']), (obj) => {
    const schemaVersion = requiredLiteral('robustness_sensitivity_v1')(obj.schemaVersion, joinPath(path, 'schemaVersion'), ctx);
    const evaluationPartition = requiredLiteral('train')(obj.evaluationPartition, joinPath(path, 'evaluationPartition'), ctx);
    const runId = requiredNonEmptyString(obj.runId, joinPath(path, 'runId'), ctx);
    const reportArtifactId = requiredNonEmptyString(obj.reportArtifactId, joinPath(path, 'reportArtifactId'), ctx);
    const candidate = parseStrictObject(obj.candidate, joinPath(path, 'candidate'), ctx, new Set(['candidateId', 'template', 'parameters', 'canonicalKey']), (candidateObj) => {
      const candidateId = requiredNonEmptyString(candidateObj.candidateId, joinPath(path, 'candidate.candidateId'), ctx);
      const template = requiredEnum(['sma_crossover', 'rsi_mean_reversion', 'breakout'] as const)(candidateObj.template, joinPath(path, 'candidate.template'), ctx);
      const canonicalKey = requiredNonEmptyString(candidateObj.canonicalKey, joinPath(path, 'candidate.canonicalKey'), ctx);
      const parameters = template === null ? null : parseRobustnessParameters(candidateObj.parameters, joinPath(path, 'candidate.parameters'), ctx, ROBUSTNESS_PARAMETER_KEYS[template]);
      if (candidateId === null || template === null || canonicalKey === null || parameters === null) return null;
      return { candidateId, template, parameters, canonicalKey };
    });
    const finalTrainingComparison = parseStrictObject(obj.finalTrainingComparison, joinPath(path, 'finalTrainingComparison'), ctx, new Set(['artifactId', 'artifactDigest']), (comparisonObj) => {
      const artifactId = requiredNonEmptyString(comparisonObj.artifactId, joinPath(path, 'finalTrainingComparison.artifactId'), ctx);
      const artifactDigest = requiredNonEmptyString(comparisonObj.artifactDigest, joinPath(path, 'finalTrainingComparison.artifactDigest'), ctx);
      return artifactId === null || artifactDigest === null ? null : { artifactId, artifactDigest };
    });
    const dataset = parseStrictObject(obj.dataset, joinPath(path, 'dataset'), ctx, new Set(['datasetId', 'datasetDigest']), (datasetObj) => {
      const datasetId = requiredNonEmptyString(datasetObj.datasetId, joinPath(path, 'dataset.datasetId'), ctx);
      const datasetDigest = requiredNonEmptyString(datasetObj.datasetDigest, joinPath(path, 'dataset.datasetDigest'), ctx);
      return datasetId === null || datasetDigest === null ? null : { datasetId, datasetDigest };
    });
    const interval = requiredEnum(['1h', '4h', '1D'] as const)(obj.interval, joinPath(path, 'interval'), ctx);
    const periodsPerYear = requiredPositiveInteger(obj.periodsPerYear, joinPath(path, 'periodsPerYear'), ctx);
    const runtimeDescriptorDigest = requiredNonEmptyString(obj.runtimeDescriptorDigest, joinPath(path, 'runtimeDescriptorDigest'), ctx);
    const trainingSplit = parseStrictObject(obj.trainingSplit, joinPath(path, 'trainingSplit'), ctx, new Set(['identityKind', 'ruleVersion', 'trainingBarCount', 'trainingStart', 'trainingEnd', 'trainingSplitDigest', 'sealedSplitDigest']), (splitObj) => {
      const identityKind = requiredEnum(['sealed_market_split', 'deterministic_legacy_split'] as const)(splitObj.identityKind, joinPath(path, 'trainingSplit.identityKind'), ctx);
      const ruleVersion = requiredLiteral('chronological-80-20-v1')(splitObj.ruleVersion, joinPath(path, 'trainingSplit.ruleVersion'), ctx);
      const trainingBarCount = requiredPositiveInteger(splitObj.trainingBarCount, joinPath(path, 'trainingSplit.trainingBarCount'), ctx);
      const trainingStart = requiredNonEmptyString(splitObj.trainingStart, joinPath(path, 'trainingSplit.trainingStart'), ctx);
      const trainingEnd = requiredNonEmptyString(splitObj.trainingEnd, joinPath(path, 'trainingSplit.trainingEnd'), ctx);
      const trainingSplitDigest = requiredNonEmptyString(splitObj.trainingSplitDigest, joinPath(path, 'trainingSplit.trainingSplitDigest'), ctx);
      const sealedSplitDigest = splitObj.sealedSplitDigest === null ? null : requiredNonEmptyString(splitObj.sealedSplitDigest, joinPath(path, 'trainingSplit.sealedSplitDigest'), ctx);
      if (identityKind === null || ruleVersion === null || trainingBarCount === null || trainingStart === null || trainingEnd === null || trainingSplitDigest === null || sealedSplitDigest === null && splitObj.sealedSplitDigest !== null) return null;
      if ((identityKind === 'sealed_market_split' && (sealedSplitDigest === null || sealedSplitDigest !== trainingSplitDigest)) || (identityKind === 'deterministic_legacy_split' && sealedSplitDigest !== null)) {
        ctx.missingFields.push(joinPath(path, 'trainingSplit.sealedSplitDigest'));
        ctx.warnings.push(`${joinPath(path, 'trainingSplit')} has an incompatible sealed split identity`);
        return null;
      }
      return { identityKind, ruleVersion, trainingBarCount, trainingStart, trainingEnd, trainingSplitDigest, sealedSplitDigest };
    });
    const executionRuleVersion = requiredLiteral('quant-execution-cost-policy-v1')(obj.executionRuleVersion, joinPath(path, 'executionRuleVersion'), ctx);
    const samplerRuleVersion = requiredLiteral('oat-parameter-neighborhood-v1')(obj.samplerRuleVersion, joinPath(path, 'samplerRuleVersion'), ctx);
    const costScenarios = requiredArray((item, itemPath, itemCtx) => parseStrictObject(item, itemPath, itemCtx, new Set(['scenario', 'multiplier', 'feeRate', 'slippageRate', 'candidateMetrics', 'benchmarkMetrics']), (scenarioObj) => {
      const scenario = requiredEnum(['baseline_1x', 'stressed_2x', 'stressed_4x'] as const)(scenarioObj.scenario, joinPath(itemPath, 'scenario'), itemCtx);
      const multiplier: 1 | 2 | 4 | null = scenarioObj.multiplier === 1 || scenarioObj.multiplier === 2 || scenarioObj.multiplier === 4
        ? scenarioObj.multiplier
        : (itemCtx.missingFields.push(joinPath(itemPath, 'multiplier')), itemCtx.warnings.push(`${joinPath(itemPath, 'multiplier')} has unsupported value`), null);
      const feeRate = requiredFiniteNumber(scenarioObj.feeRate, joinPath(itemPath, 'feeRate'), itemCtx);
      const slippageRate = requiredFiniteNumber(scenarioObj.slippageRate, joinPath(itemPath, 'slippageRate'), itemCtx);
      const candidateMetrics = parseRobustnessMetrics(scenarioObj.candidateMetrics, joinPath(itemPath, 'candidateMetrics'), itemCtx);
      const benchmarkMetrics = parseRobustnessMetrics(scenarioObj.benchmarkMetrics, joinPath(itemPath, 'benchmarkMetrics'), itemCtx);
      if (scenario === null || multiplier === null || feeRate === null || slippageRate === null || candidateMetrics === null || benchmarkMetrics === null || feeRate < 0 || slippageRate < 0) return null;
      return { scenario, multiplier, feeRate, slippageRate, candidateMetrics, benchmarkMetrics };
    }))(obj.costScenarios, joinPath(path, 'costScenarios'), ctx);
    const parameterNeighbors = requiredArray((item, itemPath, itemCtx) => parseStrictObject(item, itemPath, itemCtx, new Set(['parameterName', 'direction', 'parameters', 'canonicalKey', 'candidateMetrics']), (neighborObj) => {
      const parameterName = requiredNonEmptyString(neighborObj.parameterName, joinPath(itemPath, 'parameterName'), itemCtx);
      const direction = requiredEnum(['lower', 'upper'] as const)(neighborObj.direction, joinPath(itemPath, 'direction'), itemCtx);
      const canonicalKey = requiredNonEmptyString(neighborObj.canonicalKey, joinPath(itemPath, 'canonicalKey'), itemCtx);
      const parameters = candidate === null ? null : parseRobustnessParameters(neighborObj.parameters, joinPath(itemPath, 'parameters'), itemCtx, ROBUSTNESS_PARAMETER_KEYS[candidate.template]);
      const candidateMetrics = parseRobustnessMetrics(neighborObj.candidateMetrics, joinPath(itemPath, 'candidateMetrics'), itemCtx);
      return parameterName === null || direction === null || canonicalKey === null || parameters === null || candidateMetrics === null ? null : { parameterName, direction, parameters, canonicalKey, candidateMetrics };
    }))(obj.parameterNeighbors, joinPath(path, 'parameterNeighbors'), ctx);
    const kernelCallCount = requiredNonNegativeInteger(obj.kernelCallCount, joinPath(path, 'kernelCallCount'), ctx);
    if (schemaVersion === null || evaluationPartition === null || runId === null || reportArtifactId === null || candidate === null || finalTrainingComparison === null || dataset === null || interval === null || periodsPerYear === null || runtimeDescriptorDigest === null || trainingSplit === null || executionRuleVersion === null || samplerRuleVersion === null || costScenarios === null || parameterNeighbors === null || kernelCallCount === null) return null;
    const expectedCosts = [['baseline_1x', 1, 0.001, 0.0005], ['stressed_2x', 2, 0.002, 0.001], ['stressed_4x', 4, 0.004, 0.002]] as const;
    if (costScenarios.length !== 3 || !costScenarios.every((item, index) => item.scenario === expectedCosts[index]![0] && item.multiplier === expectedCosts[index]![1] && item.feeRate === expectedCosts[index]![2] && item.slippageRate === expectedCosts[index]![3])) return null;
    const parameterKeys = ROBUSTNESS_PARAMETER_KEYS[candidate.template];
    const validNeighborOrder = parameterKeys.flatMap((parameter) => [[parameter, 'lower'] as const, [parameter, 'upper'] as const]);
    const seenCanonicalKeys = new Set([candidate.canonicalKey]);
    let lastNeighborOrder = -1;
    for (const neighbor of parameterNeighbors) {
      const neighborOrder = validNeighborOrder.findIndex(([parameter, direction]) => parameter === neighbor.parameterName && direction === neighbor.direction);
      const changed = parameterKeys.filter((key) => neighbor.parameters[key] !== candidate.parameters[key]);
      if (neighborOrder < 0 || neighborOrder <= lastNeighborOrder || changed.length !== 1 || changed[0] !== neighbor.parameterName || seenCanonicalKeys.has(neighbor.canonicalKey)) return null;
      seenCanonicalKeys.add(neighbor.canonicalKey);
      lastNeighborOrder = neighborOrder;
    }
    if (parameterNeighbors.length > 6 || kernelCallCount !== 6 + parameterNeighbors.length || kernelCallCount > 12) return null;
    return { schemaVersion, evaluationPartition, runId, reportArtifactId, candidate, finalTrainingComparison, dataset, interval, periodsPerYear, runtimeDescriptorDigest, trainingSplit, executionRuleVersion, samplerRuleVersion, costScenarios, parameterNeighbors, kernelCallCount };
  });
}

function parseReport(value: unknown, path: string, ctx: Ctx, marketRuntime: boolean): ResearchReport | null {
  return parseObject(
    value,
    path,
    ctx,
    new Set([
      'id',
      'title',
      'conclusion',
      'proposedNextStep',
      'limitations',
      'humanReviewStatus',
      'validatorVersion',
      'generationMethod',
      'disclaimer',
      'selectionDecision',
      'iterationStop',
      'generalization',
      'walkForward',
      'robustnessSensitivity',
      'datasetQuality',
      'datasetContext',
    ]),
    (obj) => {
      let ok = true;
      const id = requiredString(obj.id, joinPath(path, 'id'), ctx);
      const title = requiredString(obj.title, joinPath(path, 'title'), ctx);
      const conclusion = requiredString(obj.conclusion, joinPath(path, 'conclusion'), ctx);
      const proposedNextStep = requiredString(obj.proposedNextStep, joinPath(path, 'proposedNextStep'), ctx);
      const limitations = requiredArray(requiredString)(obj.limitations, joinPath(path, 'limitations'), ctx);
      const humanReviewStatus = requiredString(obj.humanReviewStatus, joinPath(path, 'humanReviewStatus'), ctx);
      const validatorVersion = requiredString(obj.validatorVersion, joinPath(path, 'validatorVersion'), ctx);
      const generationMethod = requiredString(obj.generationMethod, joinPath(path, 'generationMethod'), ctx);
      const disclaimer = requiredString(obj.disclaimer, joinPath(path, 'disclaimer'), ctx);
      const selectionDecisionPresent = obj.selectionDecision !== undefined && obj.selectionDecision !== null;
      const selectionDecision = !selectionDecisionPresent ? undefined : parseStrictObject(
        obj.selectionDecision,
        joinPath(path, 'selectionDecision'),
        ctx,
        new Set(['basis', 'selectedCandidateId', 'reason', 'referenceCandidateId']),
        (decisionObj) => {
          const basis = requiredEnum(['approved_objective_rank', 'robustness_override'] as const)(decisionObj.basis, joinPath(path, 'selectionDecision.basis'), ctx);
          const selectedCandidateIdPresent = decisionObj.selectedCandidateId !== undefined;
          const selectedCandidateId = selectedCandidateIdPresent
            ? requiredString(decisionObj.selectedCandidateId, joinPath(path, 'selectionDecision.selectedCandidateId'), ctx)
            : undefined;
          const reason = decisionObj.reason === undefined ? undefined : requiredEnum(['walk_forward_stability', 'regime_coverage', 'minimum_trade_evidence'] as const)(decisionObj.reason, joinPath(path, 'selectionDecision.reason'), ctx);
          const referenceCandidateId = optionalString(decisionObj.referenceCandidateId, joinPath(path, 'selectionDecision.referenceCandidateId'), ctx);
          if (basis === null || selectedCandidateId === null || reason === null || referenceCandidateId === null) return null;
          if (basis === 'approved_objective_rank' && (reason !== undefined || referenceCandidateId !== undefined)) {
            ctx.warnings.push(`${joinPath(path, 'selectionDecision')} rank selection cannot carry a deviation`);
            ctx.missingFields.push(joinPath(path, 'selectionDecision.basis'));
            return null;
          }
          if (basis === 'robustness_override' && (reason === undefined || referenceCandidateId === undefined)) {
            ctx.warnings.push(`${joinPath(path, 'selectionDecision')} override requires a closed reason and reference candidate`);
            ctx.missingFields.push(joinPath(path, 'selectionDecision.reason'));
            return null;
          }
          return {
            basis,
            ...(selectedCandidateId ? { selectedCandidateId } : {}),
            ...(reason ? { reason } : {}),
            ...(referenceCandidateId ? { referenceCandidateId } : {}),
          };
        },
      );
      const iterationStopPresent = obj.iterationStop !== undefined;
      const iterationStop = !iterationStopPresent ? undefined : parseStrictObject(
        obj.iterationStop,
        joinPath(path, 'iterationStop'),
        ctx,
        new Set(['reason', 'referenceCandidateId']),
        (stopObj) => {
          const reason = requiredEnum(['no_novel_candidate', 'insufficient_action_budget'] as const)(stopObj.reason, joinPath(path, 'iterationStop.reason'), ctx);
          const referenceCandidateId = requiredString(stopObj.referenceCandidateId, joinPath(path, 'iterationStop.referenceCandidateId'), ctx);
          if (reason === null || referenceCandidateId === null) return null;
          return { reason, referenceCandidateId };
        },
      );
      const generalization = obj.generalization === undefined || obj.generalization === null ? undefined : parseGeneralization(obj.generalization, joinPath(path, 'generalization'), ctx);
      const walkForward = obj.walkForward === undefined || obj.walkForward === null ? undefined : parseWalkForward(obj.walkForward, joinPath(path, 'walkForward'), ctx);
      const robustnessSensitivity = obj.robustnessSensitivity === undefined || obj.robustnessSensitivity === null ? undefined : parseRobustnessSensitivity(obj.robustnessSensitivity, joinPath(path, 'robustnessSensitivity'), ctx);
      const datasetQuality = obj.datasetQuality === undefined || obj.datasetQuality === null
        ? undefined
        : marketRuntime
          ? parseMarketDatasetQuality(obj.datasetQuality, joinPath(path, 'datasetQuality'), ctx)
          : parseDatasetDataQuality(obj.datasetQuality, joinPath(path, 'datasetQuality'), ctx);
      const datasetContext = obj.datasetContext === undefined || obj.datasetContext === null ? undefined : parseObject(
        obj.datasetContext,
        joinPath(path, 'datasetContext'),
        ctx,
        new Set(['symbol', 'interval', 'periodsPerYear', 'range', 'runtimeDescriptorDigest', 'sealedSplitDigest']),
        (contextObj) => {
          const symbol = requiredString(contextObj.symbol, joinPath(path, 'datasetContext.symbol'), ctx);
          const interval = requiredEnum(['1h', '4h', '1D'] as const)(contextObj.interval, joinPath(path, 'datasetContext.interval'), ctx);
          const periodsPerYear = requiredFiniteNumber(contextObj.periodsPerYear, joinPath(path, 'datasetContext.periodsPerYear'), ctx);
          const range = parseDateRange(contextObj.range, joinPath(path, 'datasetContext.range'), ctx);
          const runtimeDescriptorDigest = requiredString(contextObj.runtimeDescriptorDigest, joinPath(path, 'datasetContext.runtimeDescriptorDigest'), ctx);
          const sealedSplitDigest = requiredString(contextObj.sealedSplitDigest, joinPath(path, 'datasetContext.sealedSplitDigest'), ctx);
          if (symbol === null || interval === null || periodsPerYear === null || range === null || runtimeDescriptorDigest === null || sealedSplitDigest === null) return null;
          return { symbol, interval, periodsPerYear, range, runtimeDescriptorDigest, sealedSplitDigest };
        },
      );
      if (
        id === null ||
        title === null ||
        conclusion === null ||
        proposedNextStep === null ||
        limitations === null ||
        humanReviewStatus === null ||
        validatorVersion === null ||
        generationMethod === null ||
        disclaimer === null ||
        (selectionDecisionPresent && selectionDecision === null) ||
        (iterationStopPresent && iterationStop === null) ||
        (obj.generalization !== undefined && obj.generalization !== null && generalization === null) ||
        (obj.walkForward !== undefined && obj.walkForward !== null && walkForward === null)
        || (obj.robustnessSensitivity !== undefined && obj.robustnessSensitivity !== null && robustnessSensitivity === null)
      ) {
        ok = false;
      }
      if (!ok) return null;
      const report: ResearchReport = {
        id: id!,
        title: title!,
        conclusion: conclusion!,
        proposedNextStep: proposedNextStep!,
        limitations: limitations!,
        humanReviewStatus: humanReviewStatus!,
        validatorVersion: validatorVersion!,
        generationMethod: generationMethod!,
        disclaimer: disclaimer!,
      };
      if (generalization != null) report.generalization = generalization;
      if (walkForward != null) report.walkForward = walkForward;
      if (robustnessSensitivity != null) report.robustnessSensitivity = robustnessSensitivity;
      if (datasetQuality != null) report.datasetQuality = datasetQuality;
      if (datasetContext != null) report.datasetContext = datasetContext;
      if (selectionDecision != null) report.selectionDecision = selectionDecision;
      if (iterationStop != null) report.iterationStop = iterationStop;
      return report;
    },
  );
}

function parseNullableReport(value: unknown, path: string, ctx: Ctx, marketRuntime: boolean): ResearchReport | null | undefined {
  if (value === null) return null;
  const parsed = parseReport(value, path, ctx, marketRuntime);
  return parsed ?? undefined;
}

function validateRobustnessSensitivity(
  report: ResearchReport | null,
  run: QuantResearchRun,
  candidates: QuantCandidate[],
  artifacts: QuantArtifact[],
  dataset: DatasetSnapshot,
  ctx: Ctx,
): boolean {
  const sensitivity = report?.robustnessSensitivity;
  if (!sensitivity) return true;
  const fail = (path: string, message: string) => {
    ctx.missingFields.push(path);
    ctx.warnings.push(message);
    return false;
  };
  if (sensitivity.runId !== run.id || sensitivity.reportArtifactId !== report!.id) return fail('report.robustnessSensitivity', 'robustness sensitivity run or report identity is inconsistent');
  const selectedCandidateId = report!.generalization?.selectedCandidateId;
  if (!selectedCandidateId || sensitivity.candidate.candidateId !== selectedCandidateId || candidates.filter((candidate) => candidate.id === selectedCandidateId).length !== 1) return fail('report.robustnessSensitivity.candidate', 'robustness sensitivity must bind the one final candidate');
  if (report!.selectionDecision?.selectedCandidateId !== undefined && report!.selectionDecision.selectedCandidateId !== selectedCandidateId) return fail('report.robustnessSensitivity.candidate', 'robustness sensitivity selection identity is inconsistent');
  const comparison = artifacts.filter((artifact) => artifact.id === sensitivity.finalTrainingComparison.artifactId && artifact.digest === sensitivity.finalTrainingComparison.artifactDigest && artifact.type === 'validation_report');
  if (comparison.length !== 1) return fail('report.robustnessSensitivity.finalTrainingComparison', 'robustness sensitivity comparison artifact is not authoritative');
  if (sensitivity.dataset.datasetId !== dataset.id || sensitivity.dataset.datasetDigest !== dataset.digest || sensitivity.interval !== dataset.interval) return fail('report.robustnessSensitivity.dataset', 'robustness sensitivity dataset identity is inconsistent');
  const split = report!.generalization!.split;
  if (sensitivity.trainingSplit.trainingBarCount !== split.trainBarCount) return fail('report.robustnessSensitivity.trainingSplit.trainingBarCount', 'robustness sensitivity training bar count is inconsistent');
  if (dataset.contract === 'market-v2') {
    const cutoffTimestampUtc = split.cutoffTimestampUtc;
    if (!isStrictUtcTimestamp(sensitivity.trainingSplit.trainingStart)
      || !isStrictUtcTimestamp(sensitivity.trainingSplit.trainingEnd)
      || !cutoffTimestampUtc
      || !isStrictUtcTimestamp(cutoffTimestampUtc)
      || sensitivity.trainingSplit.trainingStart !== dataset.dateRange.start
      || Date.parse(sensitivity.trainingSplit.trainingStart) > Date.parse(sensitivity.trainingSplit.trainingEnd)
      || Date.parse(sensitivity.trainingSplit.trainingEnd) >= Date.parse(cutoffTimestampUtc)) return fail('report.robustnessSensitivity.trainingSplit', 'market robustness sensitivity training window is inconsistent');
    if (sensitivity.periodsPerYear !== dataset.periodsPerYear
      || sensitivity.runtimeDescriptorDigest !== dataset.runtimeDescriptorDigest
      || sensitivity.trainingSplit.identityKind !== 'sealed_market_split'
      || sensitivity.trainingSplit.sealedSplitDigest !== dataset.sealedSplitDigest
      || sensitivity.trainingSplit.trainingSplitDigest !== dataset.sealedSplitDigest
      || split.descriptorDigest !== dataset.runtimeDescriptorDigest
      || split.sealDigest !== dataset.sealedSplitDigest
      || report!.datasetContext?.runtimeDescriptorDigest !== dataset.runtimeDescriptorDigest
      || report!.datasetContext?.sealedSplitDigest !== dataset.sealedSplitDigest) return fail('report.robustnessSensitivity', 'market robustness sensitivity runtime or sealed split identity is inconsistent');
  } else if (!isStrictDate(sensitivity.trainingSplit.trainingStart)
    || !isStrictDate(sensitivity.trainingSplit.trainingEnd)
    || !isStrictDate(split.cutoffDate)
    || sensitivity.trainingSplit.trainingStart !== dataset.dateRange.start
    || sensitivity.trainingSplit.trainingStart > sensitivity.trainingSplit.trainingEnd
    || sensitivity.trainingSplit.trainingEnd >= split.cutoffDate
    || sensitivity.periodsPerYear !== 252
    || sensitivity.trainingSplit.identityKind !== 'deterministic_legacy_split'
    || sensitivity.trainingSplit.sealedSplitDigest !== null) {
    return fail('report.robustnessSensitivity', 'legacy robustness sensitivity must retain deterministic training identity');
  }
  return true;
}

function parseWorkspaceSnapshot(value: unknown, ctx: Ctx): QuantWorkspaceSnapshot | null {
  return parseObject(
    value,
    '',
    ctx,
    new Set([
      'workspaceName',
      'version',
      'authenticity',
      'runtimeLabel',
      'modelLabel',
      'project',
      'recentProjects',
      'scope',
      'run',
      'limits',
      'plan',
      'researchPlan',
      'researchMemory',
      'events',
      'artifacts',
      'dataset',
      'bars',
      'kernelCheck',
      'benchmark',
      'candidates',
      'liveResearch',
      'performanceSeries',
      'trades',
      'report',
      'composerLegalCommands',
    ]),
    (obj) => {
      let ok = true;
      const marketSignal = hasMarketSnapshotSignal(obj);
      const legacySignal = hasExplicitLegacySnapshotSignal(obj);
      if (marketSignal && legacySignal) {
        ctx.missingFields.push('dataset.contract');
        ctx.warnings.push('workspace snapshot mixes explicit legacy and market runtime identity');
        return null;
      }
      const workspaceName = requiredString(obj.workspaceName, 'workspaceName', ctx);
      const version = requiredString(obj.version, 'version', ctx);
      const authenticity = requiredEnum(AUTHENTICITY_VALUES)(obj.authenticity, 'authenticity', ctx);
      const runtimeLabel = requiredString(obj.runtimeLabel, 'runtimeLabel', ctx);
      const modelLabel = requiredString(obj.modelLabel, 'modelLabel', ctx);
      const project = parseResearchProject(obj.project, 'project', ctx);
      const recentProjects = requiredArray(parseResearchProject)(obj.recentProjects, 'recentProjects', ctx);
      const scope = parseResearchScope(obj.scope, 'scope', ctx);
      const run = parseResearchRun(obj.run, 'run', ctx);
      const limits = parseLimits(obj.limits, 'limits', ctx);
      const plan = requiredArray(parsePlanStep)(obj.plan, 'plan', ctx);
      const researchPlan = parseExecutableResearchPlan(obj.researchPlan, 'researchPlan', ctx);
      const researchMemory = parseResearchMemoryProjection(obj.researchMemory, 'researchMemory', ctx);
      const events = requiredArray(parseRunEvent)(obj.events, 'events', ctx);
      const artifacts = requiredArray(parseArtifact)(obj.artifacts, 'artifacts', ctx);
      const dataset = parseDatasetSnapshot(obj.dataset, 'dataset', ctx, marketSignal);
      const bars = requiredArray(parseMarketBar)(obj.bars, 'bars', ctx);
      const kernelCheck = parseKernelCheck(obj.kernelCheck, 'kernelCheck', ctx);
      const benchmark = parseNullableBacktestMetrics(obj.benchmark, 'benchmark', ctx);
      const candidates = requiredArray(parseCandidate)(obj.candidates, 'candidates', ctx);
      const liveResearch = parseNullableLiveResearch(obj.liveResearch, 'liveResearch', ctx);
      const performanceSeries = optionalArray(parsePerformanceSeries)(obj.performanceSeries, 'performanceSeries', ctx) ?? [];
      const trades = requiredArray((item, path, tradeCtx) => parseTrade(item, path, tradeCtx, marketSignal))(obj.trades, 'trades', ctx);
      const report = parseNullableReport(obj.report, 'report', ctx, marketSignal);
      const composerLegalCommands = requiredArray(requiredEnum(COMMANDS))(obj.composerLegalCommands, 'composerLegalCommands', ctx);
      const anyNull =
        workspaceName === null ||
        version === null ||
        authenticity === null ||
        runtimeLabel === null ||
        modelLabel === null ||
        project === null ||
        recentProjects === null ||
        scope === null ||
        run === null ||
        limits === null ||
        plan === null ||
        researchPlan === null ||
        researchMemory === null ||
        events === null ||
        artifacts === null ||
        dataset === null ||
        bars === null ||
        kernelCheck === null ||
        benchmark === undefined ||
        candidates === null ||
        liveResearch === undefined ||
        (liveResearch === null && obj.liveResearch !== null) ||
        trades === null ||
        report === undefined ||
        composerLegalCommands === null;
      if (anyNull) ok = false;
      if (!ok) return null;
      const marketRuntime = dataset!.contract === 'market-v2';
      if (marketSignal !== marketRuntime) {
        ctx.warnings.push('workspace snapshot contract signals do not match its parsed dataset identity');
        ctx.missingFields.push('dataset.contract');
        return null;
      }
      if (scope!.interval !== dataset!.interval
        || scope!.symbol !== dataset!.symbol
        || scope!.dateRange.start !== dataset!.dateRange.start
        || scope!.dateRange.end !== dataset!.dateRange.end) {
        ctx.warnings.push('scope and dataset identity are inconsistent');
        ctx.missingFields.push('scope');
        return null;
      }
      if (marketRuntime) {
        const split = report?.generalization?.split;
        const reportContext = report?.datasetContext;
        const timestamps = [dataset!.dateRange.start, dataset!.dateRange.end, ...bars!.map((bar) => bar.date), ...performanceSeries.flatMap((series) => series.points.map((point) => point.date)), ...trades!.flatMap((trade) => [trade.entryDate, trade.exitDate]), ...(split?.cutoffTimestampUtc ? [split.cutoffTimestampUtc] : []), ...(split?.rangeStartUtc ? [split.rangeStartUtc] : []), ...(split?.rangeEndUtc ? [split.rangeEndUtc] : []), ...(reportContext ? [reportContext.range.start, reportContext.range.end] : [])];
        if (!timestamps.every(isStrictUtcTimestamp)) {
          ctx.warnings.push('market runtime timestamps must be RFC3339 UTC values');
          ctx.missingFields.push('dataset.dateRange');
          return null;
        }
        const marketDataset = dataset!;
        if (marketDataset.contract !== 'market-v2' || marketDataset.periodsPerYear === null
          || kernelCheck!.interval !== marketDataset.interval
          || kernelCheck!.periodsPerYear !== marketDataset.periodsPerYear
          || kernelCheck!.runtimeDescriptorDigest !== marketDataset.runtimeDescriptorDigest
          || kernelCheck!.sealedSplitDigest !== marketDataset.sealedSplitDigest) {
          ctx.warnings.push('market runtime kernel identity is incomplete or inconsistent');
          ctx.missingFields.push('kernelCheck');
          return null;
        }
        if (split && (split.interval !== marketDataset.interval
          || split.periodsPerYear !== marketDataset.periodsPerYear
          || split.datasetId !== marketDataset.id
          || split.datasetDigest !== marketDataset.digest
          || split.rangeStartUtc !== marketDataset.dateRange.start
          || split.rangeEndUtc !== marketDataset.dateRange.end
          || split.descriptorDigest !== marketDataset.runtimeDescriptorDigest
          || split.sealDigest !== marketDataset.sealedSplitDigest)) {
          ctx.warnings.push('market runtime generalization split is inconsistent');
          ctx.missingFields.push('report.generalization.split');
          return null;
        }
        if (reportContext && (reportContext.symbol !== marketDataset.symbol
          || reportContext.interval !== marketDataset.interval
          || reportContext.periodsPerYear !== marketDataset.periodsPerYear
          || reportContext.range.start !== marketDataset.dateRange.start
          || reportContext.range.end !== marketDataset.dateRange.end
          || reportContext.runtimeDescriptorDigest !== marketDataset.runtimeDescriptorDigest
          || reportContext.sealedSplitDigest !== marketDataset.sealedSplitDigest)) {
          ctx.warnings.push('market runtime report identity is inconsistent');
          ctx.missingFields.push('report.datasetContext');
          return null;
        }
        if (report && !reportContext) {
          ctx.warnings.push('market runtime report identity is required');
          ctx.missingFields.push('report.datasetContext');
          return null;
        }
        run!.contract = 'market-v2-private';
      } else if (run!.contract !== 'legacy-daily-v1') {
        ctx.warnings.push('legacy workspace snapshot cannot declare a market run contract');
        ctx.missingFields.push('run.contract');
        return null;
      }
      if (!validateRobustnessSensitivity(report!, run!, candidates!, artifacts!, dataset!, ctx)) return null;
      return {
        workspaceName: workspaceName!,
        version: version!,
        authenticity: authenticity!,
        runtimeLabel: runtimeLabel!,
        modelLabel: modelLabel!,
        project: project!,
        recentProjects: recentProjects!,
        scope: scope!,
        run: run!,
        limits: limits!,
        plan: plan!,
        researchPlan: researchPlan ?? undefined,
        researchMemory: researchMemory ?? undefined,
        events: events!,
        artifacts: artifacts!,
        dataset: dataset!,
        bars: bars!,
        kernelCheck: kernelCheck!,
        benchmark: benchmark!,
        candidates: candidates!,
        liveResearch: liveResearch!,
        performanceSeries,
        trades: trades!,
        report: report!,
        composerLegalCommands: composerLegalCommands!,
      };
    },
  );
}

export function parseQuantWorkspaceSnapshot(value: unknown): QuantWorkspaceSnapshotParseResult {
  const ctx = emptyCtx();

  if (!isPlainObject(value)) {
    ctx.warnings.push('Workspace snapshot must be an object');
    return {
      snapshot: null,
      compatibility: {
        schemaVersion: '',
        supported: false,
        degraded: true,
        missingFields: [],
        unknownFields: [],
        warnings: ctx.warnings,
      },
    };
  }

  const version = typeof (value as Record<string, unknown>).version === 'string'
    ? (value as Record<string, unknown>).version as string
    : undefined;

  if (!version || !QUANT_WORKSPACE_SUPPORTED_VERSIONS.has(version)) {
    return {
      snapshot: null,
      compatibility: {
        schemaVersion: version ?? String((value as Record<string, unknown>).version ?? 'missing'),
        supported: false,
        degraded: false,
        missingFields: [],
        unknownFields: [],
        warnings: [
          `Unsupported workspace snapshot version "${version ?? 'missing'}"; expected "${QUANT_WORKSPACE_SUPPORTED_VERSION}"`,
        ],
      },
    };
  }

  const snapshot = parseWorkspaceSnapshot(value, ctx);
  const supported = ctx.missingFields.length === 0 && snapshot !== null;
  const degraded = ctx.warnings.length > 0 || ctx.missingFields.length > 0;

  return {
    snapshot,
    compatibility: {
      schemaVersion: version,
      supported,
      degraded,
      missingFields: ctx.missingFields,
      unknownFields: ctx.unknownFields,
      warnings: ctx.warnings,
    },
  };
}
