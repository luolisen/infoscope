import { AskPanel } from "./AskPanel";
import { AskHistoryPanel } from "./AskHistoryPanel";

type EventSelection = { id: string; title: string };

type AskWorkspaceProps = {
  selectedEvents: EventSelection[];
  onClearSelection: () => void;
};

export function AskWorkspace({ selectedEvents, onClearSelection }: AskWorkspaceProps) {
  return (
    <main className="main-content ask-workspace" aria-labelledby="ask-workspace-heading">
      <AskHistoryPanel />
      <header className="ask-workspace__hero">
        <p className="editorial-label">ASK</p>
        <h1 id="ask-workspace-heading">观澜能帮忙做什么</h1>
        <p>选择一个或多个 Event，再提出你想理解的问题。</p>
      </header>
      <AskPanel onClearSelection={onClearSelection} selectedEvents={selectedEvents} workspace />
    </main>
  );
}
