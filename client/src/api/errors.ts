export type ApiError =
  | { kind: "unauthenticated" }
  | { kind: "vaultLocked" }
  | { kind: "http"; status: number }
  | { kind: "network" };

interface SerializedGatewayError {
  kind?: unknown;
  status?: unknown;
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

const statusFromThrown = (error: unknown): number | null => {
  if (typeof error === "number") {
    return error;
  }
  if (typeof error === "string") {
    const parsed = Number.parseInt(error, 10);
    return Number.isNaN(parsed) ? null : parsed;
  }
  if (!isRecord(error)) {
    return null;
  }
  const status = error.status;
  return typeof status === "number" ? status : null;
};

export const toApiError = (error: unknown): ApiError => {
  if (isRecord(error)) {
    const gateway = error as SerializedGatewayError;
    if (gateway.kind === "unauthenticated") {
      return { kind: "unauthenticated" };
    }
    if (gateway.kind === "vaultLocked") {
      return { kind: "vaultLocked" };
    }
    if (gateway.kind === "http" && typeof gateway.status === "number") {
      if (gateway.status === 401) {
        return { kind: "unauthenticated" };
      }
      if (gateway.status === 423) {
        return { kind: "vaultLocked" };
      }
      return { kind: "http", status: gateway.status };
    }
    if (gateway.kind === "network") {
      return { kind: "network" };
    }
  }

  const status = statusFromThrown(error);
  if (status === 401) {
    return { kind: "unauthenticated" };
  }
  if (status === 423) {
    return { kind: "vaultLocked" };
  }
  if (status !== null) {
    return { kind: "http", status };
  }
  return { kind: "network" };
};
