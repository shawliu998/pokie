#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cache;
mod local_runtime;
mod session;

use tauri::{
    menu::{AboutMetadataBuilder, Menu, MenuBuilder, SubmenuBuilder},
    Manager,
};
use tauri_plugin_window_state::StateFlags;

fn native_menu(app: &tauri::AppHandle) -> tauri::Result<Menu<tauri::Wry>> {
    let about = AboutMetadataBuilder::new()
        .name(Some("Qurio"))
        .version(Some(app.package_info().version.to_string()))
        .build();
    let app_menu = SubmenuBuilder::new(app, "Qurio")
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
        .setup(|app| {
            // A missing resource path must not take down the entire workspace.
            // Packaged builds resolve this directory and use the embedded
            // runtime. Source/dev launches can safely fall back to the checked
            // out runtime, while an incomplete installation reports the
            // actionable runtime error only when the user starts the Agent.
            let resource_dir = app.path().resource_dir().ok();
            let app_data_dir = app.path().app_data_dir()?;
            app.manage(local_runtime::LocalRuntimeManager::new(
                resource_dir,
                app_data_dir,
            ));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            session::get_access_token,
            session::store_access_token,
            session::clear_access_token,
            cache::store_offline_cache,
            cache::get_offline_cache,
            cache::clear_offline_cache,
            local_runtime::start_local_runtime,
            local_runtime::stop_local_runtime,
            local_runtime::get_local_runtime_status,
            local_runtime::test_local_runtime_provider,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Qurio");
}
