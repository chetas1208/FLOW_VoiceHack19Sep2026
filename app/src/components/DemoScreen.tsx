import {Component,lazy,Suspense,useEffect,useState, type ReactNode} from 'react';
import {useDemoStream,demoColors,demoLabels} from '../lib/demo-data';
import type {DemoNode} from '../lib/demo-data';

const DemoScene=lazy(()=>import('../three/DemoScene'));
const Dashboard=lazy(()=>import('./Dashboard').then(m=>({default:m.Dashboard})));

class Boundary extends Component<{children:ReactNode;fallback:ReactNode},{failed:boolean}>{state={failed:false};static getDerivedStateFromError(){return{failed:true};}render(){return this.state.failed?this.props.fallback:this.props.children;}}

export function DemoScreen(){
 const state=useDemoStream();
 const [selected,setSelected]=useState<DemoNode|null>(null);
 const [reduced,setReduced]=useState(()=>matchMedia('(prefers-reduced-motion: reduce)').matches);
 useEffect(()=>{const m=matchMedia('(prefers-reduced-motion: reduce)');const change=()=>setReduced(m.matches);m.addEventListener('change',change);return()=>m.removeEventListener('change',change);},[]);
 const legend=Object.keys(demoColors).map(key=>({key,label:demoLabels[key],count:state.nodes.filter(n=>n.category===key).length}));
 return <>
  <div className="page-heading"><div><span className="eyebrow">THE UI, IN MOTION</span><h1>Experience FLOW.</h1><p>A live, simulated walkthrough of the interface: an orbital map of your attention, and the dashboard that explains it — no session data required.</p></div><span className="badge neutral">Simulated data</span></div>
  <section className="panel demo-hero">
   <div className="demo-stage">
    <Boundary fallback={<div className="empty compact">3D view is unavailable on this device.</div>}>
     <Suspense fallback={<div className="empty compact">Loading the cockpit…</div>}>
      <DemoScene nodes={state.nodes} reduced={reduced} selected={selected} onSelect={setSelected}/>
     </Suspense>
    </Boundary>
    <span className="demo-hint">Drag to orbit · scroll to zoom · click a node</span>
   </div>
   <aside className="demo-side">
    <div><span className="eyebrow">ORBITAL SESSION MAP</span><p className="muted">Each node is an observed application, colored by classification and orbiting your session goal at the center.</p></div>
    <div className="demo-legend">{legend.map(l=><span key={l.key}><i style={{background:demoColors[l.key]}}/>{l.label}<b className="tnum">{l.count}</b></span>)}</div>
    {selected
     ?<div className="node-detail"><span className="badge"><i style={{background:demoColors[selected.category]}}/>{demoLabels[selected.category]}</span><h3>{selected.app}</h3><p>{selected.title}</p><div className="bar-track"><div style={{width:`${Math.round(selected.relevance)}%`,background:demoColors[selected.category]}}/></div><small>{Math.round(selected.relevance)}% goal relevance · simulated</small></div>
     :<p className="muted">Select a node to inspect its classification and relevance.</p>}
   </aside>
  </section>
  <Suspense fallback={<div className="empty compact">Preparing the dashboard…</div>}>
   <Dashboard state={state}/>
  </Suspense>
 </>;
}
