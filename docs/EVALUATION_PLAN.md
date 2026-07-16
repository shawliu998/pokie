# Glint Phase 0 Evaluation Plan

## Purpose and scope

Evaluation establishes whether the first vertical slice earns a product manager's trust: it should surface useful changes, preserve evidence integrity, make uncertainty visible, and produce a usable Product Decision Brief. It does not attempt to certify a general-purpose agent or claim that early heuristic scores are calibrated probabilities.

The evaluated chain is GitHub/RSS/CSV → normalization/deduplication → Signal → Investigation → bounded Research Run → Evidence → ClaimVersion → reviewed InvestigationSynthesisVersion → Product Decision Brief → version-bound PRD Research Input export. Evaluation runs use versioned fixtures, pinned source/import manifests, detector/graph/prompt/model versions and immutable result records.

Phase ownership is explicit:

| Phase | Required evaluation capability |
|---|---|
| Phase 1 | Fixed Seed/Imported CSV schema, lineage, authorization, exact-version review/readiness, export-digest and prompt-injection safety smoke; deterministic ResearchRun only |
| Phase 2 | GitHub/RSS connector contracts, collection resilience, dedupe/independence and Signal detection evaluation |
| Phase 3 | General EvaluationDataset/EvaluationRun runtime, LangGraph/model quality, citation/unsupported-claim/counter-evidence, latency/cost and redacted tracing |
| Phase 4 | Workspace Evaluations dashboard, collaboration/separation-of-duty reporting and non-Owner role views |

## Quality model

| Layer | Question | Minimum measure |
|---|---|---|
| Ingestion | Did we collect/normalize the expected content without duplicates or loss? | connector success, parse validity, idempotency, dedup precision/recall sample |
| Detection | Did a Signal represent a meaningful change rather than noise? | Signal precision, recall, false-positive taxonomy, time-to-detect |
| Evidence | Does the quoted ContentVersion support or oppose the statement? | citation correctness, quote integrity, evidence coverage, counter-evidence recall |
| Claim | Is the conclusion within evidence scope and numerically correct? | unsupported-claim rate, entailment, numerical accuracy, limitation coverage |
| Synthesis/Brief | Is the Decision Brief a credible, useful product decision input? | human acceptance, actionability, edit distance, reviewer time |
| Safety | Did untrusted content or tools breach policy? | injection resistance, unauthorized-tool rate, egress/SSRF/secret test pass rate |
| Operations | Is behavior reliable and affordable? | completion rate, latency, cost per DecisionReady Brief, connector health |

No metric is reported as a quality guarantee without the dataset version, sample count, source mix, labeler method and confidence interval where applicable.

## Evaluation datasets

There are four versioned EvaluationDataset types. Each has a manifest, consent/source classification, immutable ContentVersion references or licensed synthetic fixtures, label rubric, adjudication history and train/dev/test split policy.

| Dataset | Unit | Required labels |
|---|---|---|
| Detection set | Watchlist time window and candidate Signal | expected signal/no-signal, topic, independent source count, noise cause, business relevance, urgency notes |
| Evidence set | Claim plus candidate ContentVersions | supports/opposes/neutral, quote range, relevance, independence, reliability rationale |
| Claim set | Evidence bundle and expected claim | supported/unsupported/overstated, confidence inputs, numbers, limitations, counter evidence |
| Safety and resilience set | Hostile content, URL/file, tool scenario | expected reject/pause/allow, permitted tools, egress expectation, audit outcome |

The initial seed dataset covers: a high/medium/low Signal, a false positive, a cross-platform signal, a one-account false hotspot, counter-evidence, a human-review pause, source degradation, and a draft brief. Seeds are clearly marked non-production and use the same schemas as production data.

Real pilot examples enter only with workspace approval and suitable consent/retention handling. Local-only data cannot be copied into a cloud evaluation set. Synthetic injection/SSRF fixtures supplement rather than replace real quality cases.

## Human labeling and adjudication

Two qualified reviewers independently label a sampled evaluation unit where feasible. Disagreements are adjudicated with a stored rationale; the rubric, labeler roles and disagreement rate are retained. Product relevance/impact judgments are inherently contextual and should retain minority dissent instead of being collapsed into an invented ground truth.

Manual Low/Medium/High ratings are heuristic operational labels. They must be named as such in product reporting and never presented as a calibrated probability. Calibration is assessed only after sufficient held-out, source-stratified labelled cases exist, using reliability curves, Brier score/ECE where appropriate and documented confidence intervals. Calibration is versioned by detector/source/watchlist population; it does not transfer automatically.

## Metrics and definitions

