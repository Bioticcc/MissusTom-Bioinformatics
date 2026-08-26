import type { CheckStatus } from "../types";

const labels: Record<CheckStatus, string> = {
  passed: "Passed",
  warning: "Warning",
  blocking_failure: "Blocking",
  not_yet_configured: "Not configured",
};

export function StatusBadge({ status }: { status: CheckStatus }) {
  return <span className={`status-badge status-${status}`}>{labels[status]}</span>;
}

