import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/maintenance", () => ({
  createMaintenanceRun: vi.fn(),
  fetchMaintenanceRun: vi.fn(),
  fetchMaintenanceStatus: vi.fn(),
  maintenanceRunQueryKey: (runId: string) => ["maintenance", "runs", runId],
  maintenanceStatusQueryKey: ["maintenance", "status"],
}));

import { createMaintenanceRun, fetchMaintenanceRun, fetchMaintenanceStatus } from "../../api/maintenance";
import { MaintenancePanel } from "./MaintenancePanel";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderPanel() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><MaintenancePanel /></QueryClientProvider>);
}

describe("MaintenancePanel", () => {
  it("renders the backend-provided idle schedule without calculating one", async () => {
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({
      status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: "2026-08-16T08:00:00Z", next_cycle_at: "2026-08-16T09:00:00Z",
    });

    renderPanel();

    expect(await screen.findByText("No maintenance cycle is active.")).toBeInTheDocument();
    expect(screen.getByText("2026-08-16T09:00:00Z")).toBeInTheDocument();
  });

  it("shows loading and error states for the maintenance status", async () => {
    vi.mocked(fetchMaintenanceStatus).mockImplementation(() => new Promise(() => undefined));
    const view = renderPanel();
    expect(screen.getByText("Loading maintenance status…")).toBeInTheDocument();

    view.unmount();
    vi.mocked(fetchMaintenanceStatus).mockRejectedValue(new Error("network unavailable"));
    renderPanel();
    expect(await screen.findByText(/could not load maintenance status/i)).toBeInTheDocument();
  });

  it("starts a run and polls its generated run identifier", async () => {
    vi.mocked(fetchMaintenanceStatus).mockResolvedValue({ status: "idle", phase: null, cycle_started_at: null, cycle_finished_at: null, next_cycle_at: null });
    vi.mocked(createMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "pending" });
    vi.mocked(fetchMaintenanceRun).mockResolvedValue({ run_id: "run-1", status: "running", phase: "event_backwrite", started_at: "2026-08-16T08:00:00Z", finished_at: null });

    renderPanel();
    await screen.findByText("No maintenance cycle is active.");
    fireEvent.click(screen.getByRole("button", { name: "Start maintenance" }));

    expect(await screen.findByText("Run running / event_backwrite.")).toBeInTheDocument();
    expect(fetchMaintenanceRun).toHaveBeenCalledWith("run-1");
    expect(screen.getByRole("button", { name: "Maintenance in progress" })).toBeDisabled();
  });
});
