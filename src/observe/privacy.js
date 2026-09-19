/**
 * Privacy filter.
 *
 * This module is the single choke point between the OS observer and everything
 * downstream (analyzer, persistence, UI). Nothing that fails a check here is
 * stored, streamed, or sent to a model — local or remote.
 */
import fs from 'node:fs';
import { DEFAULT_EXCLUDED_APPS } from '../domain/contracts.js';

/** Patterns that commonly carry secrets in a window title. Redacted, never stored raw. */
const SENSITIVE_TITLE_PATTERNS = [
  { re: /\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b/g, label: '[email]' },
  { re: /\b(?:sk|pk|rk)-[A-Za-z0-9_-]{16,}\b/g, label: '[api-key]' },
  { re: /\bgh[pousr]_[A-Za-z0-9]{16,}\b/g, label: '[token]' },
  { re: /\bBearer\s+[A-Za-z0-9._~+/-]{16,}=*/gi, label: '[token]' },
  { re: /\bey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\b/g, label: '[jwt]' },
  { re: /\b(?:\d[ -]?){13,19}\b/g, label: '[card-number]' },
];

/** Title fragments that suggest a private context regardless of the app. */
const SENSITIVE_TITLE_HINTS = [/\bprivate browsing\b/i, /\bincognito\b/i, /\bpassword\b/i, /\bseed phrase\b/i, /\b2fa\b/i, /\brecovery code/i];

export function defaultPrivacySettings() {
  return {
    excludedApps: [...DEFAULT_EXCLUDED_APPS],
    screenshotsEnabled: false,
    retention: 'discard-after-analysis',
    retentionMinutes: 60,
    analysisLocation: 'metadata-only',
    cloudConsent: false,
    redactTitles: true,
    observedFields: ['frontmost application name', 'window title (redacted)', 'screenshot (only when explicitly enabled)'],
  };
}

const norm = (s) => String(s || '').trim().toLowerCase();

/** True when `app` is on the exclusion list (case-insensitive, substring-safe). */
export function isExcludedApp(privacy, app) {
  const a = norm(app);
  if (!a) return false;
  return (privacy?.excludedApps || []).some((x) => {
    const e = norm(x);
    return e && (a === e || a.includes(e) || e.includes(a));
  });
}

/** Replace secret-shaped substrings in a window title. Returns { title, redactions }. */
export function redactTitle(title) {
  let out = String(title || '');
  const redactions = [];
  for (const { re, label } of SENSITIVE_TITLE_PATTERNS) {
    out = out.replace(re, () => {
      if (!redactions.includes(label)) redactions.push(label);
      return label;
    });
  }
  return { title: out.slice(0, 400), redactions };
}

/**
 * Apply the full privacy policy to a raw observation.
 *
 * @returns {{allowed: boolean, reason?: string, observation?: object}}
 *   `allowed:false` means: do not store, do not stream, do not analyze.
 */
export function applyPrivacyFilter(privacy, raw) {
  const settings = { ...defaultPrivacySettings(), ...(privacy || {}) };

  if (!raw || !raw.app || typeof raw.app !== 'string' || !raw.app.trim()) {
    return { allowed: false, reason: 'no-app' };
  }
  if (isExcludedApp(settings, raw.app)) {
    // Delete any screenshot that was captured before the app was known.
    discardScreenshot(raw.screenshotPath);
    return { allowed: false, reason: 'excluded-app' };
  }

  const rawTitle = String(raw.title || '');
  let title = rawTitle;
  let redactions = [];
  if (settings.redactTitles !== false) ({ title, redactions } = redactTitle(rawTitle));

  const privateHint = SENSITIVE_TITLE_HINTS.some((re) => re.test(rawTitle));
  if (privateHint) {
    discardScreenshot(raw.screenshotPath);
    return {
      allowed: true,
      observation: {
        app: raw.app.trim().slice(0, 120),
        title: '',
        titleWithheld: true,
        redactions: ['[private-context]'],
        screenshotPath: null,
        screenshotAllowed: false,
        time: raw.time,
        simulated: !!raw.simulated,
      },
    };
  }

  // Screenshots require BOTH the session-level toggle and a granted OS permission.
  const screenshotAllowed = !!settings.screenshotsEnabled && !!raw.screenshotPath;
  if (!screenshotAllowed) discardScreenshot(raw.screenshotPath);

  return {
    allowed: true,
    observation: {
      app: raw.app.trim().slice(0, 120),
      title,
      titleWithheld: false,
      redactions,
      screenshotPath: screenshotAllowed ? raw.screenshotPath : null,
      screenshotAllowed,
      time: raw.time,
      simulated: !!raw.simulated,
    },
  };
}

/** Best-effort deletion of a screenshot file. Never throws. */
export function discardScreenshot(filePath) {
  if (!filePath) return false;
  try {
    fs.unlinkSync(filePath);
    return true;
  } catch {
    return false;
  }
}

/**
 * Decide whether a payload may be sent to a remote provider.
 * Cloud analysis requires explicit, recorded consent — never a default.
 */
export function mayUseCloud(privacy) {
  const s = { ...defaultPrivacySettings(), ...(privacy || {}) };
  return s.analysisLocation === 'cloud' && s.cloudConsent === true;
}
