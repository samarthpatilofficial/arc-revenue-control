import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./app/AppShell";
import { ApprovalsPage } from "./features/approvals/ApprovalsPage";
import { AuditPage } from "./features/audit/AuditPage";
import { CaseDetailPage } from "./features/cases/CaseDetailPage";
import { CasesPage } from "./features/cases/CasesPage";
import { OverviewPage } from "./features/overview/OverviewPage";
import { RecoveryActionsPage } from "./features/recovery-actions/RecoveryActionsPage";

export default function App() {
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route index element={<Navigate replace to="/overview" />} />
        <Route path="overview" element={<OverviewPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:caseReference" element={<CaseDetailPage />} />
        <Route path="approvals" element={<ApprovalsPage />} />
        <Route path="recovery-actions" element={<RecoveryActionsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="*" element={<Navigate replace to="/overview" />} />
      </Route>
    </Routes>
  );
}
