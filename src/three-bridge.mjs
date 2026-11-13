// Three.js rendering adapter. The presentation, material and camera
// behavior is provided by Three.js, not by a second hand-written shader.
import * as THREE from 'three/webgpu';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { loadNativeBox } from './native-box.mjs';

const directions={
  iso:[1,.55,1],
  front:[0,0,1],
  back:[0,0,-1],
  left:[-1,0,0],
  right:[1,0,0],
  top:[0,1,0]
};
const nearPositive=x=>Math.max(.00001,x);
const validColor=m=>Array.isArray(m?.baseColor)&&m.baseColor.length>=3
  ? m.baseColor:[1,1,1,1];

export async function createThreeViewer({scene,canvas,meshes,materials,textures,onChange=()=>{}}) {
  // Do not initiate WebGPU in the ChatGPT iframe. WebGL2 is the portable
  // backend that the original Box factory already validates.
  if(!canvas.getContext('webgl2')) throw new Error('WebGL2 is unavailable');
  const renderer=new THREE.WebGPURenderer({
    canvas,forceWebGL:true,alpha:true,antialias:true,preserveDrawingBuffer:true
  });
  let nativeBox;
  const disposables=[], objects=[], mappedMaterials=[];
  try{
    await renderer.init();
    renderer.setPixelRatio(Math.min(2,window.devicePixelRatio||1));
    renderer.outputColorSpace=THREE.SRGBColorSpace;
    renderer.toneMapping=THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure=1;
    renderer.setClearColor(0x000000,0);
    const world=new THREE.Scene();
    const bounds=new THREE.Box3(
      new THREE.Vector3(...scene.bounds.min),new THREE.Vector3(...scene.bounds.max));
    const center=bounds.getCenter(new THREE.Vector3());
    const radius=Math.max(.001,bounds.getSize(new THREE.Vector3()).length()*.5);
    const light=new THREE.DirectionalLight(0xffffff,2.1);
    light.position.copy(center).add(new THREE.Vector3(radius*2,radius*3,radius*2));
    world.add(new THREE.HemisphereLight(0xf7f5ed,0x88888f,1.55),light);

    if(scene.nativeBox){
      nativeBox=await loadNativeBox(scene.nativeBox,renderer);
      world.add(nativeBox.mesh);
      objects.push(nativeBox.mesh);
    }else{
      const threeTextures=[];
      for(const tex of textures) {
        if(!tex.image){threeTextures.push(null);continue;}
        const t=new THREE.Texture(tex.image);
        t.flipY=true;
        t.needsUpdate=true;
        t.wrapS=t.wrapT=THREE.RepeatWrapping;
        t.minFilter=THREE.LinearMipmapLinearFilter;
        t.magFilter=THREE.LinearFilter;
        t.generateMipmaps=true;
        disposables.push(t);
        threeTextures.push(t);
      }
      function mapFor(index,color=false){
        if(!Number.isInteger(index)||index<0||!threeTextures[index])return null;
        const t=threeTextures[index];
        t.colorSpace=color?THREE.SRGBColorSpace:THREE.NoColorSpace;
        return t;
      }
      for(const m of materials){
        const base=validColor(m);
        const alpha=m.alphaMode==='BLEND'||m.alphaMode==='MASK';
        const mat=new THREE.MeshStandardMaterial({
          color:new THREE.Color(base[0],base[1],base[2]),
          metalness:Math.min(1,Math.max(0,m.metallic??0)),
          roughness:Math.min(1,Math.max(.01,m.roughness??1)),
          opacity:base[3]??1,
          side:m.doubleSided?THREE.DoubleSide:THREE.FrontSide,
          transparent:m.alphaMode==='BLEND',
          alphaTest:m.alphaMode==='MASK'?(m.alphaCutoff??.5):0,
          vertexColors:true
        });
        mat.map=mapFor(m.baseColorTexture,true);
        mat.normalMap=mapFor(m.normalTexture);
        mat.metalnessMap=mapFor(m.metallicRoughnessTexture);
        mat.roughnessMap=mapFor(m.metallicRoughnessTexture);
        mat.emissiveMap=mapFor(m.emissiveTexture,true);
        const e=m.emissiveFactor||[0,0,0];
        mat.emissive.setRGB(e[0]||0,e[1]||0,e[2]||0);
        if(Number.isInteger(m.occlusionTexture)&&m.occlusionTexture>=0){
          mat.aoMap=mapFor(m.occlusionTexture);
          mat.aoMapIntensity=1;
        }
        mat.needsUpdate=true;
        mappedMaterials.push(mat);
        disposables.push(mat);
      }
      for(let i=0;i<meshes.length;i++){
        const src=meshes[i],g=new THREE.BufferGeometry();
        g.setAttribute('position',new THREE.BufferAttribute(src.positions,3));
        g.setAttribute('normal',new THREE.BufferAttribute(src.normals,3));
        g.setAttribute('uv',new THREE.BufferAttribute(src.uv,2));
        g.setAttribute('uv2',new THREE.BufferAttribute(src.uv,2));
        g.setAttribute('color',new THREE.BufferAttribute(src.colors,4,true));
        g.setIndex(new THREE.BufferAttribute(src.indices,1));
        g.computeBoundingSphere();
        disposables.push(g);
        const o=new THREE.Mesh(g,mappedMaterials[src.material]||mappedMaterials[0]);
        o.name=src.name;
        o.frustumCulled=false;
        world.add(o);objects.push(o);
      }
    }

    // The bounding cube only appears in Wire mode. It is not an approximation
    // of the ray-marched surface.
    let boundsWire;
    if(nativeBox){
      boundsWire=new THREE.LineSegments(
        new THREE.EdgesGeometry(nativeBox.geometry),
        new THREE.LineBasicMaterial({color:0xd8ccb8,transparent:true,opacity:.83})
      );
      boundsWire.visible=false;world.add(boundsWire);
      disposables.push(boundsWire.geometry,boundsWire.material);
    }
    const fov=40;
    const minNear=nearPositive(radius*.001);
    const far=Math.max(50,radius*120);
    const perspective=new THREE.PerspectiveCamera(fov,1,minNear,far);
    const orthographic=new THREE.OrthographicCamera(-1,1,1,-1,minNear,far);
    let active=perspective;
    const controls=new OrbitControls(active,canvas);
    controls.enableDamping=false;
    controls.screenSpacePanning=true;
    controls.minDistance=radius*.16;
    controls.maxDistance=radius*75;
    controls.target.copy(center);
    controls.addEventListener('change',onChange);
    let cssW=0,cssH=0,projectionMode=false,wireState=false,normalState=false,isolatedIndex=-1;
    const normalMaterial=new THREE.MeshNormalMaterial({side:THREE.DoubleSide});
    disposables.push(normalMaterial);
    let shown=true;

    function setPose(key='iso',distance=null,target=center) {
      const dir=new THREE.Vector3(...(directions[key]||directions.iso)).normalize();
      active.up.set(0,1,0);
      if(key==='top') active.up.set(0,0,-1);
      controls.target.copy(target);
      active.position.copy(target).addScaledVector(dir,distance??Math.max(radius*2.65,radius+.1));
      active.lookAt(target);
      active.updateProjectionMatrix();
      controls.update();
    }
    function fit() {setPose('iso',radius*2.65,center);}
    function view(key) {
      setPose(key,Math.max(active.position.distanceTo(controls.target),radius*.5),controls.target);
    }
    function projection(ortho) {
      if(projectionMode===!!ortho)return;
      const prev=active;
      active=ortho?orthographic:perspective;
      projectionMode=!!ortho;
      active.position.copy(prev.position);
      active.up.copy(prev.up);
      active.quaternion.copy(prev.quaternion);
      controls.object=active;controls.update();
      onChange();
    }
    function draw({wire=false,normals=false,isolated=-1}={}){
      const width=canvas.clientWidth,height=canvas.clientHeight;
      if(!width||!height)return;
      if(width!==cssW||height!==cssH){
        cssW=width;cssH=height;
        renderer.setSize(cssW,cssH,false);
      }
      const aspect=cssW/Math.max(1,cssH);
      perspective.aspect=aspect;perspective.updateProjectionMatrix();
      const distance=active.position.distanceTo(controls.target);
      const half=Math.max(radius*.1,distance*Math.tan(fov*Math.PI/360));
      orthographic.left=-half*aspect;
      orthographic.right=half*aspect;
      orthographic.top=half;
      orthographic.bottom=-half;
      orthographic.updateProjectionMatrix();
      if(nativeBox){
        nativeBox.mesh.visible=shown && !wire && isolated<1;
        boundsWire.visible=shown && wire && isolated<1;
      } else {
        for(let i=0;i<objects.length;i++) {
          const o=objects[i],original=mappedMaterials[meshes[i].material]||mappedMaterials[0];
          o.visible=meshes[i].visible && (isolated<0||meshes[i].material===isolated);
          o.material=normals?normalMaterial:original;
          original.wireframe=wire;
        }
      }
      renderer.render(world,active);
    }
    function setVisible(bool){shown=!!bool;onChange();}
    function dispose(){
      controls.dispose();
      nativeBox?.dispose();
      for(const o of objects)o.parent?.remove(o);
      for(const d of disposables)d.dispose();
      renderer.dispose();
    }
    fit();
    return {draw,fit,view,projection,setVisible,dispose,isBox:!!nativeBox,
      isWebGL2:renderer.backend?.isWebGLBackend===true,
      getRenderer:()=>renderer};
  }catch(error){
    nativeBox?.dispose();
    for(const item of disposables)item.dispose();
    await renderer.dispose();
    throw error;
  }
}
