#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod cache;
mod session;

use tauri::menu::{AboutMetadataBuilder, Menu, MenuBuilder, MenuItemBuilder, SubmenuBuilder};
use tauri::Emitter;
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
    let toggle_sidebar =
        MenuItemBuilder::with_id("view.toggle-sidebar", "Toggle Sidebar").build(app)?;
    let focus_search = MenuItemBuilder::with_id("view.focus-search", "Focus Search")
        .accelerator("CmdOrCtrl+F")
        .build(app)?;
    let command_palette = MenuItemBuilder::with_id("view.command-palette", "Command Palette")
        .accelerator("CmdOrCtrl+K")
        .build(app)?;
    let reload_workspace = MenuItemBuilder::with_id("view.reload-workspace", "Reload Workspace")
        .accelerator("CmdOrCtrl+R")
        .build(app)?;
    let view_menu = SubmenuBuilder::new(app, "View")
        .items(&[
            &toggle_sidebar,
            &focus_search,
            &command_palette,
            &reload_workspace,
        ])
        .build()?;
    let inbox = MenuItemBuilder::with_id("navigate.inbox", "Inbox").build(app)?;
    let investigations =
        MenuItemBuilder::with_id("navigate.investigations", "Investigations").build(app)?;
    let decisions = MenuItemBuilder::with_id("navigate.decisions", "Decisions").build(app)?;
    let monitoring = MenuItemBuilder::with_id("navigate.monitoring", "Monitoring").build(app)?;
    let back_to_list = MenuItemBuilder::with_id("navigate.back-to-list", "Back to List")
        .accelerator("CmdOrCtrl+[")
        .build(app)?;
    let navigate_menu = SubmenuBuilder::new(app, "Navigate")
        .items(&[
            &inbox,
            &investigations,
            &decisions,
            &monitoring,
            &back_to_list,
        ])
        .build()?;
    let window_menu = SubmenuBuilder::new(app, "Window")
        .minimize()
        .maximize()
        .fullscreen()
        .separator()
        .close_window()
        .bring_all_to_front()
        .build()?;
    let keyboard_shortcuts =
        MenuItemBuilder::with_id("help.keyboard-shortcuts", "Keyboard Shortcuts").build(app)?;
    let help_menu = SubmenuBuilder::new(app, "Help")
        .item(&keyboard_shortcuts)
        .build()?;

    MenuBuilder::new(app)
        .items(&[
            &app_menu,
            &edit_menu,
            &view_menu,
            &navigate_menu,
            &window_menu,
            &help_menu,
        ])
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
        .on_menu_event(|app, event| {
            let _ = app.emit("glint-menu", event.id().as_ref());
        })
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
