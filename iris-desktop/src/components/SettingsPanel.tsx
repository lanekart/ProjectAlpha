import { X } from "lucide-react";
import type { ApplicationDefinition } from "../core/applicationRegistry";

type SettingsPanelProps = {
  registry: ApplicationDefinition[];
  onClose: () => void;
};

export function SettingsPanel({ registry, onClose }: SettingsPanelProps) {
  return (
    <aside className="settings-panel">
      <header>
        <h1>IRIS Settings</h1>
        <button title="Close settings" onClick={onClose}>
          <X size={17} />
        </button>
      </header>

      <section>
        <h2>General</h2>
        <label>
          Display name
          <input defaultValue="Rishab" />
        </label>
        <label>
          Morning greeting
          <input type="time" defaultValue="08:00" />
        </label>
        <label>
          Quiet hours
          <input defaultValue="22:00-07:00" />
        </label>
        <label className="inline">
          <input type="checkbox" />
          Launch IRIS when I sign in
        </label>
      </section>

      <section>
        <h2>Voice</h2>
        <label>
          Speaking speed
          <input type="range" min="0.6" max="1.4" step="0.1" defaultValue="1" />
        </label>
        <label>
          Volume
          <input type="range" min="0" max="1" step="0.1" defaultValue="0.8" />
        </label>
      </section>

      <section>
        <h2>Integrations</h2>
        <p>Calendar: disconnected</p>
        <p>Gmail: disconnected</p>
        <button>Connect Google account</button>
      </section>

      <section>
        <h2>Applications</h2>
        <ul>
          {registry.map((app) => (
            <li key={app.id}>
              <span>{app.label}</span>
              <small>{app.platforms.join(", ")}</small>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <h2>Privacy</h2>
        <button>Delete local command history</button>
        <button>View stored permissions</button>
      </section>
    </aside>
  );
}
