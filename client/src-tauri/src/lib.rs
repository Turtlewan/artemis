mod error;
mod gateway;
mod state;

pub fn run() {
    tauri::Builder::default()
        .manage(state::AppState::default())
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
            gateway::app_layout_put
        ])
        .run(tauri::generate_context!())
        .expect("error while running Artemis client");
}