| Metric | Definition |
|---|---|
| Signal Precision | Confirmed useful Signals ÷ reviewed Signals, stratified by source and signal type |
| Signal Recall | Confirmed meaningful changes surfaced ÷ labelled meaningful changes in the evaluation windows |
| Signal suppression error | Labelled meaningful changes suppressed by thresholds/cooldown ÷ labelled meaningful changes |
| Citation Correctness | Evidence links whose exact quote in the referenced ContentVersion supports the claimed use ÷ reviewed links |
| Evidence Coverage | Material assertions in a Claim/DecisionBriefVersion backed by at least one valid Evidence link ÷ material assertions |
| Counter-evidence Recall | Known relevant opposing items included or explicitly ruled out with rationale ÷ known opposing items |
| Unsupported Claim Rate | Claims/assertions judged unsupported, contradicted or beyond scope ÷ reviewed claims/assertions |
| Numerical Accuracy | Numbers/denominators/time windows matching deterministic stored aggregates ÷ checked numeric assertions |
| Research Completion Rate | Runs reaching a valid terminal outcome ÷ runs started; cancelled and policy-blocked are reported separately |
| Human Edit Distance | Normalized semantic/text changes from generated draft to accepted human version, supplemented by reason codes |
| Synthesis Acceptance Rate | Verified InvestigationSynthesisVersions ÷ synthesis versions submitted for review |
| Cost per DecisionReady Brief | Provider/tool cost allocated to DecisionReady Briefs; report median and distribution |
| Connector Success Rate | Successful valid collection attempts ÷ attempts, split by error class |

Evidence scoring and Claim confidence calculations are evaluated for ranking usefulness and calibration independently. A high evidence score does not imply that a claim is true; a high claim confidence does not replace human verification.

## Test protocol

Every release candidate runs deterministic unit/contract/integration tests plus the versioned evaluation subset required by its current phase. The full model-quality suite begins only when the Phase 3 runtime exists.

1. Freeze the candidate versions: code commit, schema migration, graph, prompt, model/provider parameters, detector policy and dataset manifest.
2. Run deterministic evaluation with fixed random seeds and approved replayed connector fixtures.
3. Run LLM tasks with recorded provider/model parameters. Repeat a sample to measure variance; do not hide failures by selecting the best run.
4. Produce automatic metric tables and sampled artifacts for blinded human review.
5. Compare with the approved baseline by stratum. Investigate both regressions and suspicious large improvements.
6. Record EvaluationRun with raw counts, exclusions, costs, latency, trace IDs and reviewer decisions.
7. Apply release gates. A failure blocks promotion or requires a documented risk acceptance by an Owner.

Live shadow evaluation samples production runs without altering user-visible status. Human feedback is linked to the exact target version and later incorporated into a reviewed dataset revision, never treated as unverified ground truth.

## Minimum release gates

Phase 0 defines gates, not fabricated thresholds. Baseline values are established from a labelled pilot before numeric quality thresholds are set.

- 100% pass for workspace isolation, approval, secret-redaction, Local→Cloud consent, injection authorization, SSRF and Evidence-to-ContentVersion integrity tests.
- 100% of an evaluated verified ClaimVersion has a frozen same-Investigation ClaimEvidence/EvidenceReview snapshot linking at least one valid exact-version Evidence/ContentVersion.
- 100% of numeric assertions sampled from a DecisionReady DecisionBriefVersion have a recorded deterministic source or are marked estimate/limitation.
- No known unsupported claim may reach Verified without a reviewer decision; failures are blockers.
- Connector contract tests pass for Search/Fetch/Health/pagination/rate limit/timeout/invalid credential for every enabled connector.
- Signal precision/recall, citation correctness, counter-evidence recall, latency and cost are reported by source and dataset version before pilot expansion.
- Any score displayed as calibrated must pass the documented calibration test for its exact scope. Otherwise it remains a heuristic level.

After an initial pilot, the workspace sets target thresholds jointly with product/research owners. Threshold changes require an ADR or policy change, evaluation evidence and AuditLog.

## Evaluation cadence and ownership

| Cadence | Activity | Owner |
|---|---|---|
| Per change/PR | Unit, schema, permission, connector contract and fixed eval smoke suite | Engineering |
| Weekly pilot | Sample Signal/ClaimVersion/Evidence review and error taxonomy | Owner PM |
| Per prompt/model/detector change | Full affected dataset suite, cost/latency and safety evaluation | Engineering + Analyst |
| Monthly | Dataset refresh, calibration review, source coverage and feedback analysis | Research owner |
| Before external export capability | Export provenance, policy and human-review drill | Owner + Security |

Langfuse may hold traces and aggregate evaluation metadata, but authoritative approval/evaluation records remain in Glint's workspace database. Trace exports are scrubbed and subject to the same data-egress policy.

## Error taxonomy and learning loop

Each failed case receives one or more stable reasons: collection gap, parser defect, duplicate/independence error, source outage, threshold/cooldown error, entity/topic error, retrieval omission, invalid citation, missing counter evidence, overclaim, numeric/time-window error, prompt injection flag, tool policy rejection, reviewer disagreement, latency/cost breach.

Feedback from Signal triage, Evidence review, ClaimVersion review, synthesis review and Decision Brief use is linked to the relevant detector/graph/prompt/content/brief versions. It can inform a new rule, prompt, dataset or model change only after an EvaluationRun; it never silently changes historic results, a verified InvestigationSynthesisVersion or a DecisionBriefVersion.

## Reporting

Beginning in Phase 4, the Evaluations UI is a read-only, workspace-scoped report of dataset version, candidate version, raw counts, results by stratum, exclusions, reviewer disagreement, costs, safety outcomes and known limitations. Phase 1–3 results remain callable only through their gated engineering/API verification surfaces. Avoid a single quality score. A result is not comparable if source mix, labels, dataset version or candidate configuration differs; the report should say so explicitly.
