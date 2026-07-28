use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{Duration, Instant},
};

use crate::session;

const DEEPSEEK_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.deepseek";
const KIMI_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.kimi";
const OPENAI_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.openai";
const QWEN_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.qwen";
const OPENAI_COMPATIBLE_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.openai-compatible";
const RUNTIME_KEYCHAIN_ACCOUNT: &str = "api-key";
const READY_PREFIX: &str = "QURIO_RUNTIME_READY ";
const PROVIDER_TEST_PREFIX: &str = "QURIO_PROVIDER_TEST ";
const MAX_SECRET_BYTES: usize = 16 * 1024;
const PROVIDER_PRESETS_JSON: &str = include_str!("../../provider-presets.json");

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Provider {
    Mock,
    Deepseek,
    #[serde(rename = "openai_compatible")]
    OpenaiCompatible,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct StartLocalRuntimeRequest {
    pub preset: Option<String>,
    pub provider: Provider,
    pub model: Option<String>,
    pub base_url: Option<String>,
    pub api_key: Option<String>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct ProviderPreset {
    id: String,
    transport: Provider,
    base_url: Option<String>,
    model: Option<String>,
    request_profile: String,
}

#[derive(Clone, Debug)]
struct ResolvedProvider {
    preset: String,
    provider: Provider,
    model: Option<String>,
    base_url: Option<String>,
    request_profile: String,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalRuntimeStatus {
    pub state: String,
    pub api_url: Option<String>,
    pub workspace_id: Option<String>,
    pub provider: Option<Provider>,
    pub preset: Option<String>,
    pub model: Option<String>,
    pub base_url: Option<String>,
    pub message: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalRuntimeConnectionTest {
    pub provider: String,
    pub model: Option<String>,
    pub latency_ms: u64,
    pub status: String,
    pub message: String,
}

impl LocalRuntimeStatus {
    fn stopped() -> Self {
        Self {
            state: "stopped".to_string(),
            api_url: None,
            workspace_id: None,
            provider: None,
            preset: None,
            model: None,
            base_url: None,
            message: None,
        }
    }

    fn failed(message: impl Into<String>) -> Self {
        Self {
            state: "failed".to_string(),
            api_url: None,
            workspace_id: None,
            provider: None,
            preset: None,
            model: None,
            base_url: None,
            message: Some(message.into()),
        }
    }
}

#[derive(Debug, Deserialize)]
struct ReadyPayload {
    api_url: String,
    workspace_id: String,
    principal_id: String,
    provider: Provider,
    #[serde(default)]
    preset: Option<String>,
    model: Option<String>,
    base_url: Option<String>,
}

pub(crate) struct LocalRuntimeManager {
    child: Mutex<Option<Child>>,
    status: Mutex<LocalRuntimeStatus>,
    lifecycle_lock: Mutex<()>,
    bundled_executable: Option<PathBuf>,
    runtime_dir: Option<PathBuf>,
}

impl Default for LocalRuntimeManager {
    fn default() -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(LocalRuntimeStatus::stopped()),
            lifecycle_lock: Mutex::new(()),
            bundled_executable: None,
            runtime_dir: None,
        }
    }
}

fn source_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../..")
        .canonicalize()
        .unwrap_or_else(|_| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../.."))
}

fn source_checkout_error() -> String {
    "Qurio could not find its bundled local runtime or a valid source checkout. Reinstall Qurio, or connect it to an already-running API.".to_string()
}

fn provider_presets() -> Result<Vec<ProviderPreset>, String> {
    serde_json::from_str(PROVIDER_PRESETS_JSON)
        .map_err(|_| "Qurio's model provider registry is invalid.".to_string())
}

fn resolve_request(request: &StartLocalRuntimeRequest) -> Result<ResolvedProvider, String> {
    let explicit_preset = request.preset.is_some();
    let preset_id = request.preset.as_deref().unwrap_or(match request.provider {
        Provider::Mock => "mock",
        Provider::Deepseek => "deepseek",
        Provider::OpenaiCompatible => "custom_openai_compatible",
    });
    let preset = provider_presets()?
        .into_iter()
        .find(|candidate| candidate.id == preset_id)
        .ok_or_else(|| "The selected model provider preset is invalid.".to_string())?;
    if preset.transport != request.provider {
        return Err("The selected model provider does not match its transport.".to_string());
    }
    let custom = preset.id == "custom_openai_compatible";
    let resolved_model = if custom || !explicit_preset {
        request.model.clone()
    } else {
        if request.model != preset.model {
            return Err("The selected model provider does not match its fixed model.".to_string());
        }
        preset.model.clone()
    };
    let resolved_base_url = if custom {
        request.base_url.clone()
    } else if preset.transport == Provider::OpenaiCompatible {
        if request.base_url != preset.base_url {
            return Err(
                "The selected model provider does not match its fixed endpoint.".to_string(),
            );
        }
        preset.base_url.clone()
    } else {
        if request.base_url.is_some() {
            return Err("The selected model provider uses Qurio's fixed endpoint.".to_string());
        }
        None
    };
    Ok(ResolvedProvider {
        preset: preset.id,
        provider: preset.transport,
        model: resolved_model,
        base_url: resolved_base_url,
        request_profile: preset.request_profile,
    })
}

fn validate_request(request: &StartLocalRuntimeRequest) -> Result<ResolvedProvider, String> {
    let resolved = resolve_request(request)?;
    match request.provider {
        Provider::Mock => {
            if request.model.is_some() || request.base_url.is_some() || request.api_key.is_some() {
                return Err(
                    "Offline deterministic runtime does not accept provider configuration."
                        .to_string(),
                );
            }
        }
        Provider::Deepseek => {
            validate_model(request.model.as_deref())?;
            if request.base_url.is_some() {
                return Err("DeepSeek uses Qurio's fixed provider endpoint.".to_string());
            }
        }
        Provider::OpenaiCompatible => {
            validate_model(request.model.as_deref())?;
            validate_base_url(request.base_url.as_deref())?;
        }
    }
    if let Some(key) = &request.api_key {
        if key.trim().is_empty()
            || key.len() > MAX_SECRET_BYTES
            || key.chars().any(char::is_control)
        {
            return Err("The local-runtime API key has an invalid format.".to_string());
        }
    }
    Ok(resolved)
}

fn validate_model(model: Option<&str>) -> Result<(), String> {
    let model = model.unwrap_or_default();
    if model.trim().is_empty() || model.len() > 128 || model.chars().any(char::is_control) {
        return Err("Enter a valid provider model name.".to_string());
    }
    Ok(())
}

fn validate_base_url(base_url: Option<&str>) -> Result<(), String> {
    let value = base_url.unwrap_or_default();
    if value.trim() != value || value.len() > 2_048 || value.chars().any(char::is_control) {
        return Err("Enter a valid HTTPS provider URL.".to_string());
    }
    let parsed =
        url::Url::parse(value).map_err(|_| "Enter a valid HTTPS provider URL.".to_string())?;
    if parsed.scheme() != "https"
        || parsed.host_str().is_none()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
        || parsed.query().is_some()
        || parsed.fragment().is_some()
    {
        return Err("Enter a valid HTTPS provider URL.".to_string());
    }
    Ok(())
}

fn parse_ready_line(line: &str) -> Result<Option<ReadyPayload>, String> {
    let Some(payload) = line.strip_prefix(READY_PREFIX) else {
        return Ok(None);
    };
    let ready: ReadyPayload = serde_json::from_str(payload)
        .map_err(|_| "Qurio local runtime returned an invalid ready message.".to_string())?;
    let valid_model = match ready.provider {
        Provider::Mock => ready.model.is_none(),
        Provider::Deepseek | Provider::OpenaiCompatible => ready
            .model
            .as_deref()
            .is_some_and(|model| !model.trim().is_empty()),
    };
    let valid_base_url = match ready.provider {
        Provider::Mock | Provider::Deepseek => ready.base_url.is_none(),
        Provider::OpenaiCompatible => validate_base_url(ready.base_url.as_deref()).is_ok(),
    };
    if ready.api_url.trim().is_empty()
        || ready.workspace_id.trim().is_empty()
        || ready.principal_id.trim().is_empty()
        || !valid_model
        || !valid_base_url
    {
        return Err("Qurio local runtime returned an incomplete ready message.".to_string());
    }
    Ok(Some(ready))
}

#[cfg(target_os = "macos")]
fn keychain_service(preset: &str) -> Result<&'static str, String> {
    match preset {
        "deepseek" => Ok(DEEPSEEK_KEYCHAIN_SERVICE),
        "kimi_k3" => Ok(KIMI_KEYCHAIN_SERVICE),
        "openai" => Ok(OPENAI_KEYCHAIN_SERVICE),
        "qwen" => Ok(QWEN_KEYCHAIN_SERVICE),
        "custom_openai_compatible" => Ok(OPENAI_COMPATIBLE_KEYCHAIN_SERVICE),
        "mock" => Err("Offline deterministic runtime does not use an API key.".to_string()),
        _ => Err("The selected model provider preset is invalid.".to_string()),
    }
}

#[cfg(target_os = "macos")]
fn saved_provider_key(preset: &str) -> Result<Option<String>, String> {
    use security_framework::passwords::get_generic_password;
    const NOT_FOUND: i32 = -25300;
    match get_generic_password(keychain_service(preset)?, RUNTIME_KEYCHAIN_ACCOUNT) {
        Ok(bytes) => String::from_utf8(bytes)
            .map(Some)
            .map_err(|_| "macOS Keychain returned an invalid Qurio runtime key.".to_string()),
        Err(error) if error.code() == NOT_FOUND => Ok(None),
        Err(_) => Err("macOS Keychain could not read the Qurio runtime key.".to_string()),
    }
}

#[cfg(target_os = "macos")]
fn save_provider_key(preset: &str, key: &str) -> Result<(), String> {
    security_framework::passwords::set_generic_password(
        keychain_service(preset)?,
        RUNTIME_KEYCHAIN_ACCOUNT,
        key.trim().as_bytes(),
    )
    .map_err(|_| "macOS Keychain could not store the Qurio runtime key.".to_string())
}

#[cfg(not(target_os = "macos"))]
fn saved_provider_key(_preset: &str) -> Result<Option<String>, String> {
    Err("Qurio local runtime requires macOS Keychain.".to_string())
}
#[cfg(not(target_os = "macos"))]
fn save_provider_key(_preset: &str, _key: &str) -> Result<(), String> {
    Err("Qurio local runtime requires macOS Keychain.".to_string())
}

fn wait_for_ready(child: &mut Child) -> Result<ReadyPayload, String> {
    let stdout = child
        .stdout
        .take()
        .ok_or_else(|| "Qurio local runtime could not expose startup status.".to_string())?;
    let (sender, receiver) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        for line in BufReader::new(stdout).lines() {
            if sender.send(line).is_err() {
                break;
            }
        }
    });
    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        if let Some(exit) = child
            .try_wait()
            .map_err(|_| "Qurio local runtime could not check startup status.".to_string())?
        {
            return Err(format!(
                "Qurio local runtime stopped during startup (exit code {}).",
                exit
            ));
        }
        if let Ok(Ok(line)) = receiver.recv_timeout(Duration::from_millis(200)) {
            if let Some(ready) = parse_ready_line(&line)? {
                return Ok(ready);
            }
        }
    }
    Err("Qurio local runtime did not become ready within 30 seconds.".to_string())
}

