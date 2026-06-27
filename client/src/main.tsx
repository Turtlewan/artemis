import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import { Component, StrictMode, type ErrorInfo, type ReactNode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { AskWindow } from "./ask/AskWindow";

/**
 * Top-level boundary: a crash in any component (incl. a Tauri-API startup
 * failure) renders a visible error instead of unmounting the tree to a blank
 * screen. Catches render- and effect-phase errors.
 */
class RootErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error): { error: Error } {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Artemis UI crashed:", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.error) {
      return (
        <pre
          style={{
            color: "#ffb4a8",
            background: "#0b0e14",
            padding: 16,
            margin: 0,
            height: "100vh",
            whiteSpace: "pre-wrap",
            font: "12px ui-monospace, monospace",
            overflow: "auto",
          }}
        >
          {`Artemis UI crashed at startup:\n\n${this.state.error.message}\n\n${this.state.error.stack ?? ""}`}
        </pre>
      );
    }
    return this.props.children;
  }
}

const root = document.getElementById("root");

if (root === null) {
  throw new Error("Root element #root was not found");
}

const currentWindowLabel = (): string => {
  try {
    return getCurrentWebviewWindow().label;
  } catch {
    return "main";
  }
};

const RootView = currentWindowLabel() === "ask" ? AskWindow : App;

createRoot(root).render(
  <StrictMode>
    <RootErrorBoundary>
      <RootView />
    </RootErrorBoundary>
  </StrictMode>,
);
