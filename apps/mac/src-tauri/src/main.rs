#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cache;
mod session;

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            session::get_access_token,
            session::store_access_token,
            session::clear_access_token,
            cache::store_offline_cache,
            cache::get_offline_cache,
            cache::clear_offline_cache,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Glint");
}
