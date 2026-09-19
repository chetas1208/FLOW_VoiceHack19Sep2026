import {Canvas,useFrame,useThree} from '@react-three/fiber';
import {useEffect,useRef,useState} from 'react';
import {Color,Group,Mesh,MeshStandardMaterial,MathUtils} from 'three';
import type {RingsProps} from '../components/Nucleus';
import {ringColors} from '../components/Nucleus';
function Ring({value,index,color,reduced,onClick}:{value:number|null;index:number;color:string;reduced:boolean;onClick:()=>void}){
 const mesh=useRef<Mesh>(null);const glow=useRef<Mesh>(null);const current=useRef(value??0);const [sweep,setSweep]=useState(value??0);const [hover,setHover]=useState(false);const {invalidate}=useThree();
 useEffect(()=>{if(reduced){current.current=value??0;setSweep(value??0);}invalidate();},[value,reduced,color,invalidate]);
 useFrame((_,dt)=>{if(Math.abs(current.current-(value??0))>.08){current.current=MathUtils.damp(current.current,value??0,4,Math.min(dt,.1));setSweep(current.current);invalidate();}if(mesh.current){const mat=mesh.current.material as MeshStandardMaterial;const target=new Color(color);if(!mat.color.equals(target)){mat.color.lerp(target,.1);mat.emissive.copy(mat.color);invalidate();}}});
 const radius=2.65-index*.31;
 return <group rotation={[index*.045,index*.045,-.5+index*.28]} position={[0,0,index*.08]}><mesh><torusGeometry args={[radius,.025,8,160]}/><meshStandardMaterial color="#1e314b" metalness={.7} roughness={.4}/></mesh><mesh ref={mesh} onClick={e=>{e.stopPropagation();onClick();}} onPointerOver={()=>setHover(true)} onPointerOut={()=>setHover(false)}><torusGeometry args={[radius,hover?.055:.038,12,140,Math.PI*2*Math.max(.002,sweep/100)]}/><meshStandardMaterial color={color} emissive={color} emissiveIntensity={hover?2:1.15} transparent opacity={value==null?.1:1} metalness={.35} roughness={.22}/></mesh><mesh ref={glow}><torusGeometry args={[radius,.09,8,140,Math.PI*2*Math.max(.002,sweep/100)]}/><meshBasicMaterial color={color} transparent opacity={value==null?0:.06} depthWrite={false}/></mesh></group>;
}
function Scene({values,state,reduced,pulse,onSelect}:RingsProps){
 const group=useRef<Group>(null);const pulseMesh=useRef<Mesh>(null);const pulseAt=useRef(-10000);const {invalidate}=useThree();
 useEffect(()=>{if(pulse){pulseAt.current=performance.now();invalidate();}},[pulse,invalidate]);
 useFrame(()=>{if(!pulseMesh.current)return;const t=(performance.now()-pulseAt.current)/1800;const mat=pulseMesh.current.material as MeshStandardMaterial;mat.opacity=!reduced&&t>=0&&t<1?(1-t)*.6:0;if(t>=0&&t<1&&!reduced){pulseMesh.current.scale.setScalar(1+t*.1);invalidate();}});
 const away=state==='INTERVENE'?'#fb7185':['WATCHING','DRIFT_CANDIDATE'].includes(state)?'#fbbf24':state==='RECOVERY'?'#a3e635':null;
 return <group ref={group} rotation={[-.26,.2,.15]}><ambientLight intensity={1}/><pointLight position={[3,4,6]} intensity={35} color="#b8ecff"/>{values.map((v,i)=><Ring key={i} index={i} value={v} color={away??ringColors[i]} reduced={reduced} onClick={()=>onSelect(i)}/>)}<mesh ref={pulseMesh}><torusGeometry args={[2.93,.045,10,160]}/><meshStandardMaterial color="#ec4899" emissive="#ec4899" emissiveIntensity={2} transparent opacity={0}/></mesh></group>;
}
export default function Spatial(props:RingsProps&{visible:boolean}){return <Canvas camera={{position:[0,0,7.8],fov:48}} dpr={[1,1.5]} frameloop={props.visible?'demand':'never'} gl={{alpha:true,antialias:true,powerPreference:'low-power'}} aria-hidden="true"><Scene {...props}/></Canvas>;}
