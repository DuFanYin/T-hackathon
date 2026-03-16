import type { FC } from 'react';

export type Tab = 'System' | 'Strategies' | 'Symbols' | 'Logs';

interface SidebarProps {
  tab: Tab;
  setTab: (t: Tab) => void;
  apiBase: string;
  pills: { ok: boolean; label: string };
}

export const Sidebar: FC<SidebarProps> = ({
  tab,
  setTab,
  apiBase,
  pills,
}) => {
  const tabs: Tab[] = ['System', 'Strategies', 'Symbols', 'Logs'];
  return (
    <aside className="sidebar">
      <div className="brand">T-hackathon</div>
      <div className="meta">
        API: <span className="mono">{apiBase}</span>
        <br />
        Status:{' '}
        <span className={`pill ${pills.ok ? 'ok' : 'bad'}`}>{pills.label}</span>
      </div>
      <nav className="nav">
        {tabs.map((t) => (
          <button
            key={t}
            className={tab === t ? 'active' : ''}
            onClick={() => setTab(t)}
          >
            {t}
          </button>
        ))}
      </nav>
    </aside>
  );
};

