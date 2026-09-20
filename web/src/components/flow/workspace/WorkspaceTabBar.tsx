import { FlowIcon } from '../FlowIcon';
import { WORKSPACE_TABS, type WorkspaceTab } from './workspaceTabs';

export function WorkspaceTabBar({
  active,
  onChange,
}: {
  active: WorkspaceTab;
  onChange: (tab: WorkspaceTab) => void;
}) {
  return (
    <div className="workspace-tab-bar-wrap">
      <nav className="workspace-tab-bar" role="tablist" aria-label="Workspace">
        {WORKSPACE_TABS.map(({ id, label, icon }) => {
          const selected = active === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              id={`flow-tab-${id}`}
              aria-selected={selected}
              aria-controls={`flow-panel-${id}`}
              tabIndex={selected ? 0 : -1}
              className={`workspace-tab${selected ? ' is-active' : ''}`}
              onClick={() => onChange(id)}
            >
              <span className="workspace-tab-icon" aria-hidden="true">
                <FlowIcon>{icon}</FlowIcon>
              </span>
              <span className="workspace-tab-label">{label}</span>
            </button>
          );
        })}
      </nav>
    </div>
  );
}
