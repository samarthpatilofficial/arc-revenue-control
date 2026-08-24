import { useCallback, useState } from "react";
import { CaseTable } from "../../components/CaseTable";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { getCases } from "../../lib/api";
import { displayEnum } from "../../lib/display";
import { useApiResource } from "../../lib/useApiResource";
import type { CaseState, FailureCategory, ProviderMode } from "../../types/api";

const stateOptions: CaseState[] = [
  "DETECTED",
  "RECONCILING",
  "DIAGNOSED",
  "DECISIONED",
  "POLICY_VALIDATED",
  "ACTIONED",
  "WAITING_FOR_OUTCOME",
  "RECOVERED",
  "EXHAUSTED",
  "ESCALATED",
];
const failureOptions: FailureCategory[] = [
  "CUSTOMER_AUTHENTICATION",
  "CUSTOMER_FUNDS",
  "CUSTOMER_INTERRUPTION",
  "CUSTOMER_OR_INSTRUMENT_RESTRICTION",
  "BANK_OR_ISSUER",
  "GATEWAY_OR_NETWORK",
  "MERCHANT_CONFIGURATION",
  "RAZORPAY_OR_PLATFORM",
  "SUBSCRIPTION_RETRY_EXHAUSTED",
  "UNKNOWN",
];

export function CasesPage() {
  const [state, setState] = useState<CaseState | "">("");
  const [failureCategory, setFailureCategory] = useState<FailureCategory | "">("");
  const [providerMode, setProviderMode] = useState<ProviderMode | "">("");
  const loadCases = useCallback(
    (signal: AbortSignal) =>
      getCases(
        {
          ...(state ? { state } : {}),
          ...(failureCategory ? { failureCategory } : {}),
          ...(providerMode ? { providerMode } : {}),
          limit: 100,
        },
        signal,
      ),
    [failureCategory, providerMode, state],
  );
  const resource = useApiResource(loadCases);

  return (
    <>
      <PageHeader
        title="Recovery Cases"
        subtitle="Reconciled revenue risk, decisions, controls, and outcomes."
      />
      <div className="filters" aria-label="Case filters">
        <div className="filter-field">
          <label htmlFor="case-state">State</label>
          <select
            id="case-state"
            value={state}
            onChange={(event) => setState(event.target.value as CaseState | "")}
          >
            <option value="">All states</option>
            {stateOptions.map((value) => (
              <option key={value} value={value}>{displayEnum(value)}</option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="failure-category">Failure category</label>
          <select
            id="failure-category"
            value={failureCategory}
            onChange={(event) => setFailureCategory(event.target.value as FailureCategory | "")}
          >
            <option value="">All categories</option>
            {failureOptions.map((value) => (
              <option key={value} value={value}>{displayEnum(value)}</option>
            ))}
          </select>
        </div>
        <div className="filter-field">
          <label htmlFor="provider-mode">Provider mode</label>
          <select
            id="provider-mode"
            value={providerMode}
            onChange={(event) => setProviderMode(event.target.value as ProviderMode | "")}
          >
            <option value="">All provider modes</option>
            <option value="TEST">Test Mode</option>
            <option value="LIVE">Live Mode</option>
          </select>
        </div>
      </div>

      <SectionCard className="table-card">
        {resource.loading ? (
          <TableSkeleton rows={8} />
        ) : resource.error ? (
          <ErrorState onRetry={resource.retry} />
        ) : resource.data?.length ? (
          <CaseTable cases={resource.data} />
        ) : (
          <EmptyState
            title="No cases match these filters"
            message="Adjust the operational filters to see other recovery cases."
          />
        )}
      </SectionCard>
    </>
  );
}
