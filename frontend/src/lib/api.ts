import type {
  ApprovalQueueItem,
  CaseDetail,
  CaseFilters,
  CaseListItem,
  DashboardSummary,
  RecoveryActionItem,
  TimelineItem,
} from "../types/api";

const configuredBaseUrl = import.meta.env.VITE_ARC_API_BASE_URL?.trim();
export const API_BASE_URL = (configuredBaseUrl || "http://localhost:8000").replace(
  /\/$/,
  "",
);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code = "API_ERROR") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: signal ?? null,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError("Unable to reach the ARC API", 0, "NETWORK_ERROR");
  }

  if (!response.ok) {
    let message = "Unable to load recovery data";
    let code = "API_ERROR";
    try {
      const payload = (await response.json()) as {
        detail?: { code?: string; message?: string };
      };
      message = payload.detail?.message || message;
      code = payload.detail?.code || code;
    } catch {
      // The UI deliberately ignores non-contract backend response bodies.
    }
    throw new ApiError(message, response.status, code);
  }
  return (await response.json()) as T;
}

export function getDashboardSummary(signal?: AbortSignal): Promise<DashboardSummary> {
  return getJson("/api/v1/dashboard/summary?provider_mode=TEST&currency=INR", signal);
}

export function getCases(
  filters: CaseFilters = {},
  signal?: AbortSignal,
): Promise<CaseListItem[]> {
  const query = new URLSearchParams();
  if (filters.state) query.set("state", filters.state);
  if (filters.failureCategory) query.set("failure_category", filters.failureCategory);
  if (filters.providerMode) query.set("provider_mode", filters.providerMode);
  query.set("limit", String(filters.limit ?? 50));
  query.set("offset", String(filters.offset ?? 0));
  return getJson(`/api/v1/cases?${query.toString()}`, signal);
}

export function getCaseDetail(
  caseReference: string,
  signal?: AbortSignal,
): Promise<CaseDetail> {
  return getJson(`/api/v1/cases/${encodeURIComponent(caseReference)}`, signal);
}

export function getCaseTimeline(
  caseReference: string,
  signal?: AbortSignal,
): Promise<TimelineItem[]> {
  return getJson(
    `/api/v1/cases/${encodeURIComponent(caseReference)}/timeline`,
    signal,
  );
}

export function getApprovals(signal?: AbortSignal): Promise<ApprovalQueueItem[]> {
  return getJson("/api/v1/approvals?status=PENDING", signal);
}

export function getRecoveryActions(
  signal?: AbortSignal,
): Promise<RecoveryActionItem[]> {
  return getJson("/api/v1/recovery-actions", signal);
}
