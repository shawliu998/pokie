const KEYCHAIN_SERVICE: &str = "com.glint.app.session";
const KEYCHAIN_ACCOUNT: &str = "access-token";
const ERR_SEC_ITEM_NOT_FOUND: i32 = -25300;
const MAX_ACCESS_TOKEN_BYTES: usize = 16 * 1024;

fn validate_access_token(access_token: &str) -> Result<&str, String> {
    let token = access_token.trim();
    if token.is_empty() {
        return Err("access token is empty".to_string());
    }
    if token.len() > MAX_ACCESS_TOKEN_BYTES || token.chars().any(char::is_control) {
        return Err("access token format is invalid".to_string());
    }
    Ok(token)
}

#[cfg(target_os = "macos")]
pub(crate) fn read_keychain() -> Result<Option<String>, String> {
    use security_framework::passwords::get_generic_password;

    match get_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) {
        Ok(bytes) => {
            let token = String::from_utf8(bytes)
                .map_err(|_| "macOS Keychain returned an invalid Glint session".to_string())?;
            Ok(Some(validate_access_token(&token)?.to_string()))
        }
        Err(error) if error.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(None),
        Err(_) => Err("macOS Keychain could not read the Glint session".to_string()),
    }
}

#[cfg(not(target_os = "macos"))]
pub(crate) fn read_keychain() -> Result<Option<String>, String> {
    Err("Glint secure sessions require macOS Keychain".to_string())
}

#[cfg(target_os = "macos")]
fn write_keychain(access_token: &str) -> Result<(), String> {
    use security_framework::passwords::set_generic_password;

    let token = validate_access_token(access_token)?;
    set_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, token.as_bytes())
        .map_err(|_| "macOS Keychain could not store the Glint session".to_string())
}

#[cfg(not(target_os = "macos"))]
fn write_keychain(_access_token: &str) -> Result<(), String> {
    Err("Glint secure sessions require macOS Keychain".to_string())
}

#[cfg(target_os = "macos")]
fn delete_keychain() -> Result<(), String> {
    use security_framework::passwords::delete_generic_password;

    match delete_generic_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT) {
        Ok(()) => Ok(()),
        Err(error) if error.code() == ERR_SEC_ITEM_NOT_FOUND => Ok(()),
        Err(_) => Err("macOS Keychain could not clear the Glint session".to_string()),
    }
}

#[cfg(not(target_os = "macos"))]
fn delete_keychain() -> Result<(), String> {
    Err("Glint secure sessions require macOS Keychain".to_string())
}

#[tauri::command]
pub(crate) fn get_access_token() -> Result<Option<String>, String> {
    read_keychain()
}

#[tauri::command]
pub(crate) fn store_access_token(access_token: String) -> Result<(), String> {
    write_keychain(&access_token)
}

#[tauri::command]
pub(crate) fn clear_access_token() -> Result<(), String> {
    delete_keychain()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_opaque_tokens_without_logging_or_decoding_them() {
        assert_eq!(
            validate_access_token("  opaque.jwt-or-provider-token  "),
            Ok("opaque.jwt-or-provider-token")
        );
        assert!(validate_access_token("").is_err());
        assert!(validate_access_token("line\nbreak").is_err());
        assert!(validate_access_token(&"x".repeat(MAX_ACCESS_TOKEN_BYTES + 1)).is_err());
    }

    #[test]
    fn keychain_identity_is_stable_and_token_free() {
        assert_eq!(KEYCHAIN_SERVICE, "com.glint.app.session");
        assert_eq!(KEYCHAIN_ACCOUNT, "access-token");
        assert!(!KEYCHAIN_SERVICE.contains("Bearer"));
    }
}
