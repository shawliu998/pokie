fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_access_token",
            "store_access_token",
            "clear_access_token",
            "store_offline_cache",
            "get_offline_cache",
            "clear_offline_cache",
        ]),
    ))
    .expect("failed to build the restricted Glint Tauri manifest")
}
