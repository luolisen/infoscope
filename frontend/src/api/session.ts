import { apiClient } from "./client";

export const sessionQueryKey = ["session"] as const;

export async function fetchSession() {
  const { data, error } = await apiClient.GET("/api/v1/session");

  if (error !== undefined || data === undefined) {
    throw new Error("Session is unavailable.");
  }

  return data;
}
