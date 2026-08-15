import { apiClient } from "./client";

export async function fetchHealth() {
  const { data, error } = await apiClient.GET("/api/v1/health");

  if (error !== undefined || data === undefined) {
    throw new Error("Health check is unavailable.");
  }

  return data;
}
