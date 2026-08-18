import { useState, type CSSProperties } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchNow, nowQueryKey } from "../../api/now";
import { formatEventState, formatUtcDateTime } from "../../formatters";
import { SaveButton } from "../events/SaveButton";

type NowShellProps = {
  selectedEvents: { id: string; title: string }[];
  onToggleEventSelection: (event: { id: string; title: string }) => void;
};

const stateFilters = [
  { label: "全部", value: "all" },
  { label: "发展中", value: "developing" },
  { label: "已确认", value: "confirmed" },
  { label: "存在冲突", value: "conflicting" },
  { label: "降温中", value: "cooling" },
] as const;

type StateFilter = (typeof stateFilters)[number]["value"];

export function NowShell({ selectedEvents, onToggleEventSelection }: NowShellProps) {
  const [stateFilter, setStateFilter] = useState<StateFilter>("all");
  const now = useQuery({ queryKey: nowQueryKey, queryFn: fetchNow });
  if (now.isPending) return <main className="main-content"><p className="editorial-label">NOW / 加载中</p><p>正在整理当前信息窗口…</p></main>;
  if (now.isError) return <main className="main-content"><p className="editorial-label">NOW / 不可用</p><p role="alert">无法加载 NOW，请稍后重试。</p></main>;
  const { items, window_stats } = now.data;
  const visibleItems = stateFilter === "all" ? items : items.filter((event) => event.state === stateFilter);
  const activeFilterIndex = stateFilters.findIndex((filter) => filter.value === stateFilter);
  return <main className="main-content" id="now">
    <p className="editorial-label">NOW</p>
    <header className="now-header"><h1>此刻，什么值得关注。</h1><p>本轮新增 Raw {window_stats.raw_information_count} 条 · 因子 {window_stats.signal_count} 个 · 当前 Event {window_stats.relevant_event_count} 个</p></header>
    {items.length > 0 && <div aria-label="按 Event 状态筛选" className="now-state-filter" role="toolbar" style={{ "--state-filter-index": activeFilterIndex } as CSSProperties}>
      <span aria-hidden="true" className="now-state-filter__indicator" />
      {stateFilters.map((filter) => <button aria-pressed={filter.value === stateFilter} key={filter.value} onClick={() => setStateFilter(filter.value)} type="button">{filter.label}</button>)}
    </div>}
    {items.length === 0 ? <section className="now-empty"><p className="editorial-label">WINDOW / 空</p><h2>暂时没有需要关注的内容。</h2><p>新的相关信息出现后，会在这里呈现。</p></section> : visibleItems.length === 0 ? <section className="now-filter-empty" role="status"><p>当前没有“{stateFilters[activeFilterIndex].label}”的 Event。</p></section> : <section className="event-list event-list--filtered" key={stateFilter} aria-label="当前事件">{visibleItems.map((event) => <article className="event-item" key={event.id}><div className="event-item__heading"><p className="editorial-label">EVENT / {formatEventState(event.state)}</p><label><input aria-label={`选择 ${event.title}`} checked={selectedEvents.some((selected) => selected.id === event.id)} disabled={!selectedEvents.some((selected) => selected.id === event.id) && selectedEvents.length === 8} onChange={() => onToggleEventSelection({ id: event.id, title: event.title })} type="checkbox" /> 对比</label></div><h2><a href={`#event/${event.id}`}>{event.title}</a></h2><p>{event.overview}</p><p className="event-meta">{formatUtcDateTime(event.display_time)} · {event.new_claim_count} 条新主张 · {event.conflict_count} 个冲突</p><p className="event-why"><span className="editorial-label">为什么值得关注</span>{event.why_it_matters}</p><SaveButton eventId={event.id} saved={event.saved} /></article>)}</section>}
    <p className="window-meta">窗口结束于 {formatUtcDateTime(window_stats.window_ended_at)} · {window_stats.relevant_event_count} 个相关事件</p>
  </main>;
}
