import { apiClient } from "./client";

export const maintenanceStatusQueryKey = ["maintenance", "status"] as const;
export const maintenanceRunQueryKey = (runId: string) => ["maintenance", "runs", runId] as const;

export async function fetchMaintenanceStatus() {
  const { data, error } = await apiClient.GET("/api/v1/maintenance/status");

  if (error !== undefined || data === undefined) {
    throw new Error("Maintenance status is unavailable.");
  }

  return data;
}

export async function createMaintenanceRun() {
  const { data, error } = await apiClient.POST("/api/v1/maintenance/runs");

  if (error !== undefined || data === undefined) {
    throw new Error("Maintenance run could not be created.");
  }

  return data;
}

export async function fetchMaintenanceRun(runId: string) {
  const { data, error } = await apiClient.GET("/api/v1/maintenance/runs/{run_id}", {
    params: { path: { run_id: runId } },
  });

  if (error !== undefined || data === undefined) {
    throw new Error("Maintenance run is unavailable.");
  }

  return data;
}
