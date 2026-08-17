import { MaintenancePanel } from "../maintenance/MaintenancePanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";

export function SettingsPage() {
  return (
    <main className="main-content settings-page">
      <ModelSettingsPanel />
      <MaintenancePanel />
    </main>
  );
}
