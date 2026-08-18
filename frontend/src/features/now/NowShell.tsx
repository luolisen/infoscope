import { useQuery } from "@tanstack/react-query";
import { fetchNow, nowQueryKey } from "../../api/now";
import { SaveButton } from "../events/SaveButton";

type NowShellProps = {
  selectedEvents: { id: string; title: string }[];
  onToggleEventSelection: (event: { id: string; title: string }) => void;
};

function formatTime(value: string) {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(value));
}

export function NowShell({ selectedEvents, onToggleEventSelection }: NowShellProps) {
  const now = useQuery({ queryKey: nowQueryKey, queryFn: fetchNow });
  if (now.isPending) return <main className="main-content"><p className="editorial-label">NOW / 加载中</p><p>正在整理当前信息窗口…</p></main>;
  if (now.isError) return <main className="main-content"><p className="editorial-label">NOW / 不可用</p><p role="alert">无法加载 NOW，请稍后重试。</p></main>;
  const { items, window_stats } = now.data;
  return <main className="main-content" id="now">
    <p className="editorial-label">NOW</p>
    <header className="now-header"><h1>此刻，什么值得关注。</h1><p>{window_stats.raw_information_count} 条信息，整理为 {window_stats.event_count} 个事件。</p></header>
    {items.length === 0 ? <section className="now-empty"><p className="editorial-label">WINDOW / 空</p><h2>暂时没有需要关注的内容。</h2><p>新的相关信息出现后，会在这里呈现。</p></section> : <section className="event-list" aria-label="当前事件">{items.map((event) => <article className="event-item" key={event.id}><div className="event-item__heading"><p className="editorial-label">EVENT / {event.state}</p><label><input aria-label={`选择 ${event.title}`} checked={selectedEvents.some((selected) => selected.id === event.id)} disabled={!selectedEvents.some((selected) => selected.id === event.id) && selectedEvents.length === 8} onChange={() => onToggleEventSelection({ id: event.id, title: event.title })} type="checkbox" /> 对比</label></div><h2><a href={`#event/${event.id}`}>{event.title}</a></h2><p>{event.overview}</p><p className="event-meta">{formatTime(event.display_time)} · {event.new_claim_count} 条新主张 · {event.conflict_count} 个冲突</p><p className="event-why"><span className="editorial-label">为什么值得关注</span>{event.why_it_matters}</p><SaveButton eventId={event.id} saved={event.saved} /></article>)}</section>}
    <p className="window-meta">窗口结束于 {formatTime(window_stats.window_ended_at)} · {window_stats.relevant_event_count} 个相关事件</p>
  </main>;
}
