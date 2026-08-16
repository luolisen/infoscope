import { useQuery } from "@tanstack/react-query";
import { fetchNow, nowQueryKey } from "../../api/now";
import { SaveButton } from "../events/SaveButton";

type NowShellProps = {
  selectedEvents: { id: string; title: string }[];
  onToggleEventSelection: (event: { id: string; title: string }) => void;
};

export function NowShell({ selectedEvents, onToggleEventSelection }: NowShellProps) {
  const now = useQuery({ queryKey: nowQueryKey, queryFn: fetchNow });
  if (now.isPending) return <main className="main-content"><p className="editorial-label">NOW / LOADING</p><p>Organizing the current information window…</p></main>;
  if (now.isError) return <main className="main-content"><p className="editorial-label">NOW / UNAVAILABLE</p><p role="alert">We could not load NOW. Please try again.</p></main>;
  const { items, window_stats } = now.data;
  return <main className="main-content" id="now">
    <p className="editorial-label">NOW</p>
    <header className="now-header"><h1>What matters now.</h1><p>{window_stats.raw_information_count} pieces of information, organized into {window_stats.event_count} events.</p></header>
    {items.length === 0 ? <section className="now-empty"><p className="editorial-label">WINDOW / CLEAR</p><h2>Nothing requires your attention yet.</h2><p>New signals will appear here when they become relevant to your view.</p></section> : <section className="event-list" aria-label="Current events">{items.map((event) => <article className="event-item" key={event.id}><div className="event-item__heading"><p className="editorial-label">EVENT / {event.state}</p><label><input aria-label={`Select ${event.title}`} checked={selectedEvents.some((selected) => selected.id === event.id)} disabled={!selectedEvents.some((selected) => selected.id === event.id) && selectedEvents.length === 8} onChange={() => onToggleEventSelection({ id: event.id, title: event.title })} type="checkbox" /> Compare</label></div><h2><a href={`#event/${event.id}`}>{event.title}</a></h2><p>{event.overview}</p><p className="event-meta">{event.display_time} · {event.new_claim_count} new claims · {event.conflict_count} conflicts</p><p>{event.why_it_matters}</p><SaveButton eventId={event.id} saved={event.saved} /></article>)}</section>}
    <p className="window-meta">Window ended {window_stats.window_ended_at} · {window_stats.relevant_event_count} relevant events</p>
  </main>;
}
