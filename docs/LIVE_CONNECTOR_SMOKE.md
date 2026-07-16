# Live connector smoke

The GitHub/RSS smoke is a manual, read-only gate. It is excluded from default CI
and exits without network access unless `GLINT_ENABLE_LIVE_SMOKE=1` is set
exactly.

## Run

Use a fine-grained GitHub token with public-repository read access only. Supply
it through the existing secret-reference environment namespace; do not place a
value in `.env.example`, a shell script, a fixture, a snapshot, or a command-line
argument.

```bash
export GLINT_ENABLE_LIVE_SMOKE=1
export GLINT_SECRET_GITHUB_TOKEN="..."
export GLINT_CONNECTOR_CURSOR_SECRET="...at least 32 random bytes..."
scripts/verify_live_connectors.sh
```

If the GitHub token or cursor-signing secret is absent, GitHub is reported as
`SKIP`; credential-free RSS checks still run. Network, upstream permission, and
rate-limit failures are emitted as metadata-only `degraded` summaries rather
than turning ordinary unit tests red. A deterministic invariant failure remains
an error.

The fixed public samples are:

- GitHub: `openai/codex`, `anthropics/claude-code`, and `zed-industries/zed`.
- RSS/Atom: GitHub Blog RSS, Codex releases Atom, and Cloudflare Blog RSS.

The runner performs GitHub health/search, REST rate-limit inspection, signed
pagination, one-item fetch/re-fetch, unavailable-item handling, PR exclusion,
and GraphQL discussion degradation. It performs RSS health/search/fetch,
RSS-versus-Atom recognition, redirect/SSRF/content-type/body-cap enforcement,
stable versioning, and duplicate-URL observation. It never creates, updates, or
deletes public content.

Output deliberately contains only source identity, counts, health/freshness,
check names, and error class. It contains no item title, author, body, raw payload,
request headers, cursor, token, or exception text.

## Authenticity boundary

- Results produced by this network runner are labelled **Live Collected**.
- Existing deterministic connector fixtures are synthetic fixtures; they are
  not live data and must not be relabelled.
- A future public-data capture must be labelled **Captured Fixture**, store its
  capture date, public source URL, response content type, generation script
  version, and trimming/redaction notes, and contain no private content or
  credentials. No captured public payload is committed by this milestone.

Captured fixtures remain in default CI only after a reviewer verifies that their
manifest says `Authenticity = Captured Fixture` and that the payload is cropped,
redacted, and license-safe. The live runner output itself is not a capture format
and must not be redirected into a test fixture.
