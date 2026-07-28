fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "get_access_token",
            "store_access_token",
            "clear_access_token",
            "store_offline_cache",
            "get_offline_cache",
            "clear_offline_cache",
            "start_local_runtime",
            "stop_local_runtime",
            "get_local_runtime_status",
            "test_local_runtime_provider",
        ]),
    ))
    .expect("failed to build the restricted Qurio Tauri manifest")
}
