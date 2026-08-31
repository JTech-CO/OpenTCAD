export interface LocalServiceBootstrap {
  token: string;
}

export type LocalServiceState = "starting" | "ready" | "degraded";
export type LocalExecutionState = "blocked" | "authorized";
export type LocalRecoveryState =
  | "not-applicable"
  | "pending"
  | "ready"
  | "failed";
export type LocalSchedulerState = "not-started" | "running" | "degraded";
export type ProductGateId =
  | "runtime-adapters"
  | "native-fencing"
  | "local-transport"
  | "lifecycle-integration"
  | "credentials-and-scheduler"
  | "power-loss"
  | "platform-qualification"
  | "solver-release";

export interface LocalProductStatus {
  schemaVersion: 1;
  serviceState: LocalServiceState;
  executionState: LocalExecutionState;
  manifestSha256: string;
  backend: "docker" | "podman" | null;
  blockedGates: ProductGateId[];
  recoveryState: LocalRecoveryState;
  schedulerState: LocalSchedulerState;
}

const tokenPattern = /^[A-Za-z0-9_-]{43,171}$/u;
const digestPattern = /^[0-9a-f]{64}$/u;
const productGateIds = new Set<ProductGateId>([
  "runtime-adapters",
  "native-fencing",
  "local-transport",
  "lifecycle-integration",
  "credentials-and-scheduler",
  "power-loss",
  "platform-qualification",
  "solver-release",
]);
const loopbackHosts = new Set(["localhost", "127.0.0.1", "::1", "[::1]"]);

export function consumeLocalBootstrap(
  locationValue: Location = window.location,
  historyValue: History = window.history,
): LocalServiceBootstrap | null {
  const match = /^#local=([A-Za-z0-9_-]+)$/u.exec(locationValue.hash);
  if (!match) {
    return null;
  }
  historyValue.replaceState(
    historyValue.state,
    "",
    `${locationValue.pathname}${locationValue.search}#workspace`,
  );
  if (
    locationValue.protocol !== "http:" ||
    !loopbackHosts.has(locationValue.hostname.toLowerCase()) ||
    !tokenPattern.test(match[1])
  ) {
    return null;
  }
  return { token: match[1] };
}

function exactObject(value: unknown, keys: string[]): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("local-status-invalid");
  }
  const record = value as Record<string, unknown>;
  if (
    JSON.stringify(Object.keys(record).sort()) !==
    JSON.stringify([...keys].sort())
  ) {
    throw new Error("local-status-invalid");
  }
  return record;
}

export function decodeLocalProductStatus(value: unknown): LocalProductStatus {
  const record = exactObject(value, [
    "schemaVersion",
    "serviceState",
    "executionState",
    "manifestSha256",
    "backend",
    "blockedGates",
    "recoveryState",
    "schedulerState",
  ]);
  const services = new Set(["starting", "ready", "degraded"]);
  const executions = new Set(["blocked", "authorized"]);
  const recoveries = new Set([
    "not-applicable",
    "pending",
    "ready",
    "failed",
  ]);
  const schedulers = new Set(["not-started", "running", "degraded"]);
  const gates = record.blockedGates;
  if (
    record.schemaVersion !== 1 ||
    typeof record.serviceState !== "string" ||
    !services.has(record.serviceState) ||
    typeof record.executionState !== "string" ||
    !executions.has(record.executionState) ||
    typeof record.manifestSha256 !== "string" ||
    !digestPattern.test(record.manifestSha256) ||
    (record.backend !== null &&
      record.backend !== "docker" &&
      record.backend !== "podman") ||
    !Array.isArray(gates) ||
    gates.some(
      (item) =>
        typeof item !== "string"
        || !productGateIds.has(item as ProductGateId),
    ) ||
    new Set(gates).size !== gates.length ||
    typeof record.recoveryState !== "string" ||
    !recoveries.has(record.recoveryState) ||
    typeof record.schedulerState !== "string" ||
    !schedulers.has(record.schedulerState)
  ) {
    throw new Error("local-status-invalid");
  }
  if (
    (record.executionState === "blocked" &&
      (record.backend !== null || gates.length === 0)) ||
    (record.executionState === "authorized" &&
      (record.backend === null || gates.length !== 0))
  ) {
    throw new Error("local-status-invalid");
  }
  return {
    schemaVersion: 1,
    serviceState: record.serviceState as LocalServiceState,
    executionState: record.executionState as LocalExecutionState,
    manifestSha256: record.manifestSha256,
    backend: record.backend as "docker" | "podman" | null,
    blockedGates: [...(gates as ProductGateId[])],
    recoveryState: record.recoveryState as LocalRecoveryState,
    schedulerState: record.schedulerState as LocalSchedulerState,
  };
}

export async function fetchLocalProductStatus(
  bootstrap: LocalServiceBootstrap,
  fetcher: typeof fetch = fetch,
  timeoutMs = 5_000,
): Promise<LocalProductStatus> {
  if (!tokenPattern.test(bootstrap.token)) {
    throw new Error("local-bootstrap-invalid");
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher("/v1/status", {
      method: "GET",
      headers: {
        Accept: "application/json",
        Authorization: `Bearer ${bootstrap.token}`,
      },
      cache: "no-store",
      redirect: "error",
      credentials: "omit",
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") ?? "";
    if (!response.ok || !/^application\/json(?:;|$)/iu.test(contentType)) {
      throw new Error("local-status-unavailable");
    }
    return decodeLocalProductStatus(await response.json());
  } finally {
    window.clearTimeout(timeout);
  }
}
