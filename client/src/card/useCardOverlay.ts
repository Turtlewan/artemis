import { useCallback, useRef, useState } from "react";

import type { DomainId } from "../domains";

/** Stores the currently open domain plus the originating CardSlot for morph and focus return. */
export function useCardOverlay() {
  const [openId, setOpenId] = useState<DomainId | null>(null);
  const originRef = useRef<HTMLElement | null>(null);

  const open = useCallback((domainId: DomainId): void => {
    setOpenId(domainId);
  }, []);

  const close = useCallback((): void => {
    setOpenId(null);
  }, []);

  return { openId, open, close, originRef };
}

