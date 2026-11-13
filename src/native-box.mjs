// Native six-face Box Impostor restoration via the upstream three-impostor
// shader, rather than sampling six guides into a triangle mesh.
// Texture upload follows ComfyUI-Box-Impostor-Factory/worker/runtime.mjs (MIT).
import * as THREE from 'three/webgpu';
import { ImpostorNodeMaterial } from 'three-impostor';

function decode64(text) {
  const binary=atob(text);
  const out=new Uint8Array(binary.length);
  for(let i=0;i<binary.length;i++)out[i]=binary.charCodeAt(i);
  return out;
}

export async function loadNativeBox(native, renderer) {
  const manifest=native?.manifest;
  if(manifest?.schemaVersion!==1 || manifest.layout!=='box' ||
     !Number.isInteger(manifest.resolution) || manifest.resolution<8 || manifest.resolution>4096 ||
     !Array.isArray(manifest.maps) || !manifest.textures || !native.files) {
    throw new Error('Unsupported native Box manifest');
  }
  const min=manifest.bakeBox?.min,max=manifest.bakeBox?.max;
  if(![min,max].every(x=>Array.isArray(x)&&x.length===3&&x.every(Number.isFinite)) ||
     !min.every((x,i)=>x<max[i])) throw new Error('Invalid native Box bounds');

  const box=new THREE.Box3(new THREE.Vector3(...min),new THREE.Vector3(...max));
  const dimensions=box.getSize(new THREE.Vector3());
  const center=box.getCenter(new THREE.Vector3());
  const geometry=new THREE.BoxGeometry(dimensions.x,dimensions.y,dimensions.z).translate(center.x,center.y,center.z);
  const data={box,geometry,layout:'box',resolution:manifest.resolution,maps:[...manifest.maps]};
  const disposables=[];
  let material;
  try {
    for(const [name,description] of Object.entries(manifest.textures)){
      const encoded=native.files[description.path];
      if(typeof encoded!=='string') throw new Error('Missing native Box texture '+name);
      const bytes=decode64(encoded);
      if(bytes.length!==description.byteLength) throw new Error('Incorrect native Box bytes '+name);
      const typed=description.dtype==='float16'
        ? new Uint16Array(bytes.buffer,bytes.byteOffset,bytes.byteLength/2)
        : description.dtype==='uint8'? bytes : null;
      if(!typed) throw new Error('Unsupported native Box texture dtype '+description.dtype);
      const t=new THREE.DataTexture(typed,description.width,description.height,
          THREE.RGBAFormat,description.dtype==='float16'?THREE.HalfFloatType:THREE.UnsignedByteType);
      const nearest=description.minFilter==='nearest';
      t.minFilter=t.magFilter=nearest?THREE.NearestFilter:THREE.LinearFilter;
      t.flipY=false;
      t.wrapS=t.wrapT=THREE.ClampToEdgeWrapping;
      t.generateMipmaps=false;
      t.colorSpace=THREE.NoColorSpace;
      t.needsUpdate=true;
      // WebGLBackend copies and flips the atlas into an RT in the official
      // Box factory. Reuse those exact semantics for correct thin ray hits.
      if(renderer.backend?.isWebGLBackend){
        const row=description.width*4;
        const flipped=new typed.constructor(typed.length);
        for(let y=0;y<description.height;y++) {
          flipped.set(typed.subarray(y*row,(y+1)*row),(description.height-1-y)*row);
        }
        t.image.data=flipped;
        const rt=new THREE.RenderTarget(description.width,description.height,{
          type:t.type,depthBuffer:false,minFilter:t.minFilter,magFilter:t.magFilter,generateMipmaps:false
        });
        disposables.push(rt);
        try {
          renderer.initRenderTarget(rt);
          renderer.copyTextureToTexture(t,rt.texture);
        } finally {t.dispose();}
        data[name]=rt.texture;
      } else {
        disposables.push(t);
        data[name]=t;
      }
    }
    material=new ImpostorNodeMaterial(data);
    material.steps=Math.max(material.steps,2*manifest.resolution);
    const mesh=new THREE.Mesh(geometry,material);
    mesh.name='Native Box';
    return {
      mesh,
      geometry,
      dispose(){
        mesh.parent?.remove(mesh);
        material.dispose();
        geometry.dispose();
        for(const item of disposables)item.dispose();
      }
    };
  } catch(error) {
    material?.dispose();
    geometry.dispose();
    for(const item of disposables)item.dispose();
    throw error;
  }
}
