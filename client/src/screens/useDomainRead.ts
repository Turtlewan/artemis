import { invoke } from "@tauri-apps/api/core";
import { useEffect, useState } from "react";

import type { DomainId } from "../domains";
import { toApiError } from "../api/errors";
import { ROUTE } from "./domainRoutes";
import type { ScreenDTO } from "./dtos";

export type DomainReader<T extends ScreenDTO> = (route: string) => Promise<T>;

export interface DomainReadState<T extends ScreenDTO> {
  data: T | null;
  loading: boolean;
  error: string | null;
  locked: boolean;
}

const defaultReader: DomainReader<ScreenDTO> = async (route) => {
  // CLIENT-b live shapes are currently simpler than the locked screen DTOs.
  // The real wire-to-screen mapping is deferred; tests inject the richer fake DTOs.
  return invoke<ScreenDTO>(route);
};

export const useDomainRead = <T extends ScreenDTO>(
  domainId: DomainId,
  reader: DomainReader<T> = defaultReader as DomainReader<T>,
): DomainReadState<T> => {
  const [state, setState] = useState<DomainReadState<T>>({
    data: null,
    loading: true,
    error: null,
    locked: false,
  });

  useEffect(() => {
    let alive = true;
    setState({ data: null, loading: true, error: null, locked: false });
    reader(ROUTE[domainId])
      .then((data) => {
        if (alive) setState({ data, loading: false, error: null, locked: false });
      })
      .catch((error: unknown) => {
        if (!alive) return;
        const apiError = toApiError(error);
        setState({
          data: null,
          loading: false,
          error: apiError.kind === "vaultLocked" ? null : "Data not yet available for this domain.",
          locked: apiError.kind === "vaultLocked",
        });
      });
    return () => {
      alive = false;
    };
  }, [domainId, reader]);

  return state;
};
