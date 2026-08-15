import type { components } from "./schema";
import { apiClient } from "./client";

export const onboardingQueryKey = ["onboarding"] as const;
type Selection = components["schemas"]["OnboardingSelection"];

export class OnboardingError extends Error {
  constructor(public readonly code: string | undefined) { super("Onboarding request failed."); }
}

export async function fetchOnboarding() {
  const { data, error } = await apiClient.GET("/api/v1/onboarding");
  if (error !== undefined || data === undefined) throw new OnboardingError(error && "error" in error ? error.error.code : undefined);
  return data;
}

export async function updateOnboarding(body: Selection) {
  const { data, error } = await apiClient.PUT("/api/v1/onboarding", { body });
  if (error !== undefined || data === undefined) throw new OnboardingError(error && "error" in error ? error.error.code : undefined);
  return data;
}
