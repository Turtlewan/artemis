import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { DomainId } from "../domains";
import { domainLabel } from "../domains";
import { firstLastInvert, morphKeyframes } from "./morph";
import { getDomainDetail } from "./registry";

interface DetailOverlayProps {
  openId: DomainId | null;
  onClose: () => void;
  originRef: RefObject<HTMLElement | null>;
}

const styles = `
.card-overlay{position:fixed;inset:0;z-index:50;display:grid;place-items:center;padding:48px 28px;background:rgba(0,0,0,0.18)}
.card-overlay[hidden]{display:none}
.card-overlay__dialog{position:relative;width:min(820px,calc(100vw - 56px));height:min(620px,calc(100vh - 96px));display:flex;flex-direction:column;outline:none;opacity:0;visibility:hidden}
.card-overlay__dialog.card-overlay__dialog--ready{opacity:1;visibility:visible}
.card-overlay__header{display:flex;align-items:center;gap:14px;padding:18px 20px;border-bottom:1px solid var(--hair)}
.card-overlay__title{margin:0;font-size:18px;line-height:1.2}
.card-overlay__close{margin-left:auto;border:1px solid var(--hair);border-radius:8px;background:color-mix(in srgb,var(--p) 12%,transparent);color:var(--text);font:inherit;font-size:20px;line-height:1;width:34px;height:34px;cursor:pointer}
.card-overlay__close:hover,.card-overlay__close:focus-visible{border-color:var(--focus-ring)}
.card-overlay__body{min-height:0;flex:1;overflow:auto;padding:20px}
.card-overlay__fallback h2{margin:0 0 8px;font-size:16px}
.card-overlay__fallback p{margin:0;color:var(--muted)}
`;

let stylesMounted = false;

const ensureStyles = (): void => {
  if (stylesMounted || typeof document === "undefined") return;
  const style = document.createElement("style");
  style.dataset.cardOverlay = "true";
  style.textContent = styles;
  document.head.append(style);
  stylesMounted = true;
};

const prefersReducedMotion = (): boolean =>
  typeof window !== "undefined" &&
  window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const focusableSelector = [
  "button:not([disabled])",
  "[href]",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

const finishAnimation = (animation: Animation, onDone: () => void): void => {
  animation.onfinish = onDone;
  animation.oncancel = onDone;
};

/** Top-most focus-trapped card detail dialog with FLIP open/close morphs. */
export function DetailOverlay({ openId, onClose, originRef }: DetailOverlayProps) {
  ensureStyles();
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previousOpenId = useRef<DomainId | null>(null);
  const [renderedId, setRenderedId] = useState<DomainId | null>(openId);
  const [visible, setVisible] = useState(openId !== null);
  const closingRef = useRef(false);

  useEffect(() => {
    if (openId !== null) {
      previousOpenId.current = openId;
      setRenderedId(openId);
      setVisible(true);
    }
  }, [openId]);

  const returnFocus = useCallback((): void => {
    const origin = originRef.current;
    if (origin?.isConnected === true) origin.focus();
  }, [originRef]);

  const close = useCallback((): void => {
    if (renderedId === null || closingRef.current) return;
    const dialog = dialogRef.current;
    if (dialog === null || typeof dialog.animate !== "function" || prefersReducedMotion()) {
      setVisible(false);
      onClose();
      returnFocus();
      return;
    }

    const origin = originRef.current;
    const toOrigin = origin?.isConnected === true ? origin : null;
    const firstRect = dialog.getBoundingClientRect();
    const lastRect = toOrigin?.getBoundingClientRect();
    closingRef.current = true;
    dialog.style.willChange = "transform,opacity";
    const animation =
      lastRect === undefined
        ? dialog.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: "ease-out" })
        : dialog.animate([...morphKeyframes(firstLastInvert(lastRect, firstRect))].reverse(), {
            duration: 190,
            easing: "cubic-bezier(.2,.8,.2,1)",
          });
    finishAnimation(animation, () => {
      dialog.style.willChange = "";
      closingRef.current = false;
      setVisible(false);
      onClose();
      returnFocus();
    });
  }, [onClose, originRef, renderedId, returnFocus]);

  useEffect(() => {
    if (!visible || renderedId === null) return;
    const dialog = dialogRef.current;
    if (dialog === null) return;

    if (previousOpenId.current !== renderedId) previousOpenId.current = renderedId;

    if (typeof dialog.animate !== "function" || prefersReducedMotion()) {
      dialog.classList.add("card-overlay__dialog--ready");
      dialog.focus();
      return;
    }

    const origin = originRef.current;
    const fromRect = origin?.isConnected === true ? origin.getBoundingClientRect() : undefined;
    const toRect = dialog.getBoundingClientRect();
    dialog.classList.add("card-overlay__dialog--ready");
    dialog.focus();
    dialog.style.willChange = "transform,opacity";
    const animation =
      fromRect === undefined
        ? dialog.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 140, easing: "ease-out" })
        : dialog.animate(morphKeyframes(firstLastInvert(fromRect, toRect)), {
            duration: 220,
            easing: "cubic-bezier(.2,.8,.2,1)",
          });
    finishAnimation(animation, () => {
      dialog.style.willChange = "";
    });
  }, [originRef, renderedId, visible]);

  useEffect(() => {
    if (!visible) return;
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key !== "Tab") return;
      const dialog = dialogRef.current;
      if (dialog === null) return;
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(focusableSelector));
      if (focusable.length === 0) {
        event.preventDefault();
        dialog.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [close, visible]);

  if (!visible || renderedId === null) return null;

  const RegisteredDetail = getDomainDetail(renderedId);

  return (
    <div className="card-overlay" data-testid="card-overlay">
      <div
        ref={dialogRef}
        className="card-overlay__dialog glass"
        role="dialog"
        aria-modal="true"
        aria-labelledby="card-overlay-title"
        tabIndex={-1}
      >
        <div className="card-overlay__header">
          <h2 className="card-overlay__title" id="card-overlay-title">
            {domainLabel(renderedId)}
          </h2>
          <button className="card-overlay__close" type="button" aria-label="Close" onClick={close}>
            ×
          </button>
        </div>
        <div className="card-overlay__body">
          {RegisteredDetail === undefined ? (
            <section className="card-overlay__fallback">
              <h2>{domainLabel(renderedId)} detail coming</h2>
              <p>Detail coming.</p>
            </section>
          ) : (
            <RegisteredDetail domainId={renderedId} onClose={close} />
          )}
        </div>
      </div>
    </div>
  );
}
