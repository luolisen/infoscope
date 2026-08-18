import { useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";

import { fetchNow, nowQueryKey } from "../../api/now";

type EventSelection = { id: string; title: string };

type AskEventSidebarProps = {
  selectedEvents: EventSelection[];
  onToggleEventSelection: (event: EventSelection) => void;
};

export function AskEventSidebar({ selectedEvents, onToggleEventSelection }: AskEventSidebarProps) {
  const now = useQuery({ queryKey: nowQueryKey, queryFn: fetchNow });

  return (
    <section className="ask-event-sidebar" aria-labelledby="ask-events-heading">
      <h2 id="ask-events-heading">Event 列表</h2>
      <div className="ask-event-sidebar__items">
        {now.isPending && <p role="status">正在加载 Event…</p>}
        {now.isError && <p className="auth-error" role="alert">无法加载 Event 列表。</p>}
        {now.data?.items.length === 0 && <p className="detail-empty">当前没有可选择的 Event。</p>}
        {now.data?.items.map((event, index) => {
          const selected = selectedEvents.some((item) => item.id === event.id);
          const atLimit = !selected && selectedEvents.length === 8;
          return (
            <label
              className={`ask-event-option${selected ? " ask-event-option--selected" : ""}`}
              key={event.id}
              style={{ "--ask-row-index": Math.min(index, 6) } as CSSProperties}
              title={atLimit ? "最多选择 8 个 Event" : undefined}
            >
              <span>{event.title}</span>
              <input
                aria-label={`选择 ${event.title}`}
                checked={selected}
                disabled={atLimit}
                onChange={() => onToggleEventSelection({ id: event.id, title: event.title })}
                type="checkbox"
              />
            </label>
          );
        })}
      </div>
      {selectedEvents.length === 8 && <p className="ask-event-sidebar__limit" role="status">已选择上限 8 个 Event。</p>}
    </section>
  );
}
