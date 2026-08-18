import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "./api/health";
import { fetchSession, sessionQueryKey } from "./api/session";
import { AuthScreen } from "./features/auth/AuthScreen";
import { AskWorkspace } from "./features/ask/AskWorkspace";
import { AskEventSidebar } from "./features/ask/AskEventSidebar";
import { BriefPage } from "./features/brief/BriefPage";
import { ArchivePage } from "./features/archive/ArchivePage";
import { EventDetail } from "./features/events/EventDetail";
import { OnboardingPending } from "./features/auth/OnboardingPending";
import { NowShell } from "./features/now/NowShell";
import { SearchOverlay } from "./features/search/SearchOverlay";
import { SettingsPage } from "./features/settings/SettingsPage";
import { SearchIcon } from "./components/Icons";

const primaryNavigation = ["NOW", "ASK", "BRIEF", "ARCHIVE"];
const settingsNavigation = ["SCOPE", "SETTINGS"];

type SelectedEvent = { id: string; title: string };

export function App() {
  const sessionQuery = useQuery({ queryKey: sessionQueryKey, queryFn: fetchSession });

  if (sessionQuery.isPending) {
    return <main className="state-page"><p>正在检查登录状态…</p></main>;
  }

  if (sessionQuery.isError) {
    return <main className="state-page"><p role="alert">无法检查登录状态，请刷新后重试。</p></main>;
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
  const searchTriggerRef = useRef<HTMLButtonElement>(null);
  const navigationRef = useRef<HTMLElement>(null);
  const navigationLinks = useRef<Record<string, HTMLAnchorElement | null>>({});
  const [activeIndicator, setActiveIndicator] = useState({ top: 0, left: 0, height: 0, width: 0, visible: false });
  const eventId = locationHash.match(/^#event\/([^/]+)$/)?.[1];
  const isSettings = locationHash === "#settings";
  const isScope = locationHash === "#scope";
  const isBrief = locationHash === "#brief";
  const isArchive = locationHash === "#archive";
  const isAsk = locationHash === "#ask";
  const activePrimary = isAsk ? "ASK" : isBrief ? "BRIEF" : isArchive ? "ARCHIVE" : "NOW";
  const activeSecondary = isSettings ? "SETTINGS" : isScope ? "SCOPE" : null;

  useLayoutEffect(() => {
    const updateIndicator = () => {
      const active = navigationLinks.current[activeSecondary ?? activePrimary];
      const nav = navigationRef.current;
      if (!active || !nav) return;
      const navRect = nav.getBoundingClientRect();
      const linkRect = active.getBoundingClientRect();
      const mobile = window.matchMedia?.("(max-width: 640px)").matches
        ?? window.innerWidth <= 640;
      setActiveIndicator({
        top: mobile ? navRect.height - 2 : linkRect.top - navRect.top,
        left: mobile ? linkRect.left - navRect.left : -12,
        height: mobile ? 2 : linkRect.height,
        width: mobile ? linkRect.width : 3,
        visible: true,
      });
    };
    updateIndicator();
    window.addEventListener("resize", updateIndicator);
    return () => window.removeEventListener("resize", updateIndicator);
  }, [activePrimary, activeSecondary]);

  const closeSearch = () => {
    setSearchOpen(false);
    requestAnimationFrame(() => searchTriggerRef.current?.focus());
  };

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
        <button className="search-trigger" onClick={() => setSearchOpen(true)} ref={searchTriggerRef} type="button" aria-label="搜索，快捷键 Command K">
          <SearchIcon className="action-icon" />
          <span>搜索</span>
          <kbd>⌘K</kbd>
        </button>
      </header>

      <aside className="sidebar" aria-label="Primary navigation">
        <nav ref={navigationRef}>
          <span aria-hidden="true" className="navigation-indicator" style={{ height: activeIndicator.height, left: activeIndicator.left, opacity: activeIndicator.visible ? 1 : 0, top: activeIndicator.top, width: activeIndicator.width }} />
          <ul className="navigation-list">
            {primaryNavigation.map((item) => (
              <li key={item}>
                <a aria-current={item === activePrimary && activeSecondary === null ? "page" : undefined} href={`#${item.toLowerCase()}`} ref={(node) => { navigationLinks.current[item] = node; }}>
                  {item}
                </a>
              </li>
            ))}
          </ul>
          <ul className="navigation-list navigation-list--secondary">
            {settingsNavigation.map((item) => (
              <li key={item}><a aria-current={item === activeSecondary ? "page" : undefined} href={`#${item.toLowerCase()}`} ref={(node) => { navigationLinks.current[item] = node; }}>{item}</a></li>
            ))}
          </ul>
        </nav>
        {isAsk && <AskEventSidebar onToggleEventSelection={toggleEventSelection} selectedEvents={selectedEvents} />}
      </aside>

      <div className="content-column">
        <div className="page-transition" key={locationHash}>
          {isSettings ? <SettingsPage /> : isScope ? <OnboardingPending editExisting onComplete={() => { window.location.hash = "#now"; }} /> : isAsk ? <AskWorkspace onClearSelection={() => setSelectedEvents([])} selectedEvents={selectedEvents} /> : isBrief ? <BriefPage /> : isArchive ? <ArchivePage /> : eventId === undefined ? <NowShell onToggleEventSelection={toggleEventSelection} selectedEvents={selectedEvents} /> : <EventDetail eventId={eventId} onAsk={() => { window.location.hash = "#ask"; }} onBack={() => { window.location.hash = ""; }} onToggleEventSelection={toggleEventSelection} selectedEvents={selectedEvents} />}
        </div>
      </div>
      <SearchOverlay onClose={closeSearch} open={searchOpen} />
    </div>
  );
}
