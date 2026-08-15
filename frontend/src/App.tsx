import { useQuery } from "@tanstack/react-query";

import { fetchHealth } from "./api/health";
import { fetchSession, sessionQueryKey } from "./api/session";
import { AuthScreen } from "./features/auth/AuthScreen";
import { OnboardingPending } from "./features/auth/OnboardingPending";
import { NowShell } from "./features/now/NowShell";

const primaryNavigation = ["NOW", "BRIEF", "ARCHIVE"];
const settingsNavigation = ["SCOPE", "SETTINGS"];

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

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="wordmark" href="/" aria-label="Infoscope home">IS</a>
        <span className="meta">{healthQuery.isSuccess ? "SYSTEM / ONLINE" : "SYSTEM / CHECKING"}</span>
        <button className="search-trigger" type="button" aria-label="Search, shortcut Command K">
          <span>Search</span>
          <kbd>⌘K</kbd>
        </button>
      </header>

      <aside className="sidebar" aria-label="Primary navigation">
        <nav>
          <ul className="navigation-list">
            {primaryNavigation.map((item) => (
              <li key={item}>
                <a aria-current={item === "NOW" ? "page" : undefined} href={`#${item.toLowerCase()}`}>
                  {item}
                </a>
              </li>
            ))}
          </ul>
          <ul className="navigation-list navigation-list--secondary">
            {settingsNavigation.map((item) => (
              <li key={item}><a href={`#${item.toLowerCase()}`}>{item}</a></li>
            ))}
          </ul>
        </nav>
      </aside>

      <NowShell />
    </div>
  );
}
