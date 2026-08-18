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
    <section className="maintenance-panel" aria-labelledby="maintenance-heading">
      <p className="editorial-label">MAINTENANCE</p>
      <h1 id="maintenance-heading">保持事实层最新。</h1>
      <p className="maintenance-intro">Maintenance 在后台分析当前事实层。本页面跟随服务器管理的周期，不在前端计算调度。</p>

      {status.isPending && <p className="maintenance-state" role="status">正在加载 Maintenance 状态…</p>}
      {status.isError && <p className="auth-error" role="alert">无法加载 Maintenance 状态，请刷新后重试。</p>}
      {status.data !== undefined && (
        <section className="maintenance-status" aria-label="Maintenance status">
          <p className="editorial-label">STATUS / {status.data.status.toUpperCase()}</p>
          {status.data.status === "idle" && <p>当前没有运行中的 Maintenance 周期。</p>}
          {status.data.status === "running" && <p role="status">Maintenance 正在运行{status.data.phase === null ? "" : `：${status.data.phase}`}。</p>}
          {status.data.status === "failed" && <p role="alert">最近一次 Maintenance 失败，可以开始新的周期。</p>}
          <dl>
            <div><dt>下次周期</dt><dd>{status.data.next_cycle_at ?? "未安排"}</dd></div>
            <div><dt>当前阶段</dt><dd>{status.data.phase ?? "—"}</dd></div>
          </dl>
        </section>
      )}

      <button className="auth-submit maintenance-start" disabled={!canStart} onClick={() => create.mutate()} type="button">
        {create.isPending ? "启动中…" : runIsActive ? "Maintenance 处理中" : "开始 Maintenance"}
      </button>
      {create.isError && <p className="auth-error" role="alert">无法开始 Maintenance，请稍后重试。</p>}
      {runId !== null && run.isPending && <p className="maintenance-state" role="status">正在等待 Maintenance 周期…</p>}
      {runId !== null && run.isError && <><p className="auth-error" role="alert">无法检查该 Maintenance 周期，请稍后重试。</p><button className="text-button" onClick={() => { void run.refetch(); }} type="button">重试状态检查</button></>}
      {runId !== null && run.data !== undefined && <p className="maintenance-state" role="status">周期状态：{run.data.status}{run.data.phase === null ? "" : ` / ${run.data.phase}`}。</p>}
    </section>
  );
}
