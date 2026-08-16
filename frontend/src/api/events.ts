import { apiClient } from "./client";

export const eventDetailQueryKey = (eventId: string) => ["events", eventId] as const;

export async function fetchEventDetail(eventId: string) {
  const { data, error } = await apiClient.GET("/api/v1/events/{event_id}", {
    params: { path: { event_id: eventId } },
  });

  if (error !== undefined || data === undefined) {
    throw new Error("Event detail is unavailable.");
  }

  return data;
}
