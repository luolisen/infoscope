import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "./api/health";
import { fetchSession, sessionQueryKey } from "./api/session";
import { AuthScreen } from "./features/auth/AuthScreen";
import { AskPanel } from "./features/ask/AskPanel";
import { BriefPage } from "./features/brief/BriefPage";
import { ArchivePage } from "./features/archive/ArchivePage";
import { EventDetail } from "./features/events/EventDetail";
import { MaintenancePanel } from "./features/maintenance/MaintenancePanel";
import { OnboardingPending } from "./features/auth/OnboardingPending";
import { NowShell } from "./features/now/NowShell";
import { SearchOverlay } from "./features/search/SearchOverlay";

const primaryNavigation = ["NOW", "BRIEF", "ARCHIVE"];
const settingsNavigation = ["SCOPE", "SETTINGS"];

type SelectedEvent = { id: string; title: string };

export function App() {
  const sessionQuery = useQuery({ queryKey: sessionQueryKey, queryFn: fetchSession });

  if (sessionQuery.isPending) {
    return <main className="state-page"><p>Checking your session…</p></main>;
  }

  if (sessionQuery.isError) {
    return <main className="state-page"><p role="alert">We could not check your session. Please refresh and try again.</p></main>;
  }

  if (sessionQuery.data.state === "anonymous") {
    return <AuthScreen />;
  }

  if (sessionQuery.data.state === "onboarding_required") {
    return <OnboardingPending />;
  }

  return <ReadyApp />;
}

function ReadyApp() {
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: fetchHealth });
  const [locationHash, setLocationHash] = useState(() => window.location.hash);
  const [selectedEvents, setSelectedEvents] = useState<SelectedEvent[]>([]);
  const [searchOpen, setSearchOpen] = useState(false);
  const eventId = locationHash.match(/^#event\/([^/]+)$/)?.[1];
  const isSettings = locationHash === "#settings";
  const isBrief = locationHash === "#brief";
  const isArchive = locationHash === "#archive";

  const toggleEventSelection = (eventToToggle: SelectedEvent) => {
    setSelectedEvents((events) => {
      if (events.some((event) => event.id === eventToToggle.id)) return events.filter((event) => event.id !== eventToToggle.id);
      return events.length === 8 ? events : [...events, eventToToggle];
    });
  };

  useEffect(() => {
    const updateLocation = () => setLocationHash(window.location.hash);
    window.addEventListener("hashchange", updateLocation);
    return () => window.removeEventListener("hashchange", updateLocation);
  }, []);

  useEffect(() => {
    const openSearch = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener("keydown", openSearch);
    return () => window.removeEventListener("keydown", openSearch);
  }, []);

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Infoscope home">IS</a>
        <span className="meta">{healthQuery.isSuccess ? "SYSTEM / ONLINE" : "SYSTEM / CHECKING"}</span>
        <button className="search-trigger" onClick={() => setSearchOpen(true)} type="button" aria-label="Search, shortcut Command K">
          <span>Search</span>
          <kbd>⌘K</kbd>
        </button>
      </header>

      <aside className="sidebar" aria-label="Primary navigation">
        <nav>
          <ul className="navigation-list">
            {primaryNavigation.map((item) => (
              <li key={item}>
                <a aria-current={(item === "NOW" && !isSettings && !isBrief && !isArchive) || (item === "BRIEF" && isBrief) || (item === "ARCHIVE" && isArchive) ? "page" : undefined} href={`#${item.toLowerCase()}`}>
                  {item}
                </a>
              </li>
            ))}
          </ul>
          <ul className="navigation-list navigation-list--secondary">
            {settingsNavigation.map((item) => (
              <li key={item}><a aria-current={item === "SETTINGS" && isSettings ? "page" : undefined} href={`#${item.toLowerCase()}`}>{item}</a></li>
            ))}
          </ul>
        </nav>
      </aside>

      <div className="content-column">
        {isSettings ? <MaintenancePanel /> : isBrief ? <BriefPage /> : isArchive ? <ArchivePage /> : eventId === undefined ? <NowShell onToggleEventSelection={toggleEventSelection} selectedEvents={selectedEvents} /> : <EventDetail eventId={eventId} onBack={() => { window.location.hash = ""; }} onToggleEventSelection={toggleEventSelection} selectedEvents={selectedEvents} />}
        {!isSettings && !isBrief && !isArchive && <AskPanel onClearSelection={() => setSelectedEvents([])} selectedEvents={selectedEvents} />}
      </div>
      <SearchOverlay onClose={() => setSearchOpen(false)} open={searchOpen} />
    </div>
  );
}
