const KEY = 'flow.preferred_device_id';

export function readPreferredDeviceId(): string | null {
  try {
    const value = localStorage.getItem(KEY);
    return value && value.trim() ? value.trim() : null;
  } catch {
    return null;
  }
}

export function writePreferredDeviceId(deviceId: string): void {
  try {
    localStorage.setItem(KEY, deviceId);
  } catch {
    /* private mode / blocked storage */
  }
}

export function clearPreferredDeviceId(): void {
  try {
    localStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
