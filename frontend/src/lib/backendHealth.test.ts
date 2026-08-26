import { describe, expect, it, vi } from "vitest";
import {
  BACKEND_HEALTH_MAX_ATTEMPTS,
  BACKEND_HEALTH_RETRY_INTERVAL_MS,
  monitorBackendHealth,
  type ApiHealthState,
} from "./backendHealth";

describe("Render Free backend health monitoring", () => {
  it("uses a bounded nine-second retry window", () => {
    expect(BACKEND_HEALTH_RETRY_INTERVAL_MS).toBe(9_000);
    expect(BACKEND_HEALTH_MAX_ATTEMPTS).toBe(10);
  });

  it("stops retrying immediately after health succeeds", async () => {
    const check = vi.fn()
      .mockRejectedValueOnce(new Error("sleeping"))
      .mockRejectedValueOnce(new Error("starting"))
      .mockResolvedValue({ status: "ok" });
    const wait = vi.fn().mockResolvedValue(undefined);
    const states: ApiHealthState[] = [];

    await monitorBackendHealth({
      signal: new AbortController().signal,
      onStateChange: (state) => states.push(state),
      check,
      wait,
    });

    expect(check).toHaveBeenCalledTimes(3);
    expect(wait).toHaveBeenCalledTimes(2);
    expect(states).toEqual(["waking", "waking", "operational"]);
  });

  it("stops after the configured maximum attempts", async () => {
    const check = vi.fn().mockRejectedValue(new Error("still sleeping"));
    const wait = vi.fn().mockResolvedValue(undefined);
    const states: ApiHealthState[] = [];

    await monitorBackendHealth({
      signal: new AbortController().signal,
      onStateChange: (state) => states.push(state),
      check,
      wait,
    });

    expect(check).toHaveBeenCalledTimes(10);
    expect(wait).toHaveBeenCalledTimes(9);
    expect(states.at(-1)).toBe("unavailable");
  });

  it("does not poll again after an immediately healthy response", async () => {
    const check = vi.fn().mockResolvedValue({ status: "ok" });
    const wait = vi.fn().mockResolvedValue(undefined);
    const states: ApiHealthState[] = [];

    await monitorBackendHealth({
      signal: new AbortController().signal,
      onStateChange: (state) => states.push(state),
      check,
      wait,
    });

    expect(check).toHaveBeenCalledTimes(1);
    expect(wait).not.toHaveBeenCalled();
    expect(states).toEqual(["operational"]);
  });
});