fn terminate(child: &mut Child) {
    #[cfg(unix)]
    unsafe {
        unsafe extern "C" {
            fn kill(pid: i32, sig: i32) -> i32;
        }
        let _ = kill(child.id() as i32, 15);
    }
    for _ in 0..20 {
        if child.try_wait().ok().flatten().is_some() {
            return;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    let _ = child.kill();
    let _ = child.wait();
}

impl LocalRuntimeManager {
    pub(crate) fn new(resource_dir: Option<PathBuf>, app_data_dir: PathBuf) -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(LocalRuntimeStatus::stopped()),
            lifecycle_lock: Mutex::new(()),
            bundled_executable: resource_dir
                .map(|directory| directory.join("qurio-runtime").join("qurio-runtime")),
            runtime_dir: Some(app_data_dir.join("local-runtime")),
        }
    }

    fn reconcile(&self) {
        let mut child = self.child.lock().expect("runtime child lock");
        if let Some(process) = child.as_mut() {
            if let Ok(Some(exit)) = process.try_wait() {
                *child = None;
                let mut status = self.status.lock().expect("runtime status lock");
                if status.state == "running" {
                    *status = LocalRuntimeStatus::failed(format!(
                        "Qurio local runtime stopped unexpectedly (exit code {}).",
                        exit
                    ));
                }
            }
        }
    }

    fn start(&self, request: StartLocalRuntimeRequest) -> Result<LocalRuntimeStatus, String> {
        let _lifecycle = self.lifecycle_lock.lock().expect("runtime lifecycle lock");
        let resolved = validate_request(&request)?;
        self.reconcile();
        if self.child.lock().expect("runtime child lock").is_some() {
            return self.status();
        }
        let root = source_root();
        let python = root.join(".venv/bin/python");
        let script = root.join("scripts/run_qurio_local_runtime.py");
        let bundled = self
            .bundled_executable
            .as_ref()
            .filter(|executable| executable.is_file());
        if bundled.is_none() && (!python.is_file() || !script.is_file()) {
            let message = source_checkout_error();
            *self.status.lock().expect("runtime status lock") =
                LocalRuntimeStatus::failed(message.clone());
            return Err(message);
        }
        let mut command = match bundled {
            Some(executable) => {
                let mut command = Command::new(executable);
                if let Some(parent) = executable.parent() {
                    command.current_dir(parent);
                }
                command
            }
            None => {
                let mut command = Command::new(&python);
                command.arg(&script).current_dir(&root);
                command
            }
        };
        command
            .arg("--provider")
            .arg(match resolved.provider {
                Provider::Mock => "mock",
                Provider::Deepseek => "deepseek",
                Provider::OpenaiCompatible => "openai_compatible",
            })
            .arg("--provider-id")
            .arg(&resolved.preset)
            .arg("--request-profile")
            .arg(&resolved.request_profile)
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(runtime_dir) = &self.runtime_dir {
            command.arg("--runtime-dir").arg(runtime_dir);
        }
        if resolved.provider != Provider::Mock {
            command
                .arg("--model")
                .arg(resolved.model.as_deref().expect("validated model").trim());
            if resolved.provider == Provider::OpenaiCompatible {
                command.arg("--base-url").arg(
                    resolved
                        .base_url
                        .as_deref()
                        .expect("validated base URL")
                        .trim(),
                );
            }
            let key = match request.api_key.as_deref() {
                Some(key) => {
                    save_provider_key(&resolved.preset, key)?;
                    key.trim().to_string()
                }
                None => saved_provider_key(&resolved.preset)?
                    .ok_or_else(|| "Enter an API key once to start this provider.".to_string())?,
            };
            command.env("POKIEQUANT_AGENT_API_KEY", key);
        }
        let mut child = command.spawn().map_err(|_| source_checkout_error())?;
        let ready = match wait_for_ready(&mut child) {
            Ok(ready) => ready,
            Err(message) => {
                terminate(&mut child);
                *self.status.lock().expect("runtime status lock") =
                    LocalRuntimeStatus::failed(message.clone());
                return Err(message);
            }
        };
        if ready.provider != resolved.provider
            || ready.preset.as_deref() != Some(resolved.preset.as_str())
            || ready.model.as_deref() != resolved.model.as_deref().map(str::trim)
            || ready.base_url.as_deref() != resolved.base_url.as_deref().map(str::trim)
        {
            terminate(&mut child);
            let message =
                "Qurio local runtime returned an unexpected provider or model.".to_string();
            *self.status.lock().expect("runtime status lock") =
                LocalRuntimeStatus::failed(message.clone());
            return Err(message);
        }
        if session::store_access_token(ready.principal_id).is_err() {
            terminate(&mut child);
            let message = "Qurio local runtime started, but its session could not be stored in macOS Keychain.".to_string();
            *self.status.lock().expect("runtime status lock") =
                LocalRuntimeStatus::failed(message.clone());
            return Err(message);
        }
        let status = LocalRuntimeStatus {
            state: "running".to_string(),
            api_url: Some(ready.api_url),
            workspace_id: Some(ready.workspace_id),
            provider: Some(ready.provider),
            preset: ready.preset,
            model: ready.model,
            base_url: ready.base_url,
            message: None,
        };
        *self.child.lock().expect("runtime child lock") = Some(child);
        *self.status.lock().expect("runtime status lock") = status.clone();
        Ok(status)
    }

    fn test_provider(
        &self,
        request: StartLocalRuntimeRequest,
    ) -> Result<LocalRuntimeConnectionTest, String> {
        let resolved = validate_request(&request)?;
        if resolved.provider == Provider::Mock {
            return Ok(LocalRuntimeConnectionTest {
                provider: resolved.preset,
                model: None,
                latency_ms: 0,
                status: "verified".to_string(),
                message: "Offline deterministic mode is ready.".to_string(),
            });
        }
        let root = source_root();
        let python = root.join(".venv/bin/python");
        let script = root.join("scripts/run_qurio_local_runtime.py");
        let bundled = self
            .bundled_executable
            .as_ref()
            .filter(|executable| executable.is_file());
        if bundled.is_none() && (!python.is_file() || !script.is_file()) {
            return Err(source_checkout_error());
        }
        let mut command = match bundled {
            Some(executable) => {
                let mut command = Command::new(executable);
                if let Some(parent) = executable.parent() {
                    command.current_dir(parent);
                }
                command
            }
            None => {
                let mut command = Command::new(&python);
                command.arg(&script).current_dir(&root);
                command
            }
        };
        command
            .arg("--test-provider")
            .arg("--provider")
            .arg(match resolved.provider {
                Provider::Mock => "mock",
                Provider::Deepseek => "deepseek",
                Provider::OpenaiCompatible => "openai_compatible",
            })
            .arg("--provider-id")
            .arg(&resolved.preset)
            .arg("--request-profile")
            .arg(&resolved.request_profile)
            .arg("--model")
            .arg(resolved.model.as_deref().expect("validated model").trim())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(base_url) = &resolved.base_url {
            command.arg("--base-url").arg(base_url);
        }
        let key = match request.api_key.as_deref() {
            Some(key) => key.trim().to_string(),
            None => saved_provider_key(&resolved.preset)?
                .ok_or_else(|| "Enter an API key to test this provider.".to_string())?,
        };
        command.env("POKIEQUANT_AGENT_API_KEY", key);
        let started = Instant::now();
        let output = command
            .output()
            .map_err(|_| "Qurio could not run the provider connection test.".to_string())?;
        let latency_ms = u64::try_from(started.elapsed().as_millis()).unwrap_or(u64::MAX);
        let verified = output.status.success()
            && String::from_utf8_lossy(&output.stdout)
                .lines()
                .any(|line| line.starts_with(PROVIDER_TEST_PREFIX));
        Ok(LocalRuntimeConnectionTest {
            provider: resolved.preset,
            model: resolved.model,
            latency_ms,
            status: if verified { "verified" } else { "failed" }.to_string(),
            message: if verified {
                "Provider accepted Qurio's bounded JSON request.".to_string()
            } else {
                "Provider verification failed. Check the API key, endpoint, model, and account access."
                    .to_string()
            },
        })
    }

    fn stop(&self) -> LocalRuntimeStatus {
        let _lifecycle = self.lifecycle_lock.lock().expect("runtime lifecycle lock");
        if let Some(mut child) = self.child.lock().expect("runtime child lock").take() {
            terminate(&mut child);
        }
        let status = LocalRuntimeStatus::stopped();
        *self.status.lock().expect("runtime status lock") = status.clone();
        status
    }

    fn status(&self) -> Result<LocalRuntimeStatus, String> {
        self.reconcile();
        Ok(self.status.lock().expect("runtime status lock").clone())
    }
}

