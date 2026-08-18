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
      <div className="ask-event-sidebar__header">
        <h2 id="ask-events-heading">Event 列表</h2>
        <p aria-live="polite" className="ask-event-sidebar__count">
          <span className="visually-hidden">已选择 </span>
          {selectedEvents.length} / 8
        </p>
      </div>
      <div className="ask-event-sidebar__items">
        {now.isPending && (
          <div aria-label="正在加载 Event" className="ask-event-sidebar__loading" role="status">
            <span />
            <span />
            <span />
          </div>
        )}
        {now.isError && <p className="auth-error ask-event-sidebar__state" role="alert">无法加载 Event 列表 · 重试</p>}
        {now.data?.items.length === 0 && <p className="detail-empty">当前没有可选择的 Event。</p>}
        {now.data?.items.map((event, index) => {
          const selectedIndex = selectedEvents.findIndex((item) => item.id === event.id);
          const selected = selectedIndex !== -1;
          const atLimit = !selected && selectedEvents.length === 8;
          return (
            <label
              className={`ask-event-option${selected ? " ask-event-option--selected" : ""}`}
              key={event.id}
              style={{ "--ask-row-index": Math.min(index, 6) } as CSSProperties}
              title={atLimit ? "最多选择 8 个 Event" : undefined}
            >
              <span className="ask-event-option__title">{event.title}</span>
              <span aria-hidden="true" className="ask-event-option__order">
                {selected ? String(selectedIndex + 1).padStart(2, "0") : ""}
              </span>
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
      {selectedEvents.length === 8 && <p className="ask-event-sidebar__limit" role="status">已选满 8 个 · 取消一项后可继续</p>}
    </section>
  );
}
