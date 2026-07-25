use serde::{Deserialize, Serialize};
use std::{
    io::{BufRead, BufReader},
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};

use crate::session;

const RUNTIME_KEYCHAIN_SERVICE: &str = "com.qurio.runtime.deepseek";
const RUNTIME_KEYCHAIN_ACCOUNT: &str = "api-key";
const READY_PREFIX: &str = "QURIO_RUNTIME_READY ";
const MAX_SECRET_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub(crate) enum Provider {
    Mock,
    Deepseek,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub(crate) struct StartLocalRuntimeRequest {
    pub provider: Provider,
    pub model: Option<String>,
    pub api_key: Option<String>,
}

#[derive(Clone, Debug, Serialize, PartialEq, Eq)]
#[serde(rename_all = "camelCase")]
pub(crate) struct LocalRuntimeStatus {
    pub state: String,
    pub api_url: Option<String>,
    pub workspace_id: Option<String>,
    pub provider: Option<Provider>,
    pub model: Option<String>,
    pub message: Option<String>,
}

impl LocalRuntimeStatus {
    fn stopped() -> Self {
        Self {
            state: "stopped".to_string(),
            api_url: None,
            workspace_id: None,
            provider: None,
            model: None,
            message: None,
        }
    }

    fn failed(message: impl Into<String>) -> Self {
        Self {
            state: "failed".to_string(),
            api_url: None,
            workspace_id: None,
            provider: None,
            model: None,
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
    model: Option<String>,
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

fn validate_request(request: &StartLocalRuntimeRequest) -> Result<(), String> {
    if request.provider == Provider::Deepseek {
        let model = request.model.as_deref().unwrap_or_default();
        if model.trim().is_empty() || model.len() > 200 || model.chars().any(char::is_control) {
            return Err("Enter a valid local-runtime model name.".to_string());
        }
    } else if request.model.is_some() {
        return Err("Mock local runtime does not accept a model.".to_string());
    }
    if let Some(key) = &request.api_key {
        if key.trim().is_empty()
            || key.len() > MAX_SECRET_BYTES
            || key.chars().any(char::is_control)
        {
            return Err("The local-runtime API key has an invalid format.".to_string());
        }
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
        Provider::Deepseek => ready
            .model
            .as_deref()
            .is_some_and(|model| !model.trim().is_empty()),
    };
    if ready.api_url.trim().is_empty()
        || ready.workspace_id.trim().is_empty()
        || ready.principal_id.trim().is_empty()
        || !valid_model
    {
        return Err("Qurio local runtime returned an incomplete ready message.".to_string());
    }
    Ok(Some(ready))
}

#[cfg(target_os = "macos")]
fn saved_deepseek_key() -> Result<Option<String>, String> {
    use security_framework::passwords::get_generic_password;
    const NOT_FOUND: i32 = -25300;
    match get_generic_password(RUNTIME_KEYCHAIN_SERVICE, RUNTIME_KEYCHAIN_ACCOUNT) {
        Ok(bytes) => String::from_utf8(bytes)
            .map(Some)
            .map_err(|_| "macOS Keychain returned an invalid Qurio runtime key.".to_string()),
        Err(error) if error.code() == NOT_FOUND => Ok(None),
        Err(_) => Err("macOS Keychain could not read the Qurio runtime key.".to_string()),
    }
}

#[cfg(target_os = "macos")]
fn save_deepseek_key(key: &str) -> Result<(), String> {
    security_framework::passwords::set_generic_password(
        RUNTIME_KEYCHAIN_SERVICE,
        RUNTIME_KEYCHAIN_ACCOUNT,
        key.trim().as_bytes(),
    )
    .map_err(|_| "macOS Keychain could not store the Qurio runtime key.".to_string())
}

#[cfg(not(target_os = "macos"))]
fn saved_deepseek_key() -> Result<Option<String>, String> {
    Err("Qurio local runtime requires macOS Keychain.".to_string())
}
#[cfg(not(target_os = "macos"))]
fn save_deepseek_key(_key: &str) -> Result<(), String> {
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
    pub(crate) fn new(resource_dir: PathBuf, app_data_dir: PathBuf) -> Self {
        Self {
            child: Mutex::new(None),
            status: Mutex::new(LocalRuntimeStatus::stopped()),
            lifecycle_lock: Mutex::new(()),
            bundled_executable: Some(resource_dir.join("qurio-runtime").join("qurio-runtime")),
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
        validate_request(&request)?;
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
            .arg(match request.provider {
                Provider::Mock => "mock",
                Provider::Deepseek => "deepseek",
            })
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        if let Some(runtime_dir) = &self.runtime_dir {
            command.arg("--runtime-dir").arg(runtime_dir);
        }
        if request.provider == Provider::Deepseek {
            command
                .arg("--model")
                .arg(request.model.as_deref().expect("validated model").trim());
            let key = match request.api_key.as_deref() {
                Some(key) => {
                    save_deepseek_key(key)?;
                    key.trim().to_string()
                }
                None => saved_deepseek_key()?.ok_or_else(|| {
                    "Enter a DeepSeek key once to start this local runtime.".to_string()
                })?,
            };
            command.env("DEEPSEEK_API_KEY", key);
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
        if ready.provider != request.provider
            || ready.model.as_deref() != request.model.as_deref().map(str::trim)
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
            model: ready.model,
            message: None,
        };
        *self.child.lock().expect("runtime child lock") = Some(child);
        *self.status.lock().expect("runtime status lock") = status.clone();
        Ok(status)
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

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn rejects_invalid_start_input_without_starting_a_process() {
        assert!(validate_request(&StartLocalRuntimeRequest {
            provider: Provider::Mock,
            model: Some("mock-v1".into()),
            api_key: None
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            provider: Provider::Deepseek,
            model: Some("model".into()),
            api_key: Some("bad\nkey".into())
        })
        .is_err());
        assert!(validate_request(&StartLocalRuntimeRequest {
            provider: Provider::Deepseek,
            model: None,
            api_key: None
        })
        .is_err());
    }
    #[test]
    fn parses_only_complete_ready_messages() {
        let line = "QURIO_RUNTIME_READY {\"api_url\":\"http://127.0.0.1:8123\",\"workspace_id\":\"workspace-1\",\"principal_id\":\"principal-1\",\"provider\":\"mock\",\"model\":null}";
        let ready = parse_ready_line(line).unwrap().unwrap();
        assert_eq!(ready.workspace_id, "workspace-1");
        assert!(parse_ready_line("unrelated log").unwrap().is_none());
        assert!(parse_ready_line("QURIO_RUNTIME_READY {}").is_err());
    }

    #[test]
    fn resolves_packaged_runtime_and_application_support_paths() {
        let manager = LocalRuntimeManager::new(
            PathBuf::from("/Applications/Qurio.app/Contents/Resources"),
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
}
