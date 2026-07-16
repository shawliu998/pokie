# ADR 0004: Separate Cloud Source, Local Source, and Imported Dataset

- Status: Accepted
- Date: 2026-07-15

## Context

Glint must support continuous shared sources, user-device/cookie-dependent sources and private files without silently moving sensitive data or misrepresenting availability.

## Decision

Define three mutually distinct source kinds. Cloud Sources run server-side and continue while devices are offline. Local Sources run on an identified Mac with credentials in local secure storage and do not upload content by default. Imported Datasets are static user-selected files with terminal immutable manifests; any cloud transfer is an explicit scope/consent action and thereafter is a cloud import, not a Local Source.

The transfer lifecycle uses three separate records. ImportSession is a mutable coordination aggregate, pins the expected Imported Source pointer/version and never contains a Mac filesystem path; Phase 1 permits one non-terminal session per source. TransferConsentRecord is append-only and grants only exact digests, selected scope, destination, object limit and expiry; it does not authorize model egress, and upload completion/finalize resolve the same effective unexpired/unrevoked grant. A dedicated ImportFinalizationJob alone may receive the session ID; after object validation it creates ImportManifest plus visible normalized content and compare-and-sets the source pointer. ImportManifest then never changes. Failed, cancelled or stale sessions create no manifest and clean staging; all downstream workers accept only the terminal manifest ID.

## Consequences

The Sources UI can accurately state runtime, freshness, import progress/recovery and privacy. The architecture supports Cloud GitHub/RSS and imported CSV, but Phase 1 exposes only Seed/Imported CSV. GitHub/RSS begin in Phase 2; Local Source remains a schema/adapter seam and is not callable in the MVP OpenAPI or UI. Local cookie connectors wait for a secure device protocol. Model/tool egress policies inherit the source locality label and remain separate from upload consent.
