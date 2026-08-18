import { apiClient } from "./client";

export const askQueryKey = (askId: string) => ["ask", askId] as const;
export const askHistoryQueryKey = ["ask", "history"] as const;

export async function createAsk(eventIds: string[], question: string) {
  const { data, error } = await apiClient.POST("/api/v1/ask", {
    body: { event_ids: eventIds, question },
  });

  if (error !== undefined || data === undefined) {
    throw new Error("Ask could not be created.");
  }

  return data;
}

export async function fetchAsk(askId: string) {
  const { data, error } = await apiClient.GET("/api/v1/ask/{ask_id}", {
    params: { path: { ask_id: askId } },
  });

  if (error !== undefined || data === undefined) {
    throw new Error("Ask status is unavailable.");
  }

  return data;
}

export async function fetchAskHistory(limit = 20, cursor?: string) {
  const { data, error } = await apiClient.GET("/api/v1/ask/history", {
    params: { query: { limit, cursor } },
  });
  if (error) throw error;
  return data;
}
