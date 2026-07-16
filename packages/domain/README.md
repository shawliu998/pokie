# Glint domain package

This package is the dependency-free Phase 1 domain core shared by the FastAPI
process and background worker. It contains invariants, immutable value objects,
closed enums and deterministic calculations only. Persistence, HTTP schemas,
authorization repositories, object-store access and job execution remain in
their owning service modules.

Implemented boundaries:

- canonical JSON/SHA-256 snapshot digests;
- `ImportSession` transitions, immutable pins, append-only transfer-consent
  resolution and server-observed upload verification;
- Signal Impact/Urgency Priority derivation;
- deterministic, uncalibrated Evidence and Claim score helpers;
- canonical Investigation and ResearchRun transitions and immutable resume pins;
- recursive secret and local-path redaction/rejection;
- one-verified-synthesis grounding, typed Decision Brief block provenance,
  readiness checks, current-freshness checks and PRD export selection rules.

The domain objects are deliberately not ORM entities or wire schemas. Service
adapters translate persisted rows and Pydantic commands into these values, run
the invariant, then persist the returned immutable result in a transaction.
