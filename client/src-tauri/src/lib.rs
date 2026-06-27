mod auth;
mod error;
mod gateway;
mod state;

use tauri::{Emitter, Manager, RunEvent};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};

const DEFAULT_BRAIN_BASE_URL: &str = "http://127.0.0.1:8030";

fn ask_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::ALT), Code::Space)
}

fn set_default_base_url(state: &state::AppState) {
    if state.base_url().is_none() {
        state.set_base_url(DEFAULT_BRAIN_BASE_URL.to_string());
    }
}

pub fn run() {
    tauri::Builder::default()
        .manage(state::AppState::default())
        .setup(|app| {
            let state = app.state::<state::AppState>();
            set_default_base_url(&state);
            Ok(())
        })
        .plugin(tauri_plugin_keystore::init())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_shortcut(ask_shortcut())
                .expect("failed to register Artemis Ask global shortcut")
                .with_handler(|app, shortcut, event| {
                    if *shortcut != ask_shortcut() || event.state != ShortcutState::Pressed {
                        return;
                    }

                    if let Some(window) = app.get_webview_window("ask") {
                        let _ = window.show();
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
            gateway::app_actions_pending,
            gateway::app_actions_approve,
            gateway::app_actions_reject,
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_base_url_targets_local_brain_when_unset() {
        let state = state::AppState::default();

        set_default_base_url(&state);

        assert_eq!(state.base_url().as_deref(), Some(DEFAULT_BRAIN_BASE_URL));
    }

    #[test]
    fn default_base_url_does_not_override_existing_url() {
        let state = state::AppState::default();
        state.set_base_url("http://127.0.0.1:9000".to_string());

        set_default_base_url(&state);

        assert_eq!(state.base_url().as_deref(), Some("http://127.0.0.1:9000"));
    }
}
