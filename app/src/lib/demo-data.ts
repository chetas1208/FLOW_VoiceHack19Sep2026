import {useEffect,useState} from 'react';
import type {Category} from './types';

export interface DemoNode{id:string;app:string;title:string;category:Category;relevance:number;ring:number;angle:number}
export interface DemoBucket{t:number;relevance:number;minutes:Record<string,number>;switches:number;intervention?:string}
export interface DemoState{buckets:DemoBucket[];nodes:DemoNode[];tick:number}

const TRANSCRIPTS=[
 'Your goal was the JWT fix — the failing tests are still open. Want to park this tab and come back?',
 'You have been drifting for a few minutes. One small step back to the failing test?',
 'That looked like a quick check that grew. When you are ready, the auth suite is waiting.',
];

function mulberry32(a:number){return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296;};}

const APPS:[string,string,Category][]=[
 ['VS Code','auth/middleware.ts — JWT refactor','core'],
 ['VS Code','token expiry — failing tests','core'],
 ['Terminal','npm test — auth suite','core'],
 ['Chrome','RFC 8725 — JWT best practices','supporting'],
 ['Chrome','JWT expiration documentation','supporting'],
 ['Notion','session notes — auth fix','supporting'],
 ['Slack','#standup — quick sync','drift'],
 ['Slack','#random — memes','distraction'],
 ['X','timeline scroll','distraction'],
 ['Mail','inbox zero attempt','drift'],
 ['Figma','unrelated landing page','distraction'],
 ['Spotify','focus playlist','recovery'],
 ['Terminal','git rebase -i main','core'],
 ['Docs','platform changelog','supporting'],
];

export const demoColors:Record<string,string>={core:'#a3e635',supporting:'#22d3ee',drift:'#fbbf24',distraction:'#fb7185',recovery:'#b9a0ff'};
export const demoLabels:Record<string,string>={core:'Core task',supporting:'Supporting',drift:'Drifting',distraction:'Distraction',recovery:'Recovery'};

function nodeFor([app,title,category]:[string,string,Category],i:number,rand:()=>number):DemoNode{
 const relevance=category==='core'?82+rand()*16:category==='supporting'?58+rand()*26:category==='recovery'?38+rand()*20:rand()*36;
 return{id:'n'+i,app,title,category,relevance,ring:i%3,angle:rand()*Math.PI*2};
}
function relevanceStep(prev:number,rand:()=>number,tick:number){
 let v=prev+(rand()-0.48)*7;
 if(tick%17===8)v-=20;
 if(tick%17===12)v+=18;
 return Math.max(8,Math.min(98,v));
}
function bucketFor(t:number,relevance:number,tick:number,rand:()=>number):DemoBucket{
 const j=(base:number,spread:number)=>Math.max(0,base+(rand()-0.5)*spread);
 return{t,relevance,
  minutes:{
   core:j(relevance/100*0.62,0.16),
   supporting:j(0.16,0.08),
   drift:j(relevance<55?0.14:0.06,0.06),
   distraction:j(relevance<45?0.12:0.04,0.05),
   recovery:j(0.03,0.04),
  },
  switches:Math.min(5,Math.round(rand()*1.6+(relevance<50?1.8:0))),
  intervention:tick%17===8?TRANSCRIPTS[Math.floor(tick/17)%TRANSCRIPTS.length]:undefined,
 };
}
export function seedDemo():DemoState{
 const rand=mulberry32(20260919);
 const nodes=APPS.map((a,i)=>nodeFor(a,i,rand));
 const buckets:DemoBucket[]=[];
 let relevance=76;
 for(let tick=0;tick<48;tick++){relevance=relevanceStep(relevance,rand,tick);buckets.push(bucketFor(tick*60,relevance,tick,rand));}
 return{buckets,nodes,tick:48};
}
export function nextBucket(s:DemoState):DemoState{
 const rand=mulberry32(20260919+s.tick);
 const prev=s.buckets.at(-1)!;
 const relevance=relevanceStep(prev.relevance,rand,s.tick);
 const b=bucketFor(prev.t+60,relevance,s.tick,rand);
 return{...s,tick:s.tick+1,buckets:[...s.buckets.slice(-59),b]};
}
export function useDemoStream():DemoState{
 const [state,setState]=useState(seedDemo);
 useEffect(()=>{const t=setInterval(()=>{if(!document.hidden)setState(nextBucket);},2500);return()=>clearInterval(t);},[]);
 return state;
}
