import { useCallback, useEffect, useState } from "react";
import { getHealth } from "./api";

export type ApiHealthState =
  | "checking"
  | "waking"
  | "operational"
  | "unavailable";

export const BACKEND_HEALTH_RETRY_INTERVAL_MS = 9_000;
export const BACKEND_HEALTH_MAX_ATTEMPTS = 10;

type HealthCheck = (signal?: AbortSignal) => Promise<unknown>;
type RetryWait = (milliseconds: number, signal: AbortSignal) => Promise<void>;

interface HealthMonitorOptions {
  signal: AbortSignal;
  onStateChange: (state: ApiHealthState) => void;
  check?: HealthCheck;
  wait?: RetryWait;
  intervalMs?: number;
  maxAttempts?: number;
}

function waitForRetry(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const finish = () => {
      signal.removeEventListener("abort", handleAbort);
      resolve();
    };
    const timeout = window.setTimeout(finish, milliseconds);
    const handleAbort = () => {
      window.clearTimeout(timeout);
      finish();
    };
    signal.addEventListener("abort", handleAbort, { once: true });
  });
}

export async function monitorBackendHealth({
  signal,
  onStateChange,
  check = getHealth,
  wait = waitForRetry,
  intervalMs = BACKEND_HEALTH_RETRY_INTERVAL_MS,
  maxAttempts = BACKEND_HEALTH_MAX_ATTEMPTS,
}: HealthMonitorOptions): Promise<void> {
  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (signal.aborted) return;
    try {
      await check(signal);
      if (!signal.aborted) onStateChange("operational");
      return;
    } catch {
      if (signal.aborted) return;
      if (attempt === maxAttempts) {
        onStateChange("unavailable");
        return;
      }
      onStateChange("waking");
      await wait(intervalMs, signal);
    }
  }
}

export function useBackendHealth() {
  const [state, setState] = useState<ApiHealthState>("checking");
  const [requestVersion, setRequestVersion] = useState(0);
  const retry = useCallback(() => {
    setState("checking");
    setRequestVersion((value) => value + 1);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void monitorBackendHealth({
      signal: controller.signal,
      onStateChange: setState,
    });
    return () => controller.abort();
  }, [requestVersion]);

  return { state, retry };
}
