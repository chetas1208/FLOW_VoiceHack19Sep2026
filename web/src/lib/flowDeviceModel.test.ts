import { describe, expect, it } from 'vitest';
import type { FlowDevice } from './account';
import { pairingState, pickPrimaryDevice } from './flowDeviceModel';

const base: FlowDevice = {
  id: 'dev_test1234567890',
  name: 'MacBook Pro',
  os: 'macOS',
  architecture: 'arm64',
  flow_version: '1.0.0',
  created_at: new Date().toISOString(),
  last_seen_at: new Date().toISOString(),
  revoked_at: null,
  presence: { state: 'offline', last_heartbeat_at: null, health: { daemon: 'not_running' } },
};

describe('flowDeviceModel', () => {
  it('treats revoked separately from offline presence', () => {
    expect(pairingState({ ...base, revoked_at: new Date().toISOString() })).toBe('revoked');
    expect(pairingState(base)).toBe('paired');
  });

  it('keeps preferred paired device when offline', () => {
    const items = [base, { ...base, id: 'dev_other1234567890', name: 'Other' }];
    expect(pickPrimaryDevice(items, base.id)?.id).toBe(base.id);
  });
});
