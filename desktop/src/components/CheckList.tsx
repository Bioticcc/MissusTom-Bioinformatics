import type { PreflightCheck } from "../types";
import { StatusBadge } from "./StatusBadge";

export function CheckList({ checks }: { checks: PreflightCheck[] }) {
  if (checks.length === 0) {
    return <p className="empty-copy">Run validation to see checks.</p>;
  }
  return (
    <div className="check-list">
      {checks.map((check) => (
        <article className="check-row" key={check.check_id}>
          <div>
            <h4>{check.label}</h4>
            <p>{check.message}</p>
          </div>
          <StatusBadge status={check.status} />
        </article>
      ))}
    </div>
  );
}

