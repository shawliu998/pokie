# Qurio portfolio release checklist

This checklist is intentionally separate from implementation. Changing the GitHub default
branch, pushing commits, creating tags, and publishing a Release are external mutations and
require explicit approval.

## Release gate

- [ ] The latest Qurio branch is the repository default branch.
- [ ] GitHub Actions is green for Phase 1, Phase 2, Phase 3, security audit, and macOS native.
- [ ] The README preview, video, case study, architecture, evidence JSON, Chinese brief, and
      AGI application evidence index links work in an incognito browser.
- [ ] The committed Kraken evidence SHA-256 is
      `9bc4c3c084b731f7db724db880fadd34f7d9ae7720a361b6193c27262ae3c106`.
- [ ] The supplemental Wind integration evidence SHA-256 is
      `32711e26c715f6cc4c76f4c1d4101179573ec1c6a87031e3ebcee190af6d679d`;
      the release contains the sanitized JSON and case study, not the raw CSV or SQLite state.
- [ ] A fresh macOS package is built from the exact reviewed commit. Do not reuse the older
      `.run/release/Qurio-macos-arm64-0.1.0.zip`.
- [ ] The fresh app launches on Apple silicon, opens the no-key demo, and reopens the guided demo.
- [ ] The DMG/ZIP contains no Provider credential, local session file, or `.run` database.
- [ ] Release artifact SHA-256 values are calculated after the final archive is created.
- [ ] The absence of Developer ID notarization is stated clearly.

## Recommended release identity

```text
Tag: v0.1.0-portfolio
Title: Qurio v0.1.0 — verifiable Research Agent portfolio build
```

Recommended assets:

```text
Qurio-macos-arm64-0.1.0.dmg
Qurio-macos-arm64-0.1.0.dmg.sha256
Qurio-macos-arm64-0.1.0.zip
Qurio-macos-arm64-0.1.0.zip.sha256
qurio-v1-kraken-deepseek.json
qurio-wind-csi300-deepseek.json
qurio-90-second-mainline.webm
```

## Release description

> Qurio is an AI-native quantitative-research workspace powered by one bounded,
> verifiable Research Agent.
>
> This portfolio build includes the retained Data → Research → Compare → Analyze →
> Continue / History loop, a read-only real-provider guided demo, the Kraken/DeepSeek
> reasoning-and-repair case, and an Apple-silicon macOS application.
>
> The canonical case is intentionally a negative result: after one typed tool-call
> repair and an evidence-based candidate override, the selected strategy failed the
> fresh sealed holdout. Qurio retained `revise_research` rather than promoting it.
>
> This release demonstrates an engineering and product boundary. It does not claim
> future alpha, production reliability, or completed user validation.
>
> The macOS build is ad-hoc signed and not notarized. macOS may require explicit
> approval in Privacy & Security after download.

## Repository metadata

Suggested GitHub description:

> Verifiable autonomous Research Agent for evidence-led quantitative research.

Suggested topics:

```text
ai-agent
deepseek
quantitative-research
tauri
fastapi
react
agentic-ai
```

## Final reviewer test

Ask someone unfamiliar with the project to open the repository without explanation:

1. At 15 seconds, can they say what Qurio does?
2. At 90 seconds, can they explain why the Agent is verifiable?
3. At five minutes, can they find the failed tool call, repair, selection reason, and holdout
   failure?
4. Can they distinguish the Binance video case from the canonical Kraken case?
5. Can they state what the project does not claim?

If any answer is “no,” fix the entry path before adding features.
