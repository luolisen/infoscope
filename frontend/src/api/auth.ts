import type { components } from "./schema";
import { apiClient } from "./client";

type Credentials = components["schemas"]["CredentialsRequest"];

export class AuthenticationError extends Error {
  constructor(public readonly code: string | undefined) {
    super("Authentication request failed.");
  }
}

export async function login(credentials: Credentials) {
  const response = await apiClient.POST("/api/v1/auth/login", { body: credentials });

  if (response.error !== undefined || response.data === undefined) {
    throw new AuthenticationError(response.error?.error.code);
  }

  return response.data;
}

export async function register(credentials: Credentials) {
  const response = await apiClient.POST("/api/v1/auth/register", { body: credentials });

  if (response.error !== undefined || response.data === undefined) {
    throw new AuthenticationError(response.error?.error.code);
  }

  return response.data;
}
