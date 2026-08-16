import { apiClient } from "./client";

export const archiveQueryKey = (cursor: string | null) => ["archive", cursor] as const;
export const searchQueryKey = (query: string, cursor: string | null) => ["search", "events", query, cursor] as const;

export async function fetchArchive(cursor: string | null) {
  const { data, error } = await apiClient.GET("/api/v1/archive", { params: { query: cursor === null ? {} : { cursor } } });
  if (error !== undefined || data === undefined) throw new Error("Archive is unavailable.");
  return data;
}

export async function searchEvents(query: string, cursor: string | null) {
  const { data, error } = await apiClient.GET("/api/v1/search/events", { params: { query: cursor === null ? { q: query } : { q: query, cursor } } });
  if (error !== undefined || data === undefined) throw new Error("Search is unavailable.");
  return data;
}

export async function setEventSaved(eventId: string, saved: boolean) {
  const { data, error } = await apiClient.PUT("/api/v1/events/{event_id}/saved", {
    params: { path: { event_id: eventId } },
    body: { saved },
  });
  if (error !== undefined || data === undefined) throw new Error("Saved state could not be updated.");
  return data;
}
