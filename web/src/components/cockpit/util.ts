export { LEVEL_LABEL, pct, untilLabel, clock } from '../../lib/format';
import { clock } from '../../lib/format';
export const clockOrEmpty = (iso: string) => (iso ? clock(iso) : '');
