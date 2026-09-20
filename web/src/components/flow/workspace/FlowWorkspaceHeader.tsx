import type { FlowDevice } from '../../../lib/account';
import { pairingState, type PresenceState } from '../../../lib/flowDeviceModel';
import type { AccountUser } from '../../../lib/flowWorkspaceUi';
import { AccountMenu } from './AccountMenu';
import { DeviceStatusChip } from './DeviceStatusChip';
import { FlowBrand } from './FlowBrand';
import { WorkspaceTabBar } from './WorkspaceTabBar';
import type { WorkspaceTab } from './workspaceTabs';

export function FlowWorkspaceHeader({
  tab,
  onTabChange,
  device,
  pairing,
  presence,
  account,
}: {
  tab: WorkspaceTab;
  onTabChange: (tab: WorkspaceTab) => void;
  device: FlowDevice | null;
  pairing: ReturnType<typeof pairingState>;
  presence: PresenceState;
  account?: AccountUser;
}) {
  return (
    <header className="flow-header flow-header-balanced">
      <FlowBrand />
      <WorkspaceTabBar active={tab} onChange={onTabChange} />
      <div className="flow-header-actions">
        <DeviceStatusChip device={device} pairing={pairing} presence={presence} />
        <AccountMenu account={account} />
      </div>
    </header>
  );
}
