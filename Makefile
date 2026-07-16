SHELL := /usr/bin/env bash
PYTHON_BIN ?= .venv/bin/python

.PHONY: verify-phase1 verify-phase2 audit runtime smoke e2e-api tauri-native check

verify-phase1:
	./scripts/verify_phase1.sh

verify-phase2:
	./scripts/verify_phase2.sh

audit:
	./scripts/audit_dependencies.sh

runtime:
	$(PYTHON_BIN) -m pytest tests/runtime

smoke:
	$(PYTHON_BIN) -m pytest tests/smoke

e2e-api:
	@test -n "$(VITE_GLINT_ACCESS_TOKEN)" || (echo 'VITE_GLINT_ACCESS_TOKEN is required; run scripts/verify_phase1.sh seed first' >&2; exit 2)
	GLINT_E2E_API_MODE=external GLINT_E2E_API_URL=$${GLINT_E2E_API_URL:-http://127.0.0.1:8000} GLINT_E2E_ACCESS_TOKEN=$${VITE_GLINT_ACCESS_TOKEN} GLINT_E2E_WORKSPACE_ID=$${VITE_GLINT_WORKSPACE_ID:-11111111-1111-5111-8111-111111111111} VITE_GLINT_DATA_MODE=api VITE_GLINT_API_URL=$${GLINT_E2E_API_URL:-http://127.0.0.1:8000} VITE_GLINT_WORKSPACE_ID=$${VITE_GLINT_WORKSPACE_ID:-11111111-1111-5111-8111-111111111111} VITE_GLINT_ACCESS_TOKEN=$${VITE_GLINT_ACCESS_TOKEN} pnpm test:e2e

tauri-native:
	./scripts/verify_tauri_runtime.sh

check: verify-phase1
