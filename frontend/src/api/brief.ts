import { apiClient } from "./client";

export const briefLatestQueryKey = ["brief", "latest"] as const;

export async function fetchLatestBrief() {
  const { data, error } = await apiClient.GET("/api/v1/brief/latest");

  if (error !== undefined || data === undefined) {
    throw new Error("Brief is unavailable.");
  }

  return data;
}
