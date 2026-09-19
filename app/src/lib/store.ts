import {create} from 'zustand';
import type {Session, Meta, Metrics, Intervention, Analyzer} from './types';
/** Absolute backend origin when the UI is hosted elsewhere (e.g. Vercel → laptop over Tailscale). */
export const API_BASE=(import.meta.env.VITE_API_URL??'').replace(/\/+$/,'');
export async function api<T>(path:string, method='GET', body?:unknown):Promise<T> {
 const r=await fetch(`${API_BASE}/api${path}`,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});
 const data=await r.json(); if(!r.ok) throw new Error(data.error||`Request failed (${r.status})`); return data;
}
interface State {sessions:Session[]; current:Session|null; meta:Meta|null; connection:string; error:string|null; refresh:()=>Promise<void>; select:(id:string)=>Promise<void>; action:(action:string,body?:unknown)=>Promise<Session>; setError:(s:string|null)=>void}
export const useFlow=create<State>((set,get)=>({sessions:[],current:null,meta:null,connection:'Connecting',error:null,
 setError:error=>set({error}),
 refresh:async()=>{const sessions=await api<Session[]>('/sessions');set({sessions});const id=get().current?.id;if(id){if(sessions.some(s=>s.id===id))await get().select(id);else set({current:null});}},
 select:async id=>{const s=await api<Session>('/sessions/'+id);set({current:s});},
 action:async(action,body={})=>{const s=await api<Session>('/sessions/'+get().current!.id+'/'+action,'POST',body);set({current:s});await get().refresh();return s;}
}));
const types=['session.started','session.paused','session.resumed','session.stopped','session.deleted','observation.created','metrics.updated','drift.changed','intervention.triggered','intervention.queued','intervention.speech_started','intervention.speech_completed','intervention.failed','intervention.muted','intervention.dismissed','intervention.updated','analyzer.status','observer.status','privacy.changed','voice.changed','report.updated','settings.changed','data.deleted'];
export function connect(){
 const store=useFlow; const fail=(e:unknown)=>store.setState({error:String(e instanceof Error?e.message:e)});
 void store.getState().refresh().catch(fail);void api<Meta>('/meta').then(meta=>store.setState({meta})).catch(fail);
 const stream=new EventSource(`${API_BASE}/api/events`);
 stream.onopen=()=>store.setState({connection:'Connected'});
 stream.onerror=()=>store.setState({connection:navigator.onLine?'Reconnecting':'Offline'});
 const reconcile=(e:MessageEvent)=>{const d=JSON.parse(e.data);if(d.resnapshot)void store.getState().refresh().catch(fail);};
 stream.addEventListener('stream.connected',reconcile);
 for(const type of types)stream.addEventListener(type,(event:MessageEvent)=>{
  const d=JSON.parse(event.data) as {session?:Session;sessionId?:string;metrics?:Metrics;intervention?:Intervention;analyzer?:Analyzer};
  const state=store.getState();let current=state.current;
  if(d.session && d.session.id===current?.id)current=d.session;
  if(d.sessionId===current?.id && current){if(d.metrics)current={...current,metrics:d.metrics};if(d.intervention)current={...current,interventions:[...current.interventions.filter(i=>i.id!==d.intervention!.id),d.intervention]};}
  if(type==='session.deleted'&&d.sessionId===current?.id||type==='data.deleted')current=null;
  store.setState({current,...(d.analyzer&&state.meta?{meta:{...state.meta,analyzer:d.analyzer}}:{})});
  if(type.startsWith('session.')||type==='data.deleted')void store.getState().refresh().catch(fail);
 });
 return()=>stream.close();
}
export const labels:Record<string,string>={core:'Core task',supporting:'Supporting task',unknown:'Unknown',drift:'Drifting',distraction:'Distraction',recovery:'Recovery',unobserved:'Not observed',paused:'Paused'};
export const colors:Record<string,string>={core:'#a3e635',supporting:'#22d3ee',unknown:'#94a3b8',drift:'#fbbf24',distraction:'#fb7185',recovery:'#b9a0ff',unobserved:'#526078',paused:'#94a3b8'};
export const duration=(ms:number|null|undefined)=>{if(ms==null)return 'No data';const t=Math.max(0,Math.floor(ms/1000));return `${Math.floor(t/3600)?Math.floor(t/3600)+':':''}${String(Math.floor(t/60)%60).padStart(2,'0')}:${String(t%60).padStart(2,'0')}`;};
export const pct=(n:number|null|undefined)=>n==null?'No data':Math.round(n)+'%';
export function navigate(url:string){history.pushState({},'',url);window.dispatchEvent(new PopStateEvent('popstate'));}
