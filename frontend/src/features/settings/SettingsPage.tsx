import { MaintenancePanel } from "../maintenance/MaintenancePanel";
import { ModelSettingsPanel } from "./ModelSettingsPanel";

type SettingsPageProps = {
  onStartDemo: () => void;
};

export function SettingsPage({ onStartDemo }: SettingsPageProps) {
  return (
    <main className="main-content settings-page">
      <ModelSettingsPanel />
      <MaintenancePanel />
      <section className="demo-settings">
        <p className="editorial-label">DEMO</p>
        <h1>重新演示初见。</h1>
        <p>重放称呼、Scope 与 Focus 设置过程。演示选择不会修改本机已保存的 Profile。</p>
        <button className="demo-start" onClick={onStartDemo} type="button">演示demo</button>
      </section>
    </main>
  );
}
