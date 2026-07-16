# Glint 90-second demo script

Status: script ready; recording and publishable screenshots are **Pending**.

## Before recording

- Use a real `Glint.app` run at one consistent window size. Do not show browser
  developer tools, terminal windows, Keychain contents, tokens, or private data.
- Choose exactly one evidence mode and say it aloud. Until live-smoke evidence is
  recorded, use the deterministic synthetic fixture and call it a **fixture**.
- Keep the visible authenticity badge in frame. A `Collected` lineage badge does
  not convert a fixture run into a live run.
- Reset fixture state before the take. Do not splice screens from different data
  modes into a single apparent workflow.

## Timeline

### 0–15 seconds — problem and audience

Show the workbench shell and say:

> Product teams see changes across feedback and public sources, but lose the
> reasoning between a signal and a roadmap decision. Glint keeps that path
> evidence-backed. This take uses deterministic synthetic fixture data—no live
> network collection and no LLM.

Point out Inbox, Investigations, Decisions, and Monitoring. Do not describe an
unimplemented destination.

### 15–30 seconds — Signal Inbox

Open the Inbox and select the permission-friction Signal. Show its freshness,
data-lineage label, detection confidence, and pending human Impact/Urgency
confirmation. Say that the trigger is deterministic and explainable rather than
model-generated.

### 30–50 seconds — trigger and source evidence

Show the trigger rules, current/baseline counts, source freshness, and stated
limitations. Open the immutable source viewer before accepting any evidence.
Call out that the quote is bound to a `ContentVersion`, and that external content
is treated as untrusted input.

### 50–70 seconds — Evidence and Claim review

Open the Investigation. Compare supporting and opposing Evidence, record the
Evidence review, then inspect the Claim's support/counter counts and limitations.
Verify only the Claim version shown. Explain that reviews are append-only and a
counter-search record is retained when no counter-evidence is found.

### 70–90 seconds — Decision Brief and export

Open the reviewed synthesis and Decision Brief. Show the recommendation,
evidence summary, risks, limitations, owner/reviewer metadata if present in the
candidate, and the decision-ready review. Open PRD Research Input Preview and
show that it names the exact Decision Brief version and authenticity marker.
Stop before implying that a local copy/download is external publication.

## Capture checklist

The portfolio requires real-app captures for:

1. Inbox
2. Signal Detail
3. Investigation Evidence Review
4. Decision Brief
5. Monitoring

Target paths under `docs/assets/` are reserved, but no files should be added
until every capture passes the privacy/authenticity review. There is currently
no recorded video artifact.
