import {useMemo} from 'react';
import {Area,AreaChart,Bar,BarChart,CartesianGrid,Cell,Pie,PieChart,ReferenceDot,ResponsiveContainer,Tooltip,XAxis,YAxis} from 'recharts';
import type {DemoBucket,DemoState} from '../lib/demo-data';
import {demoColors,demoLabels} from '../lib/demo-data';

const fmtT=(t:number)=>`${Math.floor(t/60)}:${String(t%60).padStart(2,'0')}`;
const axisTick={fill:'#64748b',fontSize:10};

function ChartTip({active,payload,label}:{active?:boolean;payload?:{name?:string;value?:number|string;color?:string}[];label?:number|string}){
 if(!active||!payload?.length)return null;
 return <div className="chart-tip">{typeof label==='number'&&<strong>{fmtT(label)}</strong>}{payload.map((p,i)=><span key={i} style={{color:p.color||'#f8fafc'}}>{p.name}: {typeof p.value==='number'?Math.round(p.value*10)/10:p.value}</span>)}</div>;
}

function Spark({id,data,color}:{id:string;data:number[];color:string}){
 return <div className="spark"><ResponsiveContainer width="100%" height="100%">
  <AreaChart data={data.map((v,i)=>({i,v}))} margin={{top:2,right:0,bottom:0,left:0}}>
   <defs><linearGradient id={id} x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={color} stopOpacity={0.5}/><stop offset="100%" stopColor={color} stopOpacity={0}/></linearGradient></defs>
   <Area dataKey="v" name="Level" stroke={color} strokeWidth={1.5} fill={`url(#${id})`} isAnimationActive={false}/>
  </AreaChart>
 </ResponsiveContainer></div>;
}

function kpis(buckets:DemoBucket[]){
 const win=buckets.slice(-30);
 const avg=win.reduce((n,b)=>n+b.relevance,0)/Math.max(1,win.length);
 let streak=0,best=0;
 for(const b of buckets){if(b.relevance>=60){streak++;best=Math.max(best,streak);}else streak=0;}
 const switches=win.reduce((n,b)=>n+b.switches,0)/Math.max(1,win.length);
 return{
  score:Math.round(avg*0.6+Math.min(100,best/Math.max(1,buckets.length)*100)*0.4),
  alignment:Math.round(avg),
  continuity:Math.round(Math.min(100,best/Math.max(1,buckets.length)*100)),
  stability:Math.round(Math.max(20,100-switches*18)),
 };
}

