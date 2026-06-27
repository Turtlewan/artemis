import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";

import "../theme/tokens.css";
import { AskPopup } from "./AskPopup";

const hideAskWindow = (): void => {
  try {
    void getCurrentWebviewWindow().hide();
  } catch {
    // Unit-test and browser preview environments do not provide a Tauri window.
  }
};

export function AskWindow() {
  return <AskPopup isOpen={true} onClose={hideAskWindow} />;
}
