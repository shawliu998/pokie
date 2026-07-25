import json
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path


def _stop_process(process: subprocess.Popen[str]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def test_native_gate_uses_node_ports_and_actual_cargo_target_dir() -> None:
    script = Path("scripts/verify_tauri_runtime.sh").read_text(encoding="utf-8")
    assert "$ROOT_DIR/.venv/bin/python" not in script
    assert "node:net" in script
    assert 'CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$ROOT_DIR/apps/mac/src-tauri/target}"' in script
    assert 'for artifact in apps/mac/dist "$CARGO_TARGET_DIR"' in script
    assert "tauri build --debug --bundles app -- --locked" in script
    assert 'native_app="$CARGO_TARGET_DIR/debug/bundle/macos/Qurio.app"' in script
    assert (
        'native_runtime="$native_app/Contents/Resources/qurio-runtime/qurio-runtime"'
        in script
    )
    assert '"$native_runtime" --help >/dev/null' in script
    assert 'codesign --verify --deep --strict "$native_app"' in script
    assert "bundle_identifier=$(plutil -extract CFBundleIdentifier raw" in script
    assert '[[ "$bundle_identifier" == "com.glint.workbench"' in script
    assert "Native gate found fake React traffic lights" in script
    assert "pnpm --filter @glint/mac test -- --run" in script
    assert "ripgrep is required for the native artifact token scan" in script
    assert "macOS plutil is required for the app bundle gate" in script
    assert "GLINT_FIXTURE_ALLOWED_ORIGIN=http://127.0.0.1:1420" in script
    assert "Native API CORS preflight failed before WebView startup" in script
    assert "Access-Control-Request-Headers: Authorization,X-Workspace-ID" in script
    assert 'sub(/^[^:]*:[[:space:]]*/, "", $0)' in script
    assert "security -i" in script
    assert "-T /usr/bin/security -X %s" in script
    assert "rg -a -F -f -" in script
    assert 'rg -a -F -f - -- "$artifact" >/dev/null 2>&1' not in script
    assert 'rg -a -F -- "$token"' not in script
    assert 'FIXTURE_TOKEN="$fixture_token"' not in script
    assert 'AUTH_SECRET="$auth_secret"' not in script
    assert 'GLINT_FIXTURE_ACCESS_TOKEN="$fixture_token"' not in script
    assert '-H "Authorization: Bearer $fixture_token"' not in script
    assert "GLINT_FIXTURE_ACCESS_TOKEN_STDIN=1" in script
    assert "curl --config -" in script
    assert '-w "$fixture_token"' not in script
    assert '-X "$fixture_token_hex"' not in script
    assert 'security list-keychains -d user -s "$temporary_keychain"' in script
    assert "keychain_state_matches_original" in script
    assert "preserve_temporary_keychain=1" in script
    assert script.index("trap cleanup EXIT") < script.index(
        'mktemp -d "${TMPDIR:-/tmp}/glint-native-keychain'
    )
    assert script.index("trap cleanup EXIT") < script.index('rm -f "$cache_path" "$ready_marker"')
    assert "kill $listeners" not in script
    assert "lsof -tiTCP:1420" not in script
    assert "expected_native_cdhash=$(binary_cdhash)" in script
    assert " -A" not in script
    assert " -U" not in script
    assert script.index('"$cargo_bin" test --locked') < script.index("tauri build")


def test_native_shell_has_real_bundle_window_state_and_native_menu() -> None:
    config = json.loads(Path("apps/mac/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert config["productName"] == "Qurio"
    assert config["identifier"] == "com.glint.workbench"
    assert not config["identifier"].endswith(".app")
    assert config["bundle"]["active"] is True
    assert config["bundle"]["targets"] == ["app"]
    assert config["bundle"]["resources"] == {
        "resources/qurio-runtime/": "qurio-runtime/"
    }
    assert config["bundle"]["macOS"]["signingIdentity"] == "-"
    assert config["bundle"]["macOS"]["minimumSystemVersion"] == "11.0"
    assert "icons/icon.icns" in config["bundle"]["icon"]
    assert config["app"]["windows"][0]["decorations"] is True
    assert "http://localhost:*" in config["app"]["security"]["csp"]
    assert "http://127.0.0.1:*" in config["app"]["security"]["csp"]

    cargo_manifest = Path("apps/mac/src-tauri/Cargo.toml").read_text(encoding="utf-8")
    native_source = Path("apps/mac/src-tauri/src/main.rs").read_text(encoding="utf-8")
    workbench_source = Path("apps/mac/src/features/workbench/Workbench.tsx").read_text(
        encoding="utf-8"
    )
    assert 'tauri-plugin-window-state = "=2.4.1"' in cargo_manifest
    assert "StateFlags::SIZE | StateFlags::MAXIMIZED" in native_source
    assert ".menu(native_menu)" in native_source
    for real_native_item in (".about(", ".quit()", ".undo()", ".copy()", ".minimize()"):
        assert real_native_item in native_source
    assert 'className="traffic"' not in workbench_source
    assert "● ● ●" not in workbench_source

    workflow = Path(".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert "ditto -c -k --sequesterRsrc --keepParent" in workflow
    assert "apps/mac/src-tauri/target/debug/bundle/macos/Qurio.app" in workflow
    assert "${{ runner.temp }}/Qurio.app.zip" in workflow


def test_tauri_dev_command_forwards_the_configured_dev_url_host_and_port() -> None:
    config = json.loads(Path("apps/mac/src-tauri/tauri.conf.json").read_text(encoding="utf-8"))
    assert config["build"]["beforeDevCommand"] == "pnpm dev --host 127.0.0.1 --port 1420"
    assert config["build"]["devUrl"] == "http://127.0.0.1:1420"
    compose = Path("infra/docker-compose.yml").read_text(encoding="utf-8")
    assert 'GLINT_ALLOWED_ORIGINS: \'["http://127.0.0.1:1420","http://localhost:3000"]\'' in compose


def test_native_fixture_preflight_uses_the_exact_configured_origin() -> None:
    origin = "http://127.0.0.1:1420"
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    environment = {
        **os.environ,
        "GLINT_FIXTURE_PORT": str(port),
        "GLINT_FIXTURE_ALLOWED_ORIGIN": origin,
    }
    process = subprocess.Popen(
        ["node", "apps/mac/e2e/api-fixture.mjs"],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.2):
                    break
            except OSError:
                time.sleep(0.05)
        else:
            error = "fixture did not start"
            if process.poll() is not None and process.stderr:
                error = process.stderr.read()
            raise AssertionError(error)

        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/sync/bootstrap",
            method="OPTIONS",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "Authorization,X-Workspace-ID",
            },
        )
        with urllib.request.urlopen(request, timeout=1) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == origin
            assert response.headers["Access-Control-Allow-Origin"] != "*"
    finally:
        _stop_process(process)


def test_native_fixture_accepts_its_secret_only_over_stdin() -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    token = "stdin-only-native-fixture-token"
    environment = {
        **os.environ,
        "GLINT_FIXTURE_PORT": str(port),
        "GLINT_FIXTURE_ACCESS_TOKEN_STDIN": "1",
    }
    assert token not in environment.values()
    process = subprocess.Popen(
        ["node", "apps/mac/e2e/api-fixture.mjs"],
        env=environment,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    process.stdin.write(token)
    process.stdin.close()
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/v1/sync/bootstrap",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "X-Workspace-ID": "00000000-0000-4000-8000-000000000001",
                    },
                )
                with urllib.request.urlopen(request, timeout=0.2) as response:
                    assert response.status == 200
                    break
            except OSError:
                time.sleep(0.05)
        else:
            error = "stdin fixture did not start"
            if process.poll() is not None and process.stderr:
                error = process.stderr.read()
            raise AssertionError(error)
    finally:
        _stop_process(process)


def test_acceptance_shell_scripts_parse_individually() -> None:
    for path in sorted(Path("scripts").glob("*.sh")):
        result = subprocess.run(["bash", "-n", str(path)], check=False)
        assert result.returncode == 0, path
