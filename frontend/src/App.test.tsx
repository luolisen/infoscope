import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/health", () => ({ fetchHealth: vi.fn() }));

import { App } from "./App";
import { fetchHealth } from "./api/health";

afterEach(() => vi.clearAllMocks());

function renderApp() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={queryClient}><App /></QueryClientProvider>);
}

describe("App", () => {
  it("shows the editorial app shell and health success state", async () => {
    vi.mocked(fetchHealth).mockResolvedValue({
      status: "ok", api: "ok", database: "ok", worker: "ok",
    });

    renderApp();

    expect(screen.getByRole("heading", { name: /see the event/i })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "NOW" })).toHaveAttribute("aria-current", "page");
    expect(await screen.findByText(/API, database, and worker are operational/i)).toBeInTheDocument();
  });
});
