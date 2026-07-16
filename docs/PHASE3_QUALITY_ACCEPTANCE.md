# Phase 3 Model Quality Acceptance Record

Verification date: 2026-07-16

## Status

This record uses only `Passed`, `Provisionally Passed`, `Pending`, `Failed`, and `Not Applicable`.

| Verification layer | Status | Recorded boundary |
| --- | --- | --- |
| Deterministic reviewed replay gate | **Provisionally Passed** | Synthetic mechanism and safety gate only. |
| Live provider adapter smoke | **Passed** | Three consecutive bounded synthetic calls; no response body retained. |
| Live held-out quality evaluation | **Pending** | No approved held-out provider evaluation is recorded. |
| Live Mac owner workflow | **Pending** | No complete model-assisted human-review-to-export run is recorded. |
| External PM pilot | **Pending** | No target-user participant result is recorded. |
| Phase 3 acceptance | **Pending** | A replay gate and adapter smoke are insufficient for acceptance. |

The final opt-in live DeepSeek smoke candidate also passed three consecutive runs on 2026-07-16.
Each run sent the same repository-owned synthetic ContentVersion through the fixed six-node graph;
each produced two exact Evidence proposals and one ClaimVersion proposal. Pre-final integration
runs are not hidden: one provider response echoed the request and failed closed at schema
validation, and another supplied an invalid character offset and failed closed with zero proposal
persistence. The final runtime now asks for verbatim quote text and deterministically derives a
unique offset from the frozen source, after which the recorded candidate passed 3/3 runs. No
provider response body, prompt, Claim text, source body or credential was retained as acceptance
output. This proves the live adapter contract can complete; it does not change the provisional
quality status below.

The named `Glint Phase 3 Reviewed Model Quality Replay Set`, version
`phase3-model-quality-v1.0.0-20260716`, is a repository-reviewed synthetic fixture set. It
exercises the typed model-proposal boundary without a provider key or network call. The result is
evidence that the evaluator and safety gate behave deterministically; it is not evidence of live
DeepSeek, OpenAI, or other provider quality, pilot usefulness, calibrated probabilities, latency,
cost, or production readiness.

## Reproducible gate

Run:

```bash
./scripts/verify_phase3_quality.sh
```

The gate executes mutation-tested replay evaluation and the existing end-to-end prompt-injection
containment test. CI does not require or read a model-provider secret.

The independent `phase3-quality` CI job uploads four deterministic artifacts:

| Artifact | Contents |
| --- | --- |
| `phase3-quality-report.json` | Metric numerators, denominators, thresholds and provisional status. |
| `phase3-failure-reasons.json` | Stable failure-reason counts, including an empty map on a clean replay. |
| `phase3-prompt-manifest.json` | Prompt identifiers and the quote/offset/tool contract; no prompt text. |
| `phase3-eval-manifest.json` | Dataset digest, case IDs, candidate identifiers, review metadata and thresholds. |

None of these artifacts contains a prompt body, source body, provider response or credential.

The reviewed replay result is:

| Metric | Result | Provisional target | Denominator |
|---|---:|---:|---:|
| Citation correctness | 1.00 | >= 0.95 | 5 evidence candidates |
| Unsupported claim rate | 0.00 | <= 0.05 | 2 claims |
| Counter-evidence recall | 1.00 | >= 0.80 | 2 adjudicated opposing items |
| Numerical accuracy | 1.00 | = 1.00 | 4 checked facts |
| Prompt-injection authorization pass rate | 1.00 | = 1.00 | 2 hostile-content cases |

The evaluator fails the gate for an unknown `ContentVersion`, an out-of-bounds quote, a quote
digest mismatch, an unsupported or unpinned claim, omitted counter-evidence, a wrong numerical
value/window/denominator, or any unauthorized tool request, side effect, policy change, export,
secret output, or persisted proposal in a flagged injection case. Its report contains metric
metadata and stable failure reason counts, not fixture bodies or secrets.

## Frozen replay contract

Each evidence candidate binds `content_version_id`, `quote_start`, `quote_end`,
`quote_text_digest`, stance, extraction method and injection flags. Each claim binds limitations,
evidence IDs, `generation_method=model`, generator version and prompt references. The fixture's
canonical digest prevents changed labels or source material from silently retaining reviewed
status.

The replay contract is provider-neutral. A DeepSeek adapter may map its validated structured
response into this shape, but provider text is never trusted as a citation or authorization
decision merely because it matches the shape.

## Remaining Phase 3 acceptance evidence

Before Phase 3 can be marked accepted:

1. Freeze and run the actual bounded graph, prompt, provider/model and parameters against an
   approved held-out evaluation set; preserve every run rather than selecting the best output.
2. Record live-provider completion, latency, token/cost accounting and redacted trace evidence.
3. Run the model-assisted Mac owner path through human evidence/claim/synthesis review and a
   version-bound Brief export.
4. Obtain workspace model-egress policy and consent evidence for any non-public content sent to a
   provider.
5. Calibrate or revise the provisional thresholds using pilot labels. The current four synthetic
   cases are intentionally too small for a quality or generalization claim.

No API key value, provider response body, source body, raw prompt, or secret is an allowed
acceptance artifact.
