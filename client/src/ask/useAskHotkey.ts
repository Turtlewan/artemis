import { listen } from "@tauri-apps/api/event";
import { useCallback, useEffect, useRef, useState } from "react";

export interface AskHotkeyController {
  isOpen: boolean;
  open: () => void;
  close: () => void;
  askButtonProps: {
    type: "button";
    "aria-haspopup": "dialog";
    "aria-expanded": boolean;
    onClick: () => void;
  };
}

const focusableElement = (element: Element | null): element is HTMLElement =>
  element instanceof HTMLElement && typeof element.focus === "function";

/** Listens for the zero-payload ask:summon event and owns focus restoration for every close path. */
export function useAskHotkey(): AskHotkeyController {
  const [isOpen, setIsOpen] = useState(false);
  const restoreRef = useRef<HTMLElement | null>(null);

  const open = useCallback((): void => {
    restoreRef.current = focusableElement(document.activeElement) ? document.activeElement : null;
    setIsOpen(true);
  }, []);

  const close = useCallback((): void => {
    setIsOpen(false);
    window.requestAnimationFrame(() => {
      restoreRef.current?.focus();
      restoreRef.current = null;
    });
  }, []);

  useEffect(() => {
    let disposed = false;
    let unlisten: (() => void) | undefined;

    void listen<null>("ask:summon", () => {
      open();
    }).then((cleanup) => {
      if (disposed) {
        cleanup();
        return;
      }
      unlisten = cleanup;
    });

    return () => {
      disposed = true;
      unlisten?.();
    };
  }, [open]);

  return {
    isOpen,
    open,
    close,
    askButtonProps: {
      type: "button",
      "aria-haspopup": "dialog",
      "aria-expanded": isOpen,
      onClick: open,
    },
  };
}
