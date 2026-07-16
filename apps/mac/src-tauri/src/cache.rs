use base64::{engine::general_purpose::URL_SAFE_NO_PAD, Engine as _};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};
use tauri::{AppHandle, Manager};

use crate::session::read_keychain;

const NATIVE_CACHE_SCHEMA: &str = "glint-native-cache-v1";
const PROJECTION_CACHE_SCHEMA: &str = "glint-redacted-workspace-v1";

#[derive(Serialize, Deserialize)]
struct NativeCacheEnvelope {
    schema_version: String,
    workspace_id: String,
    principal_id: String,
    cached_at: String,
    token_fingerprint: String,
    projection_json: String,
}

fn valid_scope_id(value: &str) -> bool {
    value.len() == 36
        && value.chars().enumerate().all(|(index, character)| {
            if [8, 13, 18, 23].contains(&index) {
                character == '-'
            } else {
                character.is_ascii_hexdigit()
            }
        })
}

fn token_claims(token: &str) -> Result<(String, f64), String> {
    let segments: Vec<&str> = token.split('.').collect();
    if segments.len() != 3 {
        return Err("the Keychain session is not a signed access token".to_string());
    }
    let bytes = URL_SAFE_NO_PAD
        .decode(segments[1])
        .map_err(|_| "the Keychain session payload is invalid".to_string())?;
    let payload: Value = serde_json::from_slice(&bytes)
        .map_err(|_| "the Keychain session payload is invalid".to_string())?;
    let subject = payload
        .get("sub")
        .and_then(Value::as_str)
        .filter(|value| valid_scope_id(value))
        .ok_or_else(|| "the Keychain session subject is invalid".to_string())?;
    let expiry = payload
        .get("exp")
        .and_then(Value::as_f64)
        .ok_or_else(|| "the Keychain session expiry is invalid".to_string())?;
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "the system clock is invalid".to_string())?
        .as_secs_f64();
    if expiry <= now {
        return Err("the Keychain session is expired".to_string());
    }
    Ok((subject.to_string(), expiry))
}

fn fingerprint(token: &str) -> String {
    let digest = Sha256::digest(token.as_bytes());
    digest.iter().map(|byte| format!("{byte:02x}")).collect()
}

fn contains_forbidden_key(value: &Value) -> bool {
    match value {
        Value::Object(items) => items.iter().any(|(key, nested)| {
            let normalized = key.to_ascii_lowercase();
            normalized.contains("token")
                || normalized.contains("credential")
                || normalized.contains("secret")
                || normalized == "raw"
                || normalized.starts_with("raw_")
                || contains_forbidden_key(nested)
        }),
        Value::Array(items) => items.iter().any(contains_forbidden_key),
        _ => false,
    }
}

fn validate_projection(
    projection_json: &str,
    workspace_id: &str,
    principal_id: &str,
    cached_at: &str,
) -> Result<(), String> {
    let projection: Value = serde_json::from_str(projection_json)
        .map_err(|_| "offline cache projection is invalid JSON".to_string())?;
    if contains_forbidden_key(&projection) {
        return Err("offline cache projection contains a forbidden secret-bearing field".to_string());
    }
    let object = projection
        .as_object()
        .ok_or_else(|| "offline cache projection is invalid".to_string())?;
    if object.get("schemaVersion").and_then(Value::as_str) != Some(PROJECTION_CACHE_SCHEMA)
        || object.get("workspaceId").and_then(Value::as_str) != Some(workspace_id)
        || object.get("principalId").and_then(Value::as_str) != Some(principal_id)
        || object.get("cachedAt").and_then(Value::as_str) != Some(cached_at)
    {
        return Err("offline cache projection scope is invalid".to_string());
    }
    Ok(())
}

fn cache_directory(app: &AppHandle) -> Result<PathBuf, String> {
    let directory = app
        .path()
        .app_data_dir()
        .map_err(|_| "Glint app-data directory is unavailable".to_string())?
        .join("offline-cache");
    fs::create_dir_all(&directory)
        .map_err(|_| "Glint offline cache directory could not be created".to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&directory, fs::Permissions::from_mode(0o700))
            .map_err(|_| "Glint offline cache permissions could not be restricted".to_string())?;
    }
    Ok(directory)
}

fn cache_path(app: &AppHandle, workspace_id: &str) -> Result<PathBuf, String> {
    if !valid_scope_id(workspace_id) {
        return Err("offline cache workspace scope is invalid".to_string());
    }
    Ok(cache_directory(app)?.join(format!("workspace-{workspace_id}.json")))
}

