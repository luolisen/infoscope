import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/events", () => ({
  eventDetailQueryKey: (eventId: string) => ["events", eventId],
  fetchEventDetail: vi.fn(),
}));

import { fetchEventDetail } from "../../api/events";
import { EventDetail } from "./EventDetail";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderDetail() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><EventDetail eventId="event-1" onBack={() => undefined} /></QueryClientProvider>);
}

describe("EventDetail", () => {
  it("renders API ordering and never invents private source attribution", async () => {
    vi.mocked(fetchEventDetail).mockResolvedValue({
      id: "event-1",
      title: "Event title",
      overview: "Current overview",
      state: "developing",
      display_time: "2026-08-16T00:00:00Z",
      updated_at: "2026-08-16T01:00:00Z",
      base_analysis: { summary: "Analysis", event_type: "technology", importance: "medium", topics: ["AI"], entities: [] },
      why_it_matters: "Context",
      topics: ["AI"],
      saved: false,
      claims: [{ id: "claim-1", text: "First claim", state: "unresolved", evidence_ids: ["evidence-private"] }],
      timeline: [{ id: "timeline-1", occurred_at: "2026-08-15T00:00:00Z", summary: "First timeline entry", claim_ids: ["claim-1"] }],
      conflicts: [],
      evidence: [{ id: "evidence-private", platform: "telegram", visibility: "private_sanitized", author_name: null, url: null, published_at: null, excerpt: "Sanitized private text" }],
    });

    renderDetail();

    expect(await screen.findByRole("heading", { name: "Event title" })).toBeInTheDocument();
    expect(screen.getByText("First timeline entry")).toBeInTheDocument();
    expect(screen.getByText("Sanitized private text")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /open public source/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/telegram\.me|invite|username/i)).not.toBeInTheDocument();
  });
});
