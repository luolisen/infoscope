import { apiClient } from "./client";

export const nowQueryKey = ["now"] as const;

export async function fetchNow() {
  const { data, error } = await apiClient.GET("/api/v1/now");
  if (error !== undefined || data === undefined) throw new Error("NOW is unavailable.");
  return data;
}
