import type { components } from "./schema";
import { apiClient } from "./client";

type LocalAccess = components["schemas"]["LocalAccessRequest"];

export class AuthenticationError extends Error {
  constructor(public readonly code: string | undefined) {
    super("Authentication request failed.");
  }
}

export async function accessLocal(request: LocalAccess) {
  const response = await apiClient.POST("/api/v1/auth/local", { body: request });

  if (response.error !== undefined || response.data === undefined) {
    throw new AuthenticationError(response.error?.error.code);
  }

  return response.data;
}