fn restricted_write(path: &Path, contents: &[u8]) -> Result<(), String> {
    let temporary = path.with_extension("tmp");
    fs::write(&temporary, contents)
        .map_err(|_| "Glint offline cache could not be written".to_string())?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        fs::set_permissions(&temporary, fs::Permissions::from_mode(0o600))
            .map_err(|_| "Glint offline cache permissions could not be restricted".to_string())?;
    }
    fs::rename(&temporary, path)
        .map_err(|_| "Glint offline cache could not be replaced atomically".to_string())
}

#[tauri::command]
pub(crate) fn store_offline_cache(
    app: AppHandle,
    workspace_id: String,
    principal_id: String,
    cached_at: String,
    projection_json: String,
) -> Result<(), String> {
    if !valid_scope_id(&principal_id) || cached_at.len() < 20 || !cached_at.ends_with('Z') {
        return Err("offline cache principal or timestamp scope is invalid".to_string());
    }
    let token = read_keychain()?.ok_or_else(|| "no Keychain session is available".to_string())?;
    let (subject, _) = token_claims(&token)?;
    if subject != principal_id {
        return Err("offline cache principal does not match the Keychain session".to_string());
    }
    validate_projection(&projection_json, &workspace_id, &principal_id, &cached_at)?;
    let envelope = NativeCacheEnvelope {
        schema_version: NATIVE_CACHE_SCHEMA.to_string(),
        workspace_id: workspace_id.clone(),
        principal_id,
        cached_at,
        token_fingerprint: fingerprint(&token),
        projection_json,
    };
    let bytes = serde_json::to_vec(&envelope)
        .map_err(|_| "Glint offline cache could not be encoded".to_string())?;
    restricted_write(&cache_path(&app, &workspace_id)?, &bytes)
}

#[tauri::command]
pub(crate) fn get_offline_cache(
    app: AppHandle,
    workspace_id: String,
) -> Result<Option<String>, String> {
    let path = cache_path(&app, &workspace_id)?;
    let bytes = match fs::read(path) {
        Ok(value) => value,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err("Glint offline cache could not be read".to_string()),
    };
    let envelope: NativeCacheEnvelope = serde_json::from_slice(&bytes)
        .map_err(|_| "Glint offline cache envelope is invalid".to_string())?;
    if envelope.schema_version != NATIVE_CACHE_SCHEMA || envelope.workspace_id != workspace_id {
        return Ok(None);
    }
    let token = read_keychain()?.ok_or_else(|| "no Keychain session is available".to_string())?;
    let (subject, _) = token_claims(&token)?;
    if subject != envelope.principal_id || fingerprint(&token) != envelope.token_fingerprint {
        return Ok(None);
    }
    validate_projection(
        &envelope.projection_json,
        &workspace_id,
        &envelope.principal_id,
        &envelope.cached_at,
    )?;
    Ok(Some(envelope.projection_json))
}

#[tauri::command]
pub(crate) fn clear_offline_cache(app: AppHandle, workspace_id: String) -> Result<(), String> {
    let path = cache_path(&app, &workspace_id)?;
    match fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err("Glint offline cache could not be cleared".to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signed_session_claims_are_subject_and_expiry_scoped() {
        let subject = "00000000-0000-4000-8000-000000000002";
        let expiry = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs() + 300;
        let payload = URL_SAFE_NO_PAD.encode(format!(r#"{{"sub":"{subject}","exp":{expiry}}}"#));
        let token = format!("header.{payload}.signature");
        assert_eq!(token_claims(&token).unwrap().0, subject);
        let expired = URL_SAFE_NO_PAD.encode(format!(r#"{{"sub":"{subject}","exp":1}}"#));
        assert!(token_claims(&format!("header.{expired}.signature")).is_err());
    }

    #[test]
    fn projection_validation_rejects_scope_drift_secrets_and_old_versions() {
        let workspace = "00000000-0000-4000-8000-000000000001";
        let principal = "00000000-0000-4000-8000-000000000002";
        let cached_at = "2026-07-15T05:00:00Z";
        let valid = format!(r#"{{"schemaVersion":"{PROJECTION_CACHE_SCHEMA}","workspaceId":"{workspace}","principalId":"{principal}","cachedAt":"{cached_at}","projection":{{}}}}"#);
        assert!(validate_projection(&valid, workspace, principal, cached_at).is_ok());
        assert!(validate_projection(&valid.replace(PROJECTION_CACHE_SCHEMA, "old-v0"), workspace, principal, cached_at).is_err());
        assert!(validate_projection(&valid.replace("\"projection\":{}", "\"access_token\":\"secret\""), workspace, principal, cached_at).is_err());
    }
}
