import { apiClient } from "./client";
import type { components } from "./schema";

export type ModelSelection = components["schemas"]["ModelSelection"];

export const modelSettingsQueryKey = ["settings", "models"] as const;

export async function fetchModelSettings() {
  const { data, error } = await apiClient.GET("/api/v1/settings/models");
  if (error !== undefined || data === undefined) {
    throw new Error("Model settings are unavailable.");
  }
  return data;
}

export async function updateModelSettings(selection: ModelSelection) {
  const { data, error } = await apiClient.PUT("/api/v1/settings/models", {
    body: selection,
  });
  if (error !== undefined || data === undefined) {
    throw new Error("Model settings could not be saved.");
  }
  return data;
}
