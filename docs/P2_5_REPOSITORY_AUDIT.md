# P2.5 Repository and CI Trust Audit

Audit date: 2026-07-16 (Asia/Shanghai)

## Repository state

| Check | Result |
| --- | --- |
| Local branch at audit start | `main` |
| Working branch | `feat/p2-5-pilot-workbench` |
| Local HEAD at audit start | `161c6075a9e73dbb344f15d58ef41b7c9834380e` |
| Remote `HEAD` | `161c6075a9e73dbb344f15d58ef41b7c9834380e` |
| Remote `refs/heads/main` | `161c6075a9e73dbb344f15d58ef41b7c9834380e` |
| Default branch | `main` |
| Visibility | Public |
| Anonymous repository contents | HTTP 200; repository files were listed without GitHub credentials |
| Workflow | `Glint verification` (`.github/workflows/verify.yml`), active |
| Branch protection at audit start | Not configured (`404 Branch not protected`; no repository rulesets) |

The public repository is not empty. Anonymous `git ls-remote` and the anonymous
GitHub Contents API both returned the `main` branch and repository files. No
force push or history rewrite was needed.

## Commands executed

```text
git status
git log --oneline --decorate -10
git branch -vv
git remote -v
git ls-remote origin
gh repo view shawliu998/Glint
gh workflow list --repo shawliu998/Glint
gh run list --repo shawliu998/Glint --limit 10
gh run view 29465005327 --repo shawliu998/Glint --json url,headSha,event,status,conclusion,workflowName,jobs
gh run view 29465005327 --repo shawliu998/Glint --log-failed
gh api repos/shawliu998/Glint/branches/main/protection
gh api repos/shawliu998/Glint/rulesets
```

Anonymous visibility was also checked with GitHub credentials removed and the
Git credential helper disabled. No token or secret was printed during the
audit.

## Existing GitHub Actions result

The latest commit did trigger GitHub Actions. It did not pass.

- Run: [Glint verification 29465005327](https://github.com/shawliu998/Glint/actions/runs/29465005327)
- Event: `push`
- Branch: `main`
- Commit: `161c6075a9e73dbb344f15d58ef41b7c9834380e`
- Overall result: `failure`
- `security-audit`: success
- `phase1`: failure
- `macos-native`: failure
- `phase2`: skipped because it depends on `phase1`

## Problems found

1. The workflow relied on repository-default token permissions instead of
   declaring its own minimum permission.
2. Repeated runs on the same ref had no concurrency cancellation.
3. pnpm caching existed, but uv caching was implicit and Cargo had no explicit
   cache.
4. Job-level authentication and Vite environment values leaked into unit and
   fixture tests. This changed the expected issuer and fixture workspace.
5. Linux runners did not install the system WebKit/GTK libraries required by
   the existing Tauri Cargo check.
6. The API E2E test attempted to schedule a newly created cloud source without
   explicitly selecting a Watchlist, even though the product intentionally does
   not silently mix imported and cloud scopes.
7. The macOS native token scan suppressed ripgrep diagnostics and the workflow
   did not guarantee that ripgrep was installed.
8. `main` had no branch protection or ruleset.
9. `phase2` depends on `phase1` and its verification script currently reruns the
   Phase 1 gate. This duplication is recorded for later CI refactoring; the gate
   is not removed during the trust-baseline fix.

## Fixes prepared on the working branch

- Declared `permissions: contents: read`.
- Added per-workflow/ref concurrency with cancellation of superseded runs.
- Made uv and Cargo caches explicit while excluding tokens, environment files,
  databases, Keychain contents, and user data.
- Removed job-global Glint authentication and Vite values; acceptance scripts
  create their own scoped deterministic values.
- Made the production authentication test independent of ambient issuer values.
- Added the required Linux Tauri system packages.
- Made fixture E2E configuration ignore unrelated ambient Vite values.
- Made Watchlist selection explicit before schedule creation.
- Added a ripgrep preflight, preserved safe scanner diagnostics, and installed
  ripgrep in the macOS job.

## Remote verification

The baseline run above is the last result for `main`. The working-branch run URL,
commit SHA, job results, and any follow-up fixes will be appended after the
branch is pushed and the real GitHub Actions run reaches a terminal state.

Branch protection will be configured only after the required checks have a real
successful run. Until then, lack of a green required-check baseline is an
external sequencing blocker, not a reason to report the repository as trusted.

## Next files after Milestone A

Frontend refactoring will start only after the remote CI baseline is verified.
The first implementation set is expected to touch:

```text
apps/mac/src/main.tsx
apps/mac/src/app/App.tsx
apps/mac/src/app/AppShell.tsx
apps/mac/src/app/destinations.ts
apps/mac/src/features/session/
apps/mac/src/features/workspace/
apps/mac/src/features/inbox/
apps/mac/src/features/investigations/
apps/mac/src/features/decisions/
apps/mac/src/features/monitoring/
apps/mac/src/features/evidence/
apps/mac/src/components/
apps/mac/src/hooks/
apps/mac/src/lib/
```

The refactor will preserve REST/SSE contracts, domain state machines, current
accessible names, and the existing visible behavior until the later native
shell and interaction milestones intentionally change them.
