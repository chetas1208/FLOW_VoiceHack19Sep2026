import { randomUUID } from 'node:crypto';

export const EXCLUSIONS = ['1Password','Messages','Keychain Access','System Settings'];
export const categories = ['core','supporting','unknown','drift','distraction','recovery'];
export function now(){return new Date().toISOString()}
export function blank(goal, opts={}) {
  if(typeof goal!=='string'||!goal.trim()) throw new Error('A session goal is required');
  return { id:'ses_'+randomUUID().slice(0,8),goal:goal.trim(),startedAt:now(),endedAt:null,status:'live',mode:opts.mode||'manual',captureEnabled:!!opts.observe,score:null,metrics:null,latest:null,events:[],interventions:[],voiceEnabled:false,mutedUntil:null,report:null,lastObservationAt:null,driftSince:null,coachCooldownUntil:null,privacy:{retention:'metadata-only; no screenshots captured',excludedApps:[...EXCLUSIONS],observedFields:['frontmost app','window title (if permitted)']}};
}
export function classify(goal, app='', title='', previousCategory='unknown') {
  const value=(app+' '+title).toLowerCase(), tokens=goal.toLowerCase().match(/[a-z0-9]{3,}/g)||[];
  const stop=new Set(['the','and','get','fix','with','from','into','that','this','for','app','work','test','tests','build','make','passing']);
  const meaningful=tokens.filter(t=>!stop.has(t));
  const match=meaningful.filter(t=>value.includes(t)).length;
  const isDev=/visual studio|vs code|code|terminal|iterm|intellij|pycharm|xcode|cursor/.test(app.toLowerCase());
  const isBrowser=/chrome|safari|firefox|arc|edge/.test(app.toLowerCase());
  const distraction=/youtube|netflix|reddit|instagram|tiktok|facebook|social feed|shopping/.test(value);
  if(distraction && match===0) return {category:'distraction',alignment:0.08,confidence:0.88,reason:'The window title matches a commonly unrelated destination; this may be a false positive.'};
  if(match>0 && isDev) return {category:previousCategory==='distraction'||previousCategory==='drift'?'recovery':'core',alignment:0.93,confidence:Math.min(0.94,0.68+match*0.08),reason:`The development window title contains ${match} goal-related term(s).`};
  if(match>0) return {category:previousCategory==='distraction'||previousCategory==='drift'?'recovery':'supporting',alignment:0.83,confidence:Math.min(0.89,0.61+match*0.08),reason:`The window title contains ${match} goal-related term(s); relevance is inferred, not verified.`};
  if(isDev) return {category:'unknown',alignment:null,confidence:0.35,reason:'A development app is active, but the window title does not establish goal relevance.'};
  if(isBrowser) return {category:'unknown',alignment:null,confidence:0.35,reason:'Browser activity has insufficient evidence to establish goal relevance.'};
  return {category:'unknown',alignment:null,confidence:0.2,reason:'Insufficient metadata to determine whether this activity supports the goal.'};
}
export function addObservation(s,{app,title='',time=now(),classification=null}) {
  if(s.status!=='live') throw new Error('Session is not live');
  if(s.privacy.excludedApps.some(x=>app.toLowerCase()===x.toLowerCase())) return null;
  if(!app||typeof app!=='string')throw new Error('Application name required');
  const last=s.events.filter(e=>e.type==='observation.created').at(-1);
  const c=classification||classify(s.goal,app,title,last?.category||'unknown');
  if(!categories.includes(c.category))throw new Error('Invalid category');
  const e={id:randomUUID(),type:'observation.created',time,app,title,category:c.category,alignment:c.alignment??null,confidence:c.confidence??0,reason:c.reason||'Manual classification',source:classification?'manual':'local-heuristic',retention:s.privacy.retention};
  s.events.push(e);s.latest=e;s.lastObservationAt=time;
  if(e.category==='distraction'||e.category==='drift') s.driftSince??=time; else s.driftSince=null;
  s.metrics=calculate(s);s.score=s.metrics.sessionScore;
  return e;
}
export function calculate(s){
  const a=s.events.filter(e=>e.type==='observation.created');if(!a.length)return null;
  // Event count reflects sampled observations, NOT exact time. We do not claim time-based productivity.
  const known=a.filter(e=>e.category!=='unknown');const aligned=known.filter(e=>['core','supporting','recovery'].includes(e.category));
  const alignment=known.length?Math.round(100*aligned.length/known.length):null;
  const switches=a.slice(1).filter((e,i)=>e.app!==a[i].app).length;
  const focus=known.length?Math.max(0,Math.round(100-100*switches/Math.max(known.length,1))):null;
  const context=a.length>1?Math.max(0,Math.round(100-100*switches/(a.length-1))):null;
  const values=[alignment,focus,context].filter(x=>x!==null);
  const sessionScore=values.length?Math.round(values.reduce((x,y)=>x+y,0)/values.length):null;
  return {alignment,focus,context,sessionScore,confidence:known.length/a.length,knownSamples:known.length,totalSamples:a.length,method:'Illustrative sample-based heuristics, not a validated measure of productivity or attention.'};
}
export function prepareReport(s){
  const all=s.events.filter(e=>e.type==='observation.created');const counts=Object.fromEntries(categories.map(k=>[k,all.filter(e=>e.category===k).length]));
  const minutes=s.endedAt?Math.max(0,Math.round((new Date(s.endedAt)-new Date(s.startedAt))/60000)):0;
  return {generatedAt:now(),goal:s.goal,durationMinutes:minutes,counts,totalSamples:all.length,metrics:calculate(s),outcome:'Not confirmed by user',interventions:s.interventions,events:all,limitations:['Counts represent observation samples, not exact minutes.','Window titles cannot prove intent, task completion, or actual attention.','Scores are unvalidated heuristics and may be unavailable when evidence is insufficient.']};
}
export function maybeIntervene(s,time=now()){
  if(s.status!=='live'||!s.voiceEnabled||!s.driftSince)return null;
  if(s.mutedUntil && new Date(time)<new Date(s.mutedUntil))return null;
  if(s.coachCooldownUntil&&new Date(time)<new Date(s.coachCooldownUntil))return null;
  const elapsed=new Date(time)-new Date(s.driftSince);
  if(elapsed<90000||!s.latest||s.latest.confidence<0.75)return null;
  const msg=`You may have moved away from your goal: ${s.goal}. Want to return to it?`;
  const e={id:randomUUID(),type:'intervention.started',time,transcript:msg,reason:`Sustained classified drift for ${Math.round(elapsed/1000)} seconds; confidence ${s.latest.confidence}.`,observationId:s.latest.id};
  s.interventions.push(e);s.events.push(e);s.coachCooldownUntil=new Date(new Date(time).getTime()+15*60000).toISOString();return e;
}
