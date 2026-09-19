import { FormEvent, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CommandChip, EmptyState, PresenceDot, Spinner } from '../components/primitives';
import { api } from '../lib/api';
import { POLICY_LABEL } from '../lib/format';
import { useDocumentTitle } from '../lib/hooks';
import type { PermissionPolicy, SessionCommand } from '../lib/types';
import { sendCommand } from '../store/actions';
import { useStore } from '../store/store';

const POLICIES: PermissionPolicy[] = ['manual', 'safe_auto', 'read_only'];
const MAX_WAIT_MS = 75_000;

export function StartSessionPage() {
  useDocumentTitle('Start a session');
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const devices = useStore((s) => s.devices);
  const loaded = useStore((s) => s.devicesLoaded);
  const sessionIndex = useStore((s) => s.sessionIndex);
  const list = useMemo(() => Object.values(devices).filter((d) => !d.revoked_at).sort((a, b) => a.name.localeCompare(b.name)), [devices]);
  const [deviceId, setDeviceId] = useState(params.get('device') ?? '');
  const [goal, setGoal] = useState('');
  const [policy, setPolicy] = useState<PermissionPolicy>('manual');
  const [phase, setPhase] = useState<'form' | 'sending' | 'waiting' | 'failed'>('form');
  const [cmd, setCmd] = useState<SessionCommand | null>(null);
  const [sid, setSid] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const started = useRef(0);

  // Keep the selection valid: only online devices can start a session.
  useEffect(() => {
    const cur = devices[deviceId];
    if (cur && cur.presence.state === 'online') return;
    const first = list.find((d) => d.presence.state === 'online');
    setDeviceId(first?.id ?? '');
  }, [devices, list, deviceId]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!deviceId || !goal.trim()) return;
    setPhase('sending'); setProblem(null);
    const c = await sendCommand('START', { goal: goal.trim(), permission_policy: policy }, { deviceId }) as (SessionCommand & { session_id?: string }) | null;
    if (!c) { setPhase('form'); return; }
    setCmd(c); setSid(c.session_id ?? null);
    started.current = Date.now();
    setPhase('waiting');
  }

  // The session announces itself on the user socket (`session` frame). A slow fallback check covers a missed frame.
  useEffect(() => {
    if (phase !== 'waiting' || !sid) return;
    if (sessionIndex[sid]) { navigate(`/session/${sid}`, { replace: true }); return; }
  }, [phase, sid, sessionIndex, navigate]);

  useEffect(() => {
    if (phase !== 'waiting' || !cmd) return;
    let stop = false;
    const tick = async () => {
      if (stop) return;
      try {
        const latest = await api.command(cmd.command_id);
        if (stop) return;
        setCmd((prev) => (prev ? { ...prev, ...latest } : latest));
        if (['failed', 'expired', 'denied', 'cancelled'].includes(latest.status)) {
          setProblem(String((latest.result as { error?: string } | null)?.error ?? (latest.status === 'expired' ? 'The device did not pick up the request in time.' : 'The device could not start the session.')));
          setPhase('failed'); return;
        }
        const id = sid ?? (latest as { session_id?: string }).session_id;
        if (id) {
          try { await api.live(id); navigate(`/session/${id}`, { replace: true }); return; } catch { /* not created yet */ }
        }
      } catch { /* transient; try again */ }
      if (Date.now() - started.current > MAX_WAIT_MS) { setProblem('The session did not appear. The device may have gone offline.'); setPhase('failed'); return; }
      timer = setTimeout(tick, 4000);
    };
    let timer = setTimeout(tick, 2500);
    return () => { stop = true; clearTimeout(timer); };
  }, [phase, cmd?.command_id, sid, navigate]); // eslint-disable-line react-hooks/exhaustive-deps

  if (phase === 'waiting' || phase === 'failed') {
    const steps: Array<[string, boolean]> = [['Request sent', true], ['Reached your device', !!cmd && cmd.status !== 'queued'], ['Session running', false]];
    return (
      <div className="narrow-page">
        <h1>{phase === 'failed' ? 'The session did not start' : 'Starting your session'}</h1>
        <div className="panel start-progress">
          <p className="start-goal">{goal}</p>
          <ol className="steps">
            {steps.map(([label, done], i) => <li key={label} className={done ? 'is-done' : i === steps.findIndex(([, d]) => !d) && phase === 'waiting' ? 'is-now' : ''}>{label}</li>)}
          </ol>
          {cmd && <p className="small">Command <CommandChip status={cmd.status} /></p>}
          {phase === 'waiting' && <p className="muted small" role="status"><Spinner label="Waiting for the session" /> Waiting for your device to begin. This usually takes a few seconds.</p>}
          {problem && <p className="banner banner-bad" role="alert">{problem}</p>}
          {phase === 'failed' && <div className="row-actions"><button className="btn btn-primary" onClick={() => { setPhase('form'); setCmd(null); setSid(null); }}>Try again</button></div>}
        </div>
      </div>
    );
  }

  return (
    <div className="narrow-page">
      <h1>Start a session</h1>
      {!loaded ? <Spinner /> : (
        <form className="panel form start-form" onSubmit={submit}>
          <fieldset className="field-group">
            <legend>Which computer?</legend>
            {list.length === 0 ? <EmptyState title="No devices">Sign in from a terminal to add one.</EmptyState> : (
              <div className="device-picker" role="radiogroup">
                {list.map((d) => {
                  const ok = d.presence.state === 'online';
                  return (
                    <label key={d.id} className={`pick ${deviceId === d.id ? 'is-on' : ''} ${ok ? '' : 'is-disabled'}`}>
                      <input type="radio" name="device" value={d.id} checked={deviceId === d.id} disabled={!ok} onChange={() => setDeviceId(d.id)} />
                      <span className="pick-body">
                        <strong>{d.name}</strong>
                        <span className="muted small">{d.os} on {d.architecture}</span>
                      </span>
                      <span className="pick-side">
                        <PresenceDot state={d.presence.state} />
                        {!ok && <span className="small muted">{d.presence.state === 'degraded' ? 'Fix issues on the device first' : 'Turn it on to start'}</span>}
                      </span>
                    </label>
                  );
                })}
              </div>
            )}
          </fieldset>
          <label className="field">
            <span>What are you working on?</span>
            <textarea required maxLength={500} rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="Finish the retry logic for the sync client and get the tests passing" />
            <small className="muted">{goal.length}/500. FLOW keeps you and its agent pointed at this.</small>
          </label>
          <fieldset className="field-group">
            <legend>What may the agent do without asking?</legend>
            <div className="policy-picker" role="radiogroup">
              {POLICIES.map((p) => (
                <label key={p} className={`pick ${policy === p ? 'is-on' : ''}`}>
                  <input type="radio" name="policy" value={p} checked={policy === p} onChange={() => setPolicy(p)} />
                  <span className="pick-body"><strong>{POLICY_LABEL[p]!.name}</strong><span className="muted small">{POLICY_LABEL[p]!.hint}</span></span>
                </label>
              ))}
            </div>
          </fieldset>
          <button className="btn btn-primary btn-lg" disabled={!deviceId || !goal.trim() || phase === 'sending'}>{phase === 'sending' ? 'Sending' : 'Start session'}</button>
          {!deviceId && list.length > 0 && <p className="hint hint-warn">No device is online right now.</p>}
        </form>
      )}
    </div>
  );
}
