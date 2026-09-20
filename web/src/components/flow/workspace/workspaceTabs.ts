export type WorkspaceTab = 'session' | 'agent' | 'docs' | 'showcase';

export type WorkspaceTabDef = {
  id: WorkspaceTab;
  label: string;
  icon: string;
};

/** Primary nav — equal visual weight; labels kept short on purpose. */
export const WORKSPACE_TABS: readonly WorkspaceTabDef[] = [
  { id: 'session', label: 'Session', icon: '◉' },
  { id: 'agent', label: 'Agent', icon: '✦' },
  { id: 'docs', label: 'Docs', icon: '⌕' },
  { id: 'showcase', label: 'Demo', icon: '◇' },
] as const;
