mod auth;
mod error;
mod gateway;
mod state;

use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

fn ask_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::ALT), Code::Space)
}

pub fn run() {
    tauri::Builder::default()
        .manage(state::AppState::default())
        .plugin(tauri_plugin_keystore::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcut(ask_shortcut())
                .expect("failed to register Artemis Ask global shortcut")
                .with_handler(|app, shortcut, event| {
                    if *shortcut != ask_shortcut() || event.state != ShortcutState::Pressed {
                        return;
                    }

                    if let Some(window) = app.get_webview_window("main") {
                        let _ = window.unminimize();
                        let _ = window.set_focus();
                        let _ = window.emit("ask:summon", ());
                    }
                })
                .build(),
        )
        .invoke_handler(tauri::generate_handler![
            gateway::app_status,
            gateway::app_review_pending,
            gateway::app_review_auto_enabled,
            gateway::app_review_approve,
            gateway::app_review_reject,
            gateway::app_ask,
            gateway::app_ask_stream,
            gateway::app_lock,
            gateway::app_logout,
            gateway::app_layout_get,
            gateway::app_layout_put,
            auth::auth_pair,
            auth::auth_connect,
            auth::auth_unlock,
            auth::auth_logout,
            auth::auth_recover
        ])
        .build(tauri::generate_context!())
        .expect("error while building Artemis client")
        .run(|app, event| {
            if let RunEvent::ExitRequested { .. } = event {
                let _ = app.global_shortcut().unregister(ask_shortcut());
            }
        });
}
