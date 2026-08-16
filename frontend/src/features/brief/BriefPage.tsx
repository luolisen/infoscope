import { useQuery } from "@tanstack/react-query";

import { briefLatestQueryKey, fetchLatestBrief } from "../../api/brief";

export function BriefPage() {
  const brief = useQuery({ queryKey: briefLatestQueryKey, queryFn: fetchLatestBrief });

  if (brief.isPending) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF / LOADING</p><p>Preparing your current Brief…</p></main>;
  }

  if (brief.isError) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF / UNAVAILABLE</p><p role="alert">We could not load your Brief. Please try again.</p></main>;
  }

  const { generated_at: generatedAt, items } = brief.data;
  if (generatedAt === null && items.length === 0) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF</p><header className="brief-header"><h1>Your Brief is waiting.</h1><p>A new Brief will appear after the current event view is ready.</p></header></main>;
  }

  return (
    <main className="main-content brief-page" id="brief">
      <p className="editorial-label">BRIEF</p>
      <header className="brief-header"><h1>The current view, in brief.</h1><p>Generated {generatedAt}</p></header>
      <section aria-label="Latest Brief" className="brief-list">
        {items.map((item) => (
          <article className="brief-item" key={item.event_id}>
            <h2><a href={`#event/${item.event_id}`}>{item.title}</a></h2>
            <p>{item.summary}</p>
            <p className="brief-why">{item.why_it_matters}</p>
          </article>
        ))}
      </section>
    </main>
  );
}
