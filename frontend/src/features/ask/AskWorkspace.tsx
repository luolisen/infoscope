import { useQuery } from "@tanstack/react-query";

import { fetchNow, nowQueryKey } from "../../api/now";
import { AskPanel } from "./AskPanel";
import { AskHistoryPanel } from "./AskHistoryPanel";

type EventSelection = { id: string; title: string };

type AskWorkspaceProps = {
  selectedEvents: EventSelection[];
  onClearSelection: () => void;
  onToggleEventSelection: (event: EventSelection) => void;
};

export function AskWorkspace({ selectedEvents, onClearSelection, onToggleEventSelection }: AskWorkspaceProps) {
  const now = useQuery({ queryKey: nowQueryKey, queryFn: fetchNow });

  return (
    <main className="main-content ask-workspace" aria-labelledby="ask-workspace-heading">
      <AskHistoryPanel />
      <header className="ask-workspace__hero">
        <p className="editorial-label">ASK</p>
        <h1 id="ask-workspace-heading">观澜能帮忙做什么</h1>
        <p>选择一个或多个 Event，再提出你想理解的问题。</p>
      </header>
      <section className="ask-event-picker" aria-labelledby="ask-events-heading">
        <p className="ask-event-picker__rule" aria-hidden="true" />
        <h2 id="ask-events-heading">Event 列表</h2>
        {now.isPending && <p role="status">正在加载 Event…</p>}
        {now.isError && <p className="auth-error" role="alert">无法加载 Event 列表，请稍后重试。</p>}
        {now.data?.items.length === 0 && <p className="detail-empty">当前没有可选择的 Event。</p>}
        {now.data?.items.map((event) => {
          const selected = selectedEvents.some((item) => item.id === event.id);
          return (
            <label className={`ask-event-option${selected ? " ask-event-option--selected" : ""}`} key={event.id}>
              <span>{event.title}</span>
              <input aria-label={`选择 ${event.title}`} checked={selected} disabled={!selected && selectedEvents.length === 8} onChange={() => onToggleEventSelection({ id: event.id, title: event.title })} type="checkbox" />
            </label>
          );
        })}
      </section>
      <AskPanel onClearSelection={onClearSelection} selectedEvents={selectedEvents} workspace />
    </main>
  );
}
