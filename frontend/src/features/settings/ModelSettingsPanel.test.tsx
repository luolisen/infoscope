import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../api/modelSettings", async (importOriginal) => {
  const original = await importOriginal<typeof import("../../api/modelSettings")>();
  return {
    ...original,
    fetchModelSettings: vi.fn(),
    updateModelSettings: vi.fn(),
  };
});

import { fetchModelSettings, updateModelSettings } from "../../api/modelSettings";
import { ModelSettingsPanel } from "./ModelSettingsPanel";

const response = {
  selection: { source_id: "deepseek_official" as const, model_id: "deepseek-v4-flash" as const },
  sources: [
    {
      id: "deepseek_official" as const,
      label: "Deepseek官方",
      available: true,
      models: [
        { id: "deepseek-v4-pro" as const, label: "Pro", available: true },
        { id: "deepseek-v4-flash" as const, label: "Flash", available: true },
      ],
    },
    {
      id: "gpt_5_5" as const,
      label: "GPT-5.5",
      available: false,
      models: [{ id: "gpt-5.5" as const, label: "GPT-5.5", available: false }],
    },
    {
      id: "ai_ping" as const,
      label: "AI Ping",
      available: true,
      models: [
        { id: "DeepSeek-V4-Flash-0731" as const, label: "DeepSeek V4 Flash 0731", available: true },
        { id: "Kimi-K3" as const, label: "Kimi K3", available: true },
        { id: "Qwen3.8-Max" as const, label: "Qwen 3.8 Max", available: true },
      ],
    },
  ],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}><ModelSettingsPanel /></QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("ModelSettingsPanel", () => {
  it("renders provider and model as two levels and saves only stable identifiers", async () => {
    vi.mocked(fetchModelSettings).mockResolvedValue(response);
    vi.mocked(updateModelSettings).mockImplementation(async (selection) => ({
      ...response,
      selection,
    }));
    renderPanel();

    expect(await screen.findByRole("radio", { name: /Deepseek官方/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /^Flash/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /GPT-5.5/ })).toBeDisabled();

    fireEvent.click(screen.getByRole("radio", { name: /AI Ping/ }));
    expect(screen.getByRole("radio", { name: /DeepSeek V4 Flash 0731/ })).toBeChecked();
    fireEvent.click(screen.getByRole("radio", { name: /Qwen 3.8 Max/ }));
    fireEvent.click(screen.getByRole("button", { name: "保存模型" }));

    await waitFor(() => expect(vi.mocked(updateModelSettings).mock.calls[0]?.[0]).toEqual({
      source_id: "ai_ping",
      model_id: "Qwen3.8-Max",
    }));
    expect(await screen.findByText("模型偏好已保存。")).toBeInTheDocument();
  });

  it("shows loading and fail-closed load errors", async () => {
    vi.mocked(fetchModelSettings).mockImplementation(() => new Promise(() => undefined));
    const view = renderPanel();
    expect(screen.getByText("正在加载模型设置…")).toBeInTheDocument();

    view.unmount();
    vi.mocked(fetchModelSettings).mockRejectedValue(new Error("offline"));
    renderPanel();
    expect(await screen.findByRole("alert")).toHaveTextContent("无法加载模型设置");
  });
});
