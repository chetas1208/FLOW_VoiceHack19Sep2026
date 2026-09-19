import {Canvas,useFrame} from '@react-three/fiber';
import {Html,OrbitControls,Stars} from '@react-three/drei';
import {useRef,useState} from 'react';
import {Group,MathUtils,Mesh} from 'three';
import type {DemoNode} from '../lib/demo-data';
import {demoColors,demoLabels} from '../lib/demo-data';

const RADII=[1.9,2.9,3.9];

function Node({node,selected,onSelect}:{node:DemoNode;selected:boolean;onSelect:(n:DemoNode)=>void}){
 const mesh=useRef<Mesh>(null);
 const [hover,setHover]=useState(false);
 const color=demoColors[node.category];
 useFrame((_,dt)=>{
  if(!mesh.current)return;
  const target=hover||selected?2:1;
  mesh.current.scale.setScalar(MathUtils.damp(mesh.current.scale.x,target,8,Math.min(dt,.1)));
 });
 return (
  <mesh
   ref={mesh}
   position={[RADII[node.ring],0,0]}
   onClick={e=>{e.stopPropagation();onSelect(node);}}
   onPointerOver={()=>setHover(true)}
   onPointerOut={()=>setHover(false)}
  >
   <sphereGeometry args={[0.085,20,20]}/>
   <meshStandardMaterial color={color} emissive={color} emissiveIntensity={hover||selected?2.4:1.15} roughness={0.3} metalness={0.2}/>
   {selected&&(
    <Html center distanceFactor={9} zIndexRange={[20,0]} className="node-tag">
     <div className="node-tag" style={{borderColor:color}}>
      <strong>{node.app}</strong>
      <small>{demoLabels[node.category]} · {Math.round(node.relevance)}% relevant</small>
     </div>
    </Html>
   )}
  </mesh>
 );
}

function Ring({ring,nodes,reduced,selectedId,onSelect}:{ring:number;nodes:DemoNode[];reduced:boolean;selectedId:string;onSelect:(n:DemoNode)=>void}){
 const group=useRef<Group>(null);
 useFrame((_,dt)=>{if(group.current&&!reduced)group.current.rotation.y+=dt*(0.14-ring*0.035);});
 const inclination=[0.35,-0.22,0.55][ring];
 return (
  <group ref={group} rotation={[inclination,0,ring*0.42]}>
   <mesh>
    <torusGeometry args={[RADII[ring],0.006,8,180]}/>
    <meshBasicMaterial color="#233047" transparent opacity={0.55}/>
   </mesh>
   {nodes.map(n=>(
    <group key={n.id} rotation={[0,n.angle,0]}>
     <Node node={n} selected={selectedId===n.id} onSelect={onSelect}/>
    </group>
   ))}
  </group>
 );
}

function Core({reduced}:{reduced:boolean}){
 const group=useRef<Group>(null);
 useFrame((state,dt)=>{
  if(!group.current)return;
  if(!reduced){
   group.current.rotation.y+=dt*0.25;
   group.current.rotation.x+=dt*0.07;
   group.current.scale.setScalar(1+Math.sin(state.clock.elapsedTime*1.8)*0.035);
  }
 });
 return (
  <group ref={group}>
   <mesh>
    <icosahedronGeometry args={[0.72,1]}/>
    <meshStandardMaterial color="#22d3ee" emissive="#22d3ee" emissiveIntensity={1.5} wireframe/>
   </mesh>
   <mesh>
    <icosahedronGeometry args={[0.52,2]}/>
    <meshStandardMaterial color="#0e7490" emissive="#22d3ee" emissiveIntensity={0.7} metalness={0.35} roughness={0.25}/>
   </mesh>
  </group>
 );
}

function Rig({reduced,children}:{reduced:boolean;children:React.ReactNode}){
 const group=useRef<Group>(null);
 useFrame((state,dt)=>{
  if(!group.current)return;
  const d=Math.min(dt,.1);
  group.current.rotation.x=MathUtils.damp(group.current.rotation.x,reduced?0.12:-state.pointer.y*0.18,3,d);
  group.current.rotation.y=MathUtils.damp(group.current.rotation.y,reduced?0:state.pointer.x*0.3,3,d);
 });
 return <group ref={group} rotation={[0.12,0,0]}>{children}</group>;
}

function Scene({nodes,reduced,selectedId,onSelect}:{nodes:DemoNode[];reduced:boolean;selectedId:string;onSelect:(n:DemoNode)=>void}){
 const rings=[0,1,2].map(r=>nodes.filter(n=>n.ring===r));
 return (
  <>
   <ambientLight intensity={0.9}/>
   <pointLight position={[4,5,6]} intensity={40} color="#b8ecff"/>
   <pointLight position={[-6,-3,-4]} intensity={26} color="#c4b5fd"/>
   <Rig reduced={reduced}>
    <Core reduced={reduced}/>
    {rings.map((ns,i)=><Ring key={i} ring={i} nodes={ns} reduced={reduced} selectedId={selectedId} onSelect={onSelect}/>)}
   </Rig>
   <Stars radius={70} depth={30} count={1200} factor={2.6} saturation={0} fade speed={reduced?0:0.6}/>
   <OrbitControls enablePan={false} autoRotate={!reduced} autoRotateSpeed={0.5} minDistance={4} maxDistance={12} enableDamping dampingFactor={0.08}/>
  </>
 );
}

export default function DemoScene({nodes,reduced,selected,onSelect}:{nodes:DemoNode[];reduced:boolean;selected:DemoNode|null;onSelect:(n:DemoNode|null)=>void}){
 return (
  <Canvas
   className="demo-canvas"
   camera={{position:[0,2.2,8.2],fov:50}}
   dpr={[1,1.5]}
   gl={{antialias:true,alpha:true,powerPreference:'low-power'}}
   onPointerMissed={()=>onSelect(null)}
  >
   <Scene nodes={nodes} reduced={reduced} selectedId={selected?.id||''} onSelect={onSelect}/>
  </Canvas>
 );
}
