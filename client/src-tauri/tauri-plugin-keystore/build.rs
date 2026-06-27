const COMMANDS: &[&str] = &["create_key", "sign", "get_public_key", "destroy_key", "has_key"];

fn main() {
    tauri_plugin::Builder::new(COMMANDS).build();
}
