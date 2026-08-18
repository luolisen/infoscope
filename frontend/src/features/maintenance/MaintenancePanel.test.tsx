import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/maintenance", () => ({
  createMaintenanceRun: vi.fn(),
  fetchMaintenanceRun: vi.fn(),
  fetchMaintenanceStatus: vi.fn(),
  maintenanceRunQueryKey: (runId: string) => ["maintenance", "runs", runId],
  maintenanceStatusQueryKey: ["maintenance", "status"],
}));

import { createMaintenanceRun, fetchMaintenanceRun, fetchMaintenanceStatus } from "../../api/maintenance";
import type { components } from "../../api/schema";
import { MaintenancePanel } from "./MaintenancePanel";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return { queryClient, view: render(<QueryClientProvider client={queryClient}><MaintenancePanel /></QueryClientProvider>) };
}

describe("MaintenancePanel", () => {
  it("renders the backend-provided idle schedule without calculating one", async () => {
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({
      status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: "2026-08-16T08:00:00Z", next_cycle_at: "2026-08-16T09:00:00Z",
    });

    renderPanel();

    expect(await screen.findByText("当前没有运行中的 Maintenance 周期。")).toBeInTheDocument();
    expect(screen.getByText("2026-08-16T09:00:00Z")).toBeInTheDocument();
  });

  it("shows loading and error states for the maintenance status", async () => {
    vi.mocked(fetchMaintenanceStatus).mockImplementation(() => new Promise(() => undefined));
    const { view } = renderPanel();
    expect(screen.getByText("正在加载 Maintenance 状态…")).toBeInTheDocument();

    view.unmount();
    vi.mocked(fetchMaintenanceStatus).mockRejectedValue(new Error("network unavailable"));
    renderPanel();
    expect(await screen.findByText(/无法加载 Maintenance 状态/)).toBeInTheDocument();
  });

  it("starts a run and polls its generated run identifier", async () => {
    vi.mocked(fetchMaintenanceStatus)
      .mockResolvedValueOnce({ status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null })
      .mockResolvedValueOnce({ status: "failed", phase: null, cycle_started_at: "2026-08-16T08:00:00Z", cycle_finished_at: "2026-08-16T08:10:00Z", next_cycle_at: "2026-08-16T09:10:00Z" });
    vi.mocked(createMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "pending" });
    vi.mocked(fetchMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "running", phase: "event_backwrite", started_at: "2026-08-16T08:00:00Z", finished_at: null });

    renderPanel();
    await screen.findByText("当前没有运行中的 Maintenance 周期。");
    fireEvent.click(screen.getByRole("button", { name: "开始 Maintenance" }));

    expect(await screen.findByText("周期状态：running / event_backwrite。")).toBeInTheDocument();
    expect(fetchMaintenanceRun).toHaveBeenCalledWith("run-1");
    expect(screen.getByRole("button", { name: "Maintenance 处理中" })).toBeDisabled();
  });

  it("refreshes the backend status after a terminal run", async () => {
    const currentStatus: components["schemas"]["MaintenanceStatusResponse"] = { status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null };
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue(currentStatus);
    vi.mocked(createMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "pending" });
    vi.mocked(fetchMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "completed", phase: null, started_at: "2026-08-16T08:00:00Z", finished_at: "2026-08-16T08:10:00Z" });
    const { queryClient } = renderPanel();
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");

    await screen.findByText("当前没有运行中的 Maintenance 周期。");
    fireEvent.click(screen.getByRole("button", { name: "开始 Maintenance" }));

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: ["maintenance", "status"] }));
    expect(fetchMaintenanceStatus).toHaveBeenCalledTimes(2);
  });
});
