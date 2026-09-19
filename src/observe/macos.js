/**
 * macOS observation layer.
 *
 * Two independent signals, each behind its own OS permission:
 *   1. Frontmost application name  — NSWorkspace via the native helper. No permission needed.
 *   2. Window title                — System Events (AppleScript). Needs Accessibility.
 *   3. Screenshot                  — ScreenCaptureKit via the native helper. Needs Screen Recording.
 *
 * We never attempt to work around a missing permission, and we never retry in a
 * hidden loop: a denied permission is surfaced once, with the exact action the
 * user can take, and the observer degrades to whatever signals remain.
 */
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const exec = promisify(execFile);
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const HELPER = path.join(ROOT, 'native', 'bin', 'FlowCapture');

export const isMac = process.platform === 'darwin';
export const helperAvailable = () => isMac && fs.existsSync(HELPER);

const FRONTMOST_SCRIPT = `tell application "System Events"
  set frontApp to first application process whose frontmost is true
  set appName to name of frontApp
  try
    set winName to name of front window of frontApp
  on error
    set winName to ""
  end try
  return appName & "|||" & winName
end tell`;

async function runHelper(args, timeout = 8000) {
  const { stdout } = await exec(HELPER, args, { timeout, maxBuffer: 1 << 20 });
  const line = stdout.trim().split('\n').filter(Boolean).pop() || '{}';
  return JSON.parse(line);
}

/**
 * Probe both permissions without prompting.
 * @returns {Promise<{platform:string, helper:boolean, screenRecording:'granted'|'denied'|'unavailable', accessibility:'granted'|'denied'|'unavailable', detail:string|null}>}
 */
export async function checkPermissions() {
  const result = {
    platform: process.platform,
    helper: helperAvailable(),
    screenRecording: 'unavailable',
    accessibility: 'unavailable',
    detail: null,
  };
  if (!isMac) {
    result.detail = 'Screen observation is implemented for macOS only. Other platforms can use manual or simulated observations.';
    return result;
  }
  if (result.helper) {
    try {
      const out = await runHelper(['permission'], 5000);
      result.screenRecording = out.permission === 'granted' ? 'granted' : 'denied';
    } catch (err) {
      result.screenRecording = 'denied';
      result.detail = `Capture helper failed: ${String(err.message).slice(0, 160)}`;
    }
  } else {
    result.detail = 'Native helper not built. Run `npm run build:native` to enable screenshot capture.';
  }
  try {
    await exec('osascript', ['-e', FRONTMOST_SCRIPT], { timeout: 6000 });
    result.accessibility = 'granted';
  } catch (err) {
    result.accessibility = 'denied';
    const hint = 'Grant Accessibility to your terminal in System Settings › Privacy & Security › Accessibility to read window titles.';
    result.detail = result.detail ? `${result.detail} ${hint}` : hint;
  }
  return result;
}

/** Trigger the one-time Screen Recording system prompt. */
export async function requestScreenRecordingPermission() {
  if (!helperAvailable()) return { permission: 'unavailable', reason: 'helper-not-built' };
  try {
    return await runHelper(['request-permission'], 30000);
  } catch (err) {
    return { permission: 'denied', reason: String(err.message).slice(0, 200) };
  }
}

/**
 * Read the frontmost app and (if permitted) its window title.
 * @returns {Promise<{app:string,title:string,titleAvailable:boolean,source:string}>}
 */
export async function readFrontmost() {
  if (!isMac) throw Object.assign(new Error('Frontmost detection requires macOS'), { code: 'UNSUPPORTED_PLATFORM' });

  let app = '';
  let title = '';
  let titleAvailable = false;
  let source = 'none';

  // Preferred path: one AppleScript call gives both app and title.
  try {
    const { stdout } = await exec('osascript', ['-e', FRONTMOST_SCRIPT], { timeout: 6000 });
    const [a, ...rest] = stdout.trim().split('|||');
    app = (a || '').trim();
    title = rest.join('|||').trim().slice(0, 400);
    titleAvailable = true;
    source = 'system-events';
  } catch {
    // Accessibility denied: fall back to the app name only, which needs no permission.
    if (helperAvailable()) {
      try {
        const out = await runHelper(['frontmost'], 5000);
        app = out.app || '';
        source = 'nsworkspace';
      } catch { /* both signals unavailable */ }
    }
  }

  if (!app) throw Object.assign(new Error('Could not determine the frontmost application'), { code: 'NO_FRONTMOST' });
  return { app, title, titleAvailable, source };
}

/**
 * Capture a screenshot with excluded apps filtered out by the compositor.
 * @returns {Promise<{ok:boolean, path?:string, error?:string, excluded?:string[]}>}
 */
export async function captureScreenshot({ excludedApps = [], maxWidth = 1280, quality = 0.6, dir } = {}) {
  if (!helperAvailable()) return { ok: false, error: 'helper-not-built' };
  const outDir = dir || path.join(os.tmpdir(), 'flow-captures');
  const out = path.join(outDir, `shot_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.jpg`);
  try {
    const res = await runHelper(
      ['capture', '--out', out, '--exclude', excludedApps.join(','), '--max-width', String(maxWidth), '--quality', String(quality)],
      15000,
    );
    if (!res.ok) return { ok: false, error: res.error || 'capture-failed' };
    return { ok: true, path: res.path, width: res.width, height: res.height, excluded: res.excluded || [] };
  } catch (err) {
    return { ok: false, error: String(err.message).slice(0, 200) };
  }
}

/** Speak text with the macOS speech synthesizer. Resolves to a lifecycle result. */
export async function speak(text, { voice, rate } = {}) {
  if (!isMac) return { ok: false, error: 'say-unavailable-on-platform' };
  const args = [];
  if (voice) args.push('-v', voice);
  if (rate) args.push('-r', String(rate));
  args.push(String(text).slice(0, 600));
  try {
    await exec('say', args, { timeout: 45000 });
    return { ok: true };
  } catch (err) {
    return { ok: false, error: String(err.message).slice(0, 200) };
  }
}

/** List installed speech voices (name + locale). */
export async function listVoices() {
  if (!isMac) return [];
  try {
    const { stdout } = await exec('say', ['-v', '?'], { timeout: 6000 });
    return stdout
      .trim()
      .split('\n')
      .map((line) => {
        const m = line.match(/^(.+?)\s{2,}([\w-]+)\s+#\s*(.*)$/);
        return m ? { name: m[1].trim(), locale: m[2], sample: m[3] } : null;
      })
      .filter(Boolean)
      .filter((v) => v.locale.startsWith('en'));
  } catch {
    return [];
  }
}
