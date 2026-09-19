import {Component,lazy,Suspense,useEffect,useState, type ReactNode} from 'react';
import type {Metrics} from '../lib/types';
const Spatial=lazy(()=>import('../three/Spatial'));
export const metricKeys=['goalAlignment','focusContinuity','contextStability','sessionScore'] as const;
export const metricNames=['Goal alignment','Focus continuity','Context stability','Session score'];
export const ringColors=['#22d3ee','#a3e635','#ac8cff','#67a5ff'];
export interface RingsProps {values:(number|null)[]; state:string; reduced:boolean; pulse:string; onSelect:(index:number)=>void}
function Flat({values,onSelect}:RingsProps){return <svg viewBox="0 0 400 400" className="flat-rings" aria-label="Session metric rings"><defs><filter id="glow"><feGaussianBlur stdDeviation="2"/></filter></defs>{values.map((v,i)=>{const r=162-i*19,c=2*Math.PI*r;return <g key={i} transform="rotate(-90 200 200)"><circle cx="200" cy="200" r={r} fill="none" stroke="#203044" strokeWidth="5" strokeDasharray={v==null?'3 7':undefined}/><circle role="button" tabIndex={0} aria-label={`${metricNames[i]}: ${v??'No data'}. Show explanation`} onClick={()=>onSelect(i)} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();onSelect(i);}}} cx="200" cy="200" r={r} fill="none" stroke={ringColors[i]} opacity={v==null?.15:1} strokeWidth="7" strokeLinecap="round" strokeDasharray={`${c*(v??0)/100} ${c}`} /></g>;})}</svg>}
class Boundary extends Component<{children:ReactNode;fallback:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return{failed:true};}render(){return this.state.failed?this.props.fallback:this.props.children;}}
export function Nucleus({metrics,state,pulse,onSelect}:{metrics:Metrics|null;state:string;pulse:string;onSelect:(index:number)=>void}){
 const [flat,setFlat]=useState(()=>localStorage.getItem('flow-2d')==='true');
 const [reduced,setReduced]=useState(matchMedia('(prefers-reduced-motion: reduce)').matches);
 const [visible,setVisible]=useState(!document.hidden);
 const [values,setValues]=useState(metricKeys.map(k=>metrics?.[k]??null));
 useEffect(()=>{const m=matchMedia('(prefers-reduced-motion: reduce)');const change=()=>setReduced(m.matches);m.addEventListener('change',change);return()=>m.removeEventListener('change',change);},[]);
 useEffect(()=>{const change=()=>setVisible(!document.hidden);document.addEventListener('visibilitychange',change);return()=>document.removeEventListener('visibilitychange',change);},[]);
 useEffect(()=>{const t=setTimeout(()=>setValues(metricKeys.map(k=>metrics?.[k]??null)),values.every(x=>x===null)||reduced?0:5000);return()=>clearTimeout(t);},[metrics,reduced]);
 const props={values,state,reduced,pulse,onSelect};const fallback=<Flat {...props}/>;
 return <section className="panel nucleus"><div className="section-label">SESSION INTELLIGENCE <span className="tiny">{flat?'2D':'SPATIAL'} VIEW</span></div><div className="orb-stage">{flat?fallback:<Boundary fallback={fallback}><Suspense fallback={fallback}><Spatial {...props} visible={visible}/></Suspense></Boundary>}<div className="orb-score"><span className="eyebrow">SESSION SCORE</span><strong className="tnum">{metrics?.sessionScore??'—'}</strong><span>{metrics?.band||'Awaiting observations'}</span><small>Heuristic · not a productivity measure</small></div></div><div className="nucleus-footer"><span>Coverage <b>{metrics?.coverage==null?'No data':Math.round(metrics.coverage*100)+'%'}</b></span><button className="text-button" onClick={()=>{localStorage.setItem('flow-2d',String(!flat));setFlat(!flat);}}>Use {flat?'3D':'2D'} view</button></div></section>;
}
