import { useQuery } from "@tanstack/react-query";

import { briefLatestQueryKey, fetchLatestBrief } from "../../api/brief";

export function BriefPage() {
  const brief = useQuery({ queryKey: briefLatestQueryKey, queryFn: fetchLatestBrief });

  if (brief.isPending) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF / LOADING</p><p>正在准备 Brief…</p></main>;
  }

  if (brief.isError) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF / UNAVAILABLE</p><p role="alert">无法加载 Brief，请稍后重试。</p></main>;
  }

  const { generated_at: generatedAt, items } = brief.data;
  if (items.length === 0) {
    return <main className="main-content brief-page"><p className="editorial-label">BRIEF</p><header className="brief-header"><h1>{generatedAt === null ? "Brief 正在等待。" : "当前 Brief 没有内容。"}</h1><p>{generatedAt === null ? "当前 Event 视图准备好后，新的 Brief 会出现在这里。" : `生成于 ${generatedAt}，当前没有 Brief 条目。`}</p></header></main>;
  }

  return (
    <main className="main-content brief-page" id="brief">
      <p className="editorial-label">BRIEF</p>
      <header className="brief-header"><h1>当前视野，一览。</h1><p>生成于 {generatedAt}</p></header>
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
