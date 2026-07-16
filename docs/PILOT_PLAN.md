# Glint P2.5 pilot plan

Status: **Planned, not started**. No participant has been recruited and no pilot
result is reported by this repository.

## Objective and participants

Recruit 3–5 product managers or product-research owners from small teams who
regularly turn competitor or user evidence into prioritization input. The study
tests whether Glint makes the reasoning chain understandable and reviewable; it
does not test production scale or model quality.

Do not invite external participants to bypass macOS Gatekeeper. Start the
external pilot only after the candidate distribution is Developer ID signed and
notarized, or use a supervised internal build with an explicitly documented
installation boundary.

## Study setup

- Duration: 35–45 minutes per participant, moderated.
- Data mode: a reset deterministic fixture for comparability; a separately
  consented public-data live run may be observed only after live-smoke approval.
- Disclosure: state the exact mode, that the current path uses **No LLM**, and
  that fixture behavior is not evidence of live-connector reliability.
- Privacy: use no participant company secrets, private repositories, production
  credentials, or unapproved feeds. Record screen/audio only with consent.
- Roles: one moderator, one note-taker/reviewer, and one decision owner for the
  pilot recommendation. Record `Owner`, `Reviewer`, `Last reviewed by`, review
  timestamp, activity summary, and decision responsibility in the session log.

## Participant tasks

1. Decide whether one Signal is worth investigating.
2. Find why the Signal was detected and identify its source/freshness.
3. Inspect both supporting and opposing Evidence, or locate the explicit
   counter-search record.
4. Review a Claim and explain what would make it unacceptable.
5. Form and review a Decision Brief.
6. Preview and export the version-bound PRD Research Input Markdown.

The moderator must not teach the domain vocabulary before the participant has
attempted each task. Assistance is recorded with the task timestamp.

## Measures

Record raw observations per participant; do not invent or backfill values.

| Measure | Start | Stop | Record |
| --- | --- | --- | --- |
| Time to first understand Signal | Signal list appears | Participant explains what changed and why | Seconds, interpretation, assistance |
| Time to find source | Task prompt ends | Participant opens the correct source/version | Seconds, wrong turns |
| Evidence review time | Investigation opens | Participant states support and counter-evidence assessment | Seconds, missing concepts |
| Conclusion acceptance | Decision Brief shown | Participant accepts/rejects with a reason | Yes/no, reason, confidence |
| Recommendation actionability | Brief review ends | Participant names a concrete next decision/action or says none | Yes/no, verbatim rationale |
| Most confusing concept | End of workflow | Participant identifies one concept or none | Verbatim response |
| Weekly-use intent | End of session | Participant answers the question | 1–5 rating plus reason |

Also log task completion, critical errors, moderator interventions, offline or
degraded-source encounters, and whether the participant noticed authenticity and
freshness labels.

## Session record

For each participant create a private, access-controlled record outside this
public repository containing:

```text
Participant code:
Role / team context:
Build commit SHA:
Data mode: Deterministic Fixture | Live verification
Owner:
Reviewer:
Last reviewed by:
Review timestamp:
Activity summary:
Decision responsibility:
Task observations and timings:
Confusing concepts:
Weekly-use rating and rationale:
Consent / recording status:
```

Never commit participant identities, recordings, credentials, or confidential
source content here.

## Analysis and decision rule

Two researchers independently review notes, reconcile disagreements, and retain
both raw observations and the coded summary. Report denominators and missing
data. With only 3–5 participants, findings are directional and must not be
presented as statistical proof.

The pilot owner may recommend another iteration when participants can complete
the vertical path but repeatedly misunderstand a bounded concept. A Phase 3
recommendation additionally requires the repository's final P2.5 technical
acceptance, publishable authenticity evidence, and no unresolved critical
security or data-loss issue. Pilot completion alone does not imply production or
GA readiness.

## Current result

No sessions run. Metrics, quotes, success rates, and product recommendations are
all **Pending**.
