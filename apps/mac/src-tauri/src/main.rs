#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cache;
mod session;

use tauri::menu::{AboutMetadataBuilder, Menu, MenuBuilder, SubmenuBuilder};
use tauri_plugin_window_state::StateFlags;

fn native_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let about = AboutMetadataBuilder::new()
        .name(Some("Glint"))
        .version(Some(app.package_info().version.to_string()))
        .build();
    let app_menu = SubmenuBuilder::new(app, "Glint")
        .about(Some(about))
        .separator()
        .hide()
        .hide_others()
        .show_all()
        .separator()
        .quit()
        .build()?;
    let edit_menu = SubmenuBuilder::new(app, "Edit")
        .undo()
        .redo()
        .separator()
        .cut()
        .copy()
        .paste()
        .select_all()
        .build()?;
    let window_menu = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .fullscreen()
        .separator()
        .close_window()
        .bring_all_to_front()
        .build()?;

    MenuBuilder::new(app)
        .items(&[&app_menu, &edit_menu, &window_menu])
        .build()
}

fn main() {
    tauri::Builder::default()
        .plugin(
            tauri_plugin_window_state::Builder::default()
                .with_state_flags(StateFlags::SIZE | StateFlags::MAXIMIZED)
                .build(),
        )
        .menu(native_menu)
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
