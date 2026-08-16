import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  createMaintenanceRun,
  fetchMaintenanceRun,
  fetchMaintenanceStatus,
  maintenanceRunQueryKey,
  maintenanceStatusQueryKey,
} from "../../api/maintenance";

export function MaintenancePanel() {
  const queryClient = useQueryClient();
  const [runId, setRunId] = useState<string | null>(null);
  const refreshedTerminalRunId = useRef<string | null>(null);
  const status = useQuery({
    queryKey: maintenanceStatusQueryKey,
    queryFn: fetchMaintenanceStatus,
    refetchInterval: (query) => query.state.data?.status === "running" ? 3_000 : false,
  });
  const create = useMutation({
    mutationFn: createMaintenanceRun,
    onSuccess: (accepted) => setRunId(accepted.run_id),
  });
  const run = useQuery({
    queryKey: runId === null ? ["maintenance", "runs", "idle"] : maintenanceRunQueryKey(runId),
    queryFn: () => fetchMaintenanceRun(runId!),
    enabled: runId !== null,
    refetchInterval: (query) => query.state.data?.status === "pending" || query.state.data?.status === "running" ? 1_500 : false,
  });

  const terminalRun = run.data?.status === "completed" || run.data?.status === "failed" ? run.data : undefined;
  const runIsTerminal = terminalRun !== undefined;
  const runIsActive = runId !== null && !runIsTerminal;
  const canStart = status.data !== undefined && !create.isPending && !runIsActive && status.data.status !== "running";

  useEffect(() => {
    if (terminalRun === undefined || terminalRun.run_id === refreshedTerminalRunId.current) return;

    void queryClient.invalidateQueries({ queryKey: maintenanceStatusQueryKey });
    refreshedTerminalRunId.current = terminalRun.run_id;
  }, [queryClient, terminalRun]);

  return (
    <main className="main-content maintenance-panel" aria-labelledby="maintenance-heading">
      <p className="editorial-label">MAINTENANCE</p>
      <h1 id="maintenance-heading">Keep the record current.</h1>
      <p className="maintenance-intro">Maintenance runs analyze the current record in the background. This page follows the server-managed cycle; it does not calculate a schedule locally.</p>

      {status.isPending && <p className="maintenance-state" role="status">Loading maintenance status…</p>}
      {status.isError && <p className="auth-error" role="alert">We could not load maintenance status. Please refresh and try again.</p>}
      {status.data !== undefined && (
        <section className="maintenance-status" aria-label="Maintenance status">
          <p className="editorial-label">STATUS / {status.data.status.toUpperCase()}</p>
          {status.data.status === "idle" && <p>No maintenance cycle is active.</p>}
          {status.data.status === "running" && <p role="status">Maintenance is running{status.data.phase === null ? "" : `: ${status.data.phase}`}.</p>}
          {status.data.status === "failed" && <p role="alert">The latest maintenance cycle failed. You can start a new cycle.</p>}
          <dl>
            <div><dt>Next cycle</dt><dd>{status.data.next_cycle_at ?? "Not scheduled"}</dd></div>
            <div><dt>Current phase</dt><dd>{status.data.phase ?? "—"}</dd></div>
          </dl>
        </section>
      )}

      <button className="auth-submit maintenance-start" disabled={!canStart} onClick={() => create.mutate()} type="button">
        {create.isPending ? "Starting maintenance…" : runIsActive ? "Maintenance in progress" : "Start maintenance"}
      </button>
      {create.isError && <p className="auth-error" role="alert">We could not start maintenance. Please try again.</p>}
      {runId !== null && run.isPending && <p className="maintenance-state" role="status">Waiting for the maintenance run…</p>}
      {runId !== null && run.isError && <><p className="auth-error" role="alert">We could not check this maintenance run. Please try again.</p><button className="text-button" onClick={() => { void run.refetch(); }} type="button">Retry status check</button></>}
      {runId !== null && run.data !== undefined && <p className="maintenance-state" role="status">Run {run.data.status}{run.data.phase === null ? "" : ` / ${run.data.phase}`}.</p>}
    </main>
  );
}
