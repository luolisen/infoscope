import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/brief", () => ({
  briefLatestQueryKey: ["brief", "latest"],
  fetchLatestBrief: vi.fn(),
}));

import { fetchLatestBrief } from "../../api/brief";
import { BriefPage } from "./BriefPage";

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

function renderBrief() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><BriefPage /></QueryClientProvider>);
}

describe("BriefPage", () => {
  it("renders loading and error states", async () => {
    vi.mocked(fetchLatestBrief).mockImplementation(() => new Promise(() => undefined));
    const view = renderBrief();
    expect(screen.getByText("正在准备 Brief…")).toBeInTheDocument();

    view.unmount();
    vi.mocked(fetchLatestBrief).mockRejectedValue(new Error("network unavailable"));
    renderBrief();
    expect(await screen.findByText(/无法加载 Brief/)).toBeInTheDocument();
  });

  it("treats null generated_at with no items as a legal empty Brief", async () => {
    vi.mocked(fetchLatestBrief).mockResolvedValue({ generated_at: null, items: [] });
    renderBrief();
    expect(await screen.findByRole("heading", { name: /Brief 正在等待/ })).toBeInTheDocument();
  });

  it("treats a generated deterministic-empty Brief as an empty state", async () => {
    vi.mocked(fetchLatestBrief).mockResolvedValue({ generated_at: "2026-08-16T13:05:00Z", items: [] });
    renderBrief();

    expect(await screen.findByRole("heading", { name: /当前 Brief 没有内容/ })).toBeInTheDocument();
    expect(screen.getByText(/生成于 2026年8月16日 13:05/)).toBeInTheDocument();
    expect(screen.queryByText(/2026-08-16T13:05:00Z/)).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Latest Brief")).not.toBeInTheDocument();
  });

  it("renders backend order unchanged and links every item to Event Detail", async () => {
    vi.mocked(fetchLatestBrief).mockResolvedValue({
      generated_at: "2026-08-16T13:05:00Z",
      items: [
        { event_id: "event-2", title: "Second from Backend", summary: "Second summary", why_it_matters: "Second relevance" },
        { event_id: "event-1", title: "First from Backend", summary: "First summary", why_it_matters: "First relevance" },
      ],
    });
    renderBrief();

    expect(await screen.findByText("Second summary")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "当前视野一览" })).toBeInTheDocument();
    const titles = screen.getAllByRole("link").map((link) => link.textContent);
    expect(titles).toEqual(["Second from Backend", "First from Backend"]);
    expect(screen.getByRole("link", { name: "Second from Backend" })).toHaveAttribute("href", "#event/event-2");
    expect(screen.getByText("First relevance")).toBeInTheDocument();
    expect(screen.getByText("生成于 2026年8月16日 13:05")).toBeInTheDocument();
  });
});