impl Drop for LocalRuntimeManager {
    fn drop(&mut self) {
        if let Ok(child) = self.child.get_mut() {
            if let Some(mut child) = child.take() {
                terminate(&mut child);
            }
        }
    }
}

#[tauri::command]
pub(crate) fn start_local_runtime(
    manager: tauri::State<'_, LocalRuntimeManager>,
    request: StartLocalRuntimeRequest,
) -> Result<LocalRuntimeStatus, String> {
    manager.start(request)
}
#[tauri::command]
pub(crate) fn stop_local_runtime(
    manager: tauri::State<'_, LocalRuntimeManager>,
) -> LocalRuntimeStatus {
    manager.stop()
}
#[tauri::command]
pub(crate) fn get_local_runtime_status(
    manager: tauri::State<'_, LocalRuntimeManager>,
) -> Result<LocalRuntimeStatus, String> {
    manager.status()
}

#[tauri::command]
pub(crate) fn test_local_runtime_provider(
    manager: tauri::State<'_, LocalRuntimeManager>,
    request: StartLocalRuntimeRequest,
) -> Result<LocalRuntimeConnectionTest, String> {
    manager.test_provider(request)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_invalid_start_input_without_starting_a_process() {
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: None,
            provider: Provider::Mock,
            model: Some("mock-v1".into()),
            base_url: None,
            api_key: None
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: None,
            provider: Provider::Deepseek,
            model: Some("model".into()),
            base_url: None,
            api_key: Some("bad\nkey".into())
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: None,
            provider: Provider::Deepseek,
            model: None,
            base_url: None,
            api_key: None
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: None,
            provider: Provider::OpenaiCompatible,
            model: Some("provider-model".into()),
            base_url: Some("http://provider.example/v1".into()),
            api_key: Some("key".into())
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: None,
            provider: Provider::OpenaiCompatible,
            model: Some("provider-model".into()),
            base_url: Some("https://provider.example/v1".into()),
            api_key: Some("key".into())
        })
        .is_ok());
    }
    #[test]
    fn parses_only_complete_ready_messages() {
        let line = "QURIO_RUNTIME_READY {\"api_url\":\"http://127.0.0.1:8123\",\"workspace_id\":\"workspace-1\",\"principal_id\":\"principal-1\",\"provider\":\"mock\",\"model\":null,\"base_url\":null}";
        let ready = parse_ready_line(line).unwrap().unwrap();
        assert_eq!(ready.workspace_id, "workspace-1");
        let compatible = "QURIO_RUNTIME_READY {\"api_url\":\"http://127.0.0.1:8123\",\"workspace_id\":\"workspace-1\",\"principal_id\":\"principal-1\",\"provider\":\"openai_compatible\",\"model\":\"provider-model\",\"base_url\":\"https://provider.example/v1\"}";
        assert_eq!(
            parse_ready_line(compatible).unwrap().unwrap().provider,
            Provider::OpenaiCompatible
        );
        assert!(parse_ready_line("unrelated log").unwrap().is_none());
        assert!(parse_ready_line("QURIO_RUNTIME_READY {}").is_err());
    }

    #[test]
    fn closed_registry_resolves_fixed_presets_and_rejects_transport_drift() {
        let kimi = validate_request(&StartLocalRuntimeRequest {
            preset: Some("kimi_k3".into()),
            provider: Provider::OpenaiCompatible,
            model: Some("kimi-k3".into()),
            base_url: Some("https://api.moonshot.cn/v1".into()),
            api_key: Some("key".into()),
        })
        .unwrap();
        assert_eq!(kimi.preset, "kimi_k3");
        assert_eq!(kimi.request_profile, "kimi_k3");
        assert!(validate_request(&StartLocalRuntimeRequest {
            preset: Some("openai".into()),
            provider: Provider::Deepseek,
            model: Some("gpt-4.1-mini".into()),
            base_url: None,
            api_key: Some("key".into()),
        })
        .is_err());
    }

    #[cfg(target_os = "macos")]
    #[test]
    fn every_keyed_preset_has_a_separate_keychain_service() {
        let services = [
            keychain_service("deepseek").unwrap(),
            keychain_service("kimi_k3").unwrap(),
            keychain_service("openai").unwrap(),
            keychain_service("qwen").unwrap(),
            keychain_service("custom_openai_compatible").unwrap(),
        ];
        let unique = services
            .into_iter()
            .collect::<std::collections::HashSet<_>>();
        assert_eq!(unique.len(), 5);
    }

    #[test]
    fn resolves_packaged_runtime_and_application_support_paths() {
        let manager = LocalRuntimeManager::new(
            Some(PathBuf::from("/Applications/Qurio.app/Contents/Resources")),
            PathBuf::from("/Users/test/Library/Application Support/com.glint.workbench"),
        );
        assert_eq!(
            manager.bundled_executable,
            Some(PathBuf::from(
                "/Applications/Qurio.app/Contents/Resources/qurio-runtime/qurio-runtime"
            ))
        );
        assert_eq!(
            manager.runtime_dir,
            Some(PathBuf::from(
                "/Users/test/Library/Application Support/com.glint.workbench/local-runtime"
            ))
        );
    }

    #[test]
    fn missing_resource_path_keeps_the_workspace_available_for_source_fallback() {
        let manager = LocalRuntimeManager::new(
            None,
            PathBuf::from("/Users/test/Library/Application Support/com.glint.workbench"),
        );
        assert_eq!(manager.bundled_executable, None);
        assert_eq!(
            manager.runtime_dir,
            Some(PathBuf::from(
                "/Users/test/Library/Application Support/com.glint.workbench/local-runtime"
            ))
        );
    }
}
