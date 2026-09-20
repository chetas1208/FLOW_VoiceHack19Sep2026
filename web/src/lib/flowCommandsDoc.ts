export const DOC_NAV = [
  { id: 'quick-start', title: 'Quick Start' },
  { id: 'install', title: 'Install' },
  { id: 'connect', title: 'Connect Account' },
  { id: 'start', title: 'Start Session' },
  { id: 'commands', title: 'Commands' },
  { id: 'troubleshoot', title: 'Troubleshooting' },
] as const;

export function installCommand(repository = 'https://github.com/chetas1208/FLOW_VoiceHack19Sep2026.git') {
  return `python3 -m pip install --user "git+${repository}"`;
}

export const CORE_COMMANDS = [
  { group: 'Setup & account', items: ['flow setup', 'flow login', 'flow logout', 'flow whoami', 'flow account', 'flow devices'] },
  { group: 'Session & daemon', items: ['flow start "goal"', 'flow status', 'flow pause', 'flow resume', 'flow stop', 'flow daemon start', 'flow daemon stop', 'flow daemon status', 'flow e2e', 'flow efficiency test'] },
  { group: 'Intelligence', items: ['flow ask "question"', 'flow recommend', 'flow recommend --do', 'flow task add "task"'] },
  { group: 'Voice', items: ['flow voice status', 'flow voice on', 'flow voice off', 'flow voice mute 30m', 'flow voice unmute', 'flow voice stop', 'flow voice test'] },
  { group: 'System & privacy', items: ['flow doctor', 'flow observer', 'flow permissions', 'flow config', 'flow validate'] },
] as const;

export const TROUBLESHOOTING = [
  { issue: 'Device shows offline but still linked', fix: 'Start the local daemon: flow daemon start' },
  { issue: 'flow login times out', fix: 'Open the browser URL within 5 minutes and approve the device request.' },
  { issue: 'Session commands fail', fix: 'Run flow status and ensure one active session exists.' },
  { issue: 'Model shows unloaded', fix: 'Normal — FLOW loads models on demand (≤500 MB budget).' },
  { issue: 'Permission errors on macOS', fix: 'Run flow permissions and grant Screen Recording + Accessibility.' },
  { issue: 'Account URL mismatch', fix: 'export FLOW_ACCOUNT_URL=<this site origin> then flow login again.' },
] as const;