export function Dashboard({state}:{state:DemoState}){
 const k=useMemo(()=>kpis(state.buckets),[state.buckets]);
 const totals=useMemo(()=>Object.keys(demoColors).map(key=>({key,name:demoLabels[key],value:Math.round(state.buckets.reduce((n,b)=>n+(b.minutes[key]||0),0))})),[state.buckets]);
 const interventions=useMemo(()=>state.buckets.filter(b=>b.intervention).slice(-4).reverse(),[state.buckets]);
 const totalMin=totals.reduce((n,x)=>n+x.value,0);
 const spark=(sel:(b:DemoBucket)=>number)=>state.buckets.slice(-30).map(sel);
 const cards:{label:string;value:number;color:string;data:number[]}[]=[
  {label:'Session score',value:k.score,color:'#67a5ff',data:spark(b=>b.relevance)},
  {label:'Goal alignment',value:k.alignment,color:'#22d3ee',data:spark(b=>b.relevance)},
  {label:'Focus continuity',value:k.continuity,color:'#a3e635',data:spark(b=>b.relevance)},
  {label:'Context stability',value:k.stability,color:'#ac8cff',data:spark(b=>Math.max(20,100-b.switches*18))},
 ];
 return <>
  <section className="kpi-row">
   {cards.map(c=><section className="panel kpi-card" key={c.label}><div className="kpi-top"><span>{c.label}</span><strong className="tnum">{c.value}</strong></div><Spark id={'sp'+c.label} data={c.data} color={c.color}/><small>simulated · updates live</small></section>)}
  </section>
  <section className="demo-grid">
   <section className="panel"><div className="panel-heading"><div><span className="eyebrow">ATTENTION OVER TIME</span><h2>Goal relevance, minute by minute</h2></div><span className="tiny">PINK MARKS · COACH INTERVENTIONS</span></div>
    <div className="chart-body tall"><ResponsiveContainer width="100%" height="100%">
     <AreaChart data={state.buckets} margin={{top:8,right:8,left:-18,bottom:0}}>
      <defs><linearGradient id="relGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#22d3ee" stopOpacity={0.35}/><stop offset="100%" stopColor="#22d3ee" stopOpacity={0.02}/></linearGradient></defs>
      <CartesianGrid stroke="rgba(148,163,184,.1)" strokeDasharray="3 6" vertical={false}/>
      <XAxis dataKey="t" tickFormatter={fmtT} tick={axisTick} tickLine={false} axisLine={{stroke:'rgba(148,163,184,.15)'}} minTickGap={44}/>
      <YAxis domain={[0,100]} tick={axisTick} tickLine={false} axisLine={false} width={36}/>
      <Tooltip content={<ChartTip/>} cursor={{stroke:'rgba(34,211,238,.35)'}}/>
      <Area type="monotone" dataKey="relevance" name="Relevance" stroke="#22d3ee" strokeWidth={2} fill="url(#relGrad)" isAnimationActive={false}/>
      {interventions.map(b=><ReferenceDot key={b.t} x={b.t} y={b.relevance} r={4} fill="#ec4899" stroke="#0a0d14" strokeWidth={2}/>)}
     </AreaChart>
    </ResponsiveContainer></div>
   </section>
   <section className="panel"><span className="eyebrow">WHERE TIME WENT</span><h2>Observed minutes by category</h2>
    <div className="donut-wrap"><ResponsiveContainer width="100%" height="100%">
     <PieChart>
      <Pie data={totals} dataKey="value" nameKey="name" innerRadius="58%" outerRadius="82%" paddingAngle={3} stroke="none" isAnimationActive={false}>
       {totals.map(t=><Cell key={t.key} fill={demoColors[t.key]}/>)}
      </Pie>
      <Tooltip content={<ChartTip/>}/>
     </PieChart>
    </ResponsiveContainer><div className="donut-center"><strong className="tnum">{totalMin}m</strong><small>observed</small></div></div>
    <div className="legend-col">{totals.map(t=><span key={t.key}><i style={{background:demoColors[t.key]}}/>{t.name}<b className="tnum">{t.value}m</b></span>)}</div>
   </section>
   <section className="panel"><div className="panel-heading"><div><span className="eyebrow">TASK SWITCHING</span><h2>Context switches per minute</h2></div></div>
    <div className="chart-body"><ResponsiveContainer width="100%" height="100%">
     <BarChart data={state.buckets} margin={{top:8,right:8,left:-22,bottom:0}}>
      <CartesianGrid stroke="rgba(148,163,184,.1)" strokeDasharray="3 6" vertical={false}/>
      <XAxis dataKey="t" tickFormatter={fmtT} tick={axisTick} tickLine={false} axisLine={{stroke:'rgba(148,163,184,.15)'}} minTickGap={44}/>
      <YAxis allowDecimals={false} tick={axisTick} tickLine={false} axisLine={false} width={36}/>
      <Tooltip content={<ChartTip/>} cursor={{fill:'rgba(148,163,184,.06)'}}/>
      <Bar dataKey="switches" name="Switches" fill="#67a5ff" radius={[3,3,0,0]} isAnimationActive={false}/>
     </BarChart>
    </ResponsiveContainer></div>
   </section>
   <section className="panel"><span className="eyebrow">THE COACH IN THE LOOP</span><h2>Recent interventions</h2>
    {interventions.length?interventions.map(b=><article className="intervention-review demo-intervention" key={b.t}><p className="quote">“{b.intervention}”</p><span className="tiny">AT {fmtT(b.t)} · RELEVANCE {Math.round(b.relevance)}%</span></article>):<p className="muted">No interventions in the current window.</p>}
    <p className="muted">Simulated transcripts for demonstration — the production coach is configurable, opt-in and always cooldown-bound.</p>
   </section>
  </section>
 </>;
}
