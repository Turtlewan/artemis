use std::fmt;
use std::sync::Mutex;

use zeroize::Zeroizing;

#[derive(Default)]
pub(crate) struct AppState {
    pub(crate) session_token: Mutex<Option<Zeroizing<String>>>,
    pub(crate) brain_base_url: Mutex<Option<String>>,
}

impl AppState {
    pub(crate) fn token(&self) -> Option<String> {
        self.session_token
            .lock()
            .expect("session token mutex poisoned")
            .as_ref()
            .map(|token| token.to_string())
    }

    pub(crate) fn set_token(&self, token: String) {
        *self
            .session_token
            .lock()
            .expect("session token mutex poisoned") = Some(Zeroizing::new(token));
    }

    pub(crate) fn clear_token(&self) {
        *self
            .session_token
            .lock()
            .expect("session token mutex poisoned") = None;
    }

    pub(crate) fn set_base_url(&self, url: String) {
        *self
            .brain_base_url
            .lock()
            .expect("brain base URL mutex poisoned") = Some(url);
    }

    pub(crate) fn base_url(&self) -> Option<String> {
        self.brain_base_url
            .lock()
            .expect("brain base URL mutex poisoned")
            .clone()
    }
}

impl fmt::Debug for AppState {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("AppState")
            .field("session_token", &"<redacted>")
            .field("brain_base_url", &self.base_url())
            .finish()
    }
}
