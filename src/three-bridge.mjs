// Three.js rendering adapter. The presentation, material and camera
// behavior is provided by Three.js, not by a second hand-written shader.
import * as THREE from 'three/webgpu';
import { createInspectorCamera } from './inspector-camera.mjs';

const validColor=m=>Array.isArray(m?.baseColor)&&m.baseColor.length>=3
  ? m.baseColor:[1,1,1,1];

export async function createThreeViewer({scene,canvas,meshes,materials,textures,loadNativeBox,loadNativeGltf,loadSplats,forceWebGL=false,onChange=()=>{}}) {
  // Asking this canvas for a WebGL2 context here would lock out WebGPU.
  const renderer=new THREE.WebGPURenderer({
    canvas,forceWebGL,alpha:true,antialias:true,preserveDrawingBuffer:true
  });
  let nativeBox,nativeGltf,nativeSplat,camera,initialized=false;
  const disposables=[], objects=[], mappedMaterials=[];
  try{
    await renderer.init();
    initialized=true;
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
    }else if(scene.nativeSplat){
      nativeSplat=loadSplats(scene.nativeSplat);
      world.add(nativeSplat.model);
    }else if(scene.nativeGltf){
      nativeGltf=await loadNativeGltf(scene.nativeGltf,onChange);
      world.add(nativeGltf.root);
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
        if(src.normals) g.setAttribute('normal',new THREE.BufferAttribute(src.normals,3));
        if(src.uv) {
          const uv=new THREE.BufferAttribute(src.uv,2);
          g.setAttribute('uv',uv);
          g.setAttribute('uv1',uv);
        }
        if(src.colors) g.setAttribute('color',new THREE.BufferAttribute(src.colors,4,true));
        if(src.indices.length) g.setIndex(new THREE.BufferAttribute(src.indices,1));
        g.computeBoundingSphere();
        disposables.push(g);
        let o;
        if(src.primitive==='points') {
          const mat=new THREE.PointsMaterial({size:2,sizeAttenuation:false,vertexColors:!!src.colors});
          disposables.push(mat);
          o=new THREE.Points(g,mat);
        } else {
          o=new THREE.Mesh(g,mappedMaterials[src.material]||mappedMaterials[0]);
        }
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
    camera=createInspectorCamera(canvas,center,radius,onChange);
    let cssW=0,cssH=0;
    const normalMaterial=new THREE.MeshNormalMaterial({side:THREE.DoubleSide});
    disposables.push(normalMaterial);
    let shown=true;

    function draw({wire=false,normals=false,isolated=-1}={}){
      const width=canvas.clientWidth,height=canvas.clientHeight;
      if(!width||!height)return;
      if(width!==cssW||height!==cssH){
        cssW=width;cssH=height;
        renderer.setSize(cssW,cssH,false);
        camera.resize();
      }
      if(nativeBox){
        nativeBox.mesh.visible=shown && !wire && isolated<1;
        boundsWire.visible=shown && wire && isolated<1;
      } else if(nativeSplat){
        nativeSplat.model.visible=meshes[0].visible && isolated<1;
      } else if(nativeGltf){
        nativeGltf.update(wire,normals,isolated,normalMaterial);
      } else {
        for(let i=0;i<objects.length;i++) {
          const o=objects[i],original=mappedMaterials[meshes[i].material]||mappedMaterials[0];
          o.visible=meshes[i].visible && (isolated<0||meshes[i].material===isolated);
          if(o.isPoints) continue;
          o.material=normals?normalMaterial:original;
          original.wireframe=wire;
        }
      }
      renderer.render(world,camera.active);
    }
    function setVisible(bool){shown=!!bool;onChange();}
    function dispose(){
      camera.dispose();
      nativeBox?.dispose();
      nativeGltf?.dispose();
      nativeSplat?.dispose();
      for(const o of objects)o.parent?.remove(o);
      for(const d of disposables)d.dispose();
      renderer.dispose();
    }
    // init() can finish before the canvas, textures and shaders have been
    // used. Catch first-frame errors while the caller can still retry WebGL.
    const device=renderer.backend.isWebGPUBackend ? renderer.backend.device : null;
    device?.pushErrorScope('validation');
    let validation;
    try {
      draw();
    } finally {
      if(device) validation=await device.popErrorScope();
    }
    if(validation) throw new Error(validation.message);
    return {draw,fit:camera.fit,view:camera.view,projection:camera.projection,
      basis:camera.basis,orbit:camera.orbit,setVisible,dispose,isBox:!!nativeBox,
      gltfInspector:nativeGltf?.inspector,
      backend:device?'WebGPU':'WebGL2',
      isWebGL2:renderer.backend?.isWebGLBackend===true,
      getRenderer:()=>renderer};
  }catch(error){
    camera?.dispose();
    nativeBox?.dispose();
    nativeGltf?.dispose();
    nativeSplat?.dispose();
    for(const item of disposables)item.dispose();
    if(initialized) await renderer.dispose();
    throw error;
  }
}
