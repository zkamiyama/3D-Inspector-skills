import {AnimationMixer, LoadingManager, TextureLoader} from 'three/webgpu';
import {GLTFLoader} from 'three/addons/loaders/GLTFLoader.js';

function playback(clips, root, invalidate) {
  if (!clips.length) return null;
  const mixer = new AnimationMixer(root);
  const panel = document.createElement('div');
  panel.className = 'clip-controls';
  panel.setAttribute('role', 'group');
  panel.setAttribute('aria-label', 'Animation playback');
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.textContent = 'Play';
  const select = document.createElement('select');
  select.setAttribute('aria-label', 'Animation clip');
  clips.forEach((clip, index) => select.add(new Option(clip.name || `Clip ${index + 1}`, index)));
  const seek = document.createElement('input');
  seek.type = 'range';
  seek.min = '0';
  seek.step = 'any';
  seek.setAttribute('aria-label', 'Animation time');
  panel.append(toggle, select, seek);
  document.querySelector('#stage').append(panel);
  let action, playing = false, last = 0;
  function choose() {
    mixer.stopAllAction();
    action = mixer.clipAction(clips[select.selectedIndex]).reset().play();
    seek.max = action.getClip().duration;
    seek.value = '0';
    mixer.update(0);
    last = performance.now();
    invalidate();
  }
  toggle.onclick = () => {
    playing = !playing;
    toggle.textContent = playing ? 'Pause' : 'Play';
    toggle.setAttribute('aria-pressed', String(playing));
    last = performance.now();
    invalidate();
  };
  select.onchange = choose;
  seek.oninput = () => {
    action.time = Number(seek.value);
    // LoopRepeat wraps exactly at duration; leave the endpoint on the last pose.
    if (action.time === action.getClip().duration) action.time = Math.max(0, action.time - 1e-7);
    mixer.update(0);
    last = performance.now();
    invalidate();
  };
  choose();
  return {
    tick() {
      if (!playing) return;
      const now = performance.now();
      mixer.update(Math.min((now - last) / 1000, .25));
      last = now;
      seek.value = action.time;
      invalidate();
    },
    dispose() { panel.remove(); mixer.stopAllAction(); mixer.uncacheRoot(root); }
  };
}

// Build inspector rows from the same primitives and materials Three renders.
function inspector(root) {
  const rows = [], materials = [], textures = [];
  const materialIds = new Map(), textureIds = new Map(), disposables = new Set();
  function textureIndex(texture, role) {
    if (!texture?.image) return -1;
    if (textureIds.has(texture)) return textureIds.get(texture);
    const image = texture.image;
    const size = Math.min(1, 512 / Math.max(image.width, image.height));
    const thumbnail = document.createElement('canvas');
    thumbnail.width = Math.max(1, Math.round(image.width * size));
    thumbnail.height = Math.max(1, Math.round(image.height * size));
    thumbnail.getContext('2d').drawImage(image, 0, 0, thumbnail.width, thumbnail.height);
    const id = textures.length;
    textures.push({image: thumbnail, dataUri: thumbnail.toDataURL(), name: texture.name || role,
      width: image.width, height: image.height, format: texture.userData.mimeType, role});
    textureIds.set(texture, id);
    return id;
  }
  root.traverse(object => {
    if (!object.geometry || !object.material) return;
    const material = object.material;
    disposables.add(object.geometry);
    disposables.add(material);
    if (object.skeleton) disposables.add(object.skeleton);
    for (const value of Object.values(material)) if (value?.isTexture) disposables.add(value);
    if (!materialIds.has(material)) {
      materialIds.set(material, materials.length);
      materials.push({name: material.name || `Material ${materials.length + 1}`,
        baseColor: [...(material.color?.toArray() || [1,1,1]), material.opacity],
        metallic: material.metalness, roughness: material.roughness,
        alphaMode: material.transparent ? 'BLEND' : material.alphaTest ? 'MASK' : 'OPAQUE',
        baseColorTexture: textureIndex(material.map, 'Base color'), normalTexture: textureIndex(material.normalMap, 'Normal'),
        metallicRoughnessTexture: textureIndex(material.metalnessMap || material.roughnessMap, 'Metal / rough'),
        emissiveTexture: textureIndex(material.emissiveMap, 'Emissive'), occlusionTexture: textureIndex(material.aoMap, 'AO')});
    }
    const geom = object.geometry, count = geom.attributes.position.count;
    const indexCount = geom.index?.count ?? count;
    let uv = null;
    // Sidebar UV canvas uses the bottom-left texture origin of exported rows.
    if (geom.attributes.uv) {
      uv = new Float32Array(count * 2);
      for (let i=0; i<count; i++) {uv[i*2] = geom.attributes.uv.getX(i); uv[i*2+1] = 1 - geom.attributes.uv.getY(i);}
    }
    const indices = object.isMesh ? geom.index?.array ?? Uint32Array.from({length:count}, (_, i) => i) : [];
    rows.push({object, original:material, name:object.name || `Primitive ${rows.length+1}`, visible:true,
      positions:{length: count * 3}, indices, uv, material:materialIds.get(material), triangleCount: object.isMesh ? Math.floor(indexCount / 3) : 0});
  });
  return {rows, materials, textures, disposables};
}

export async function loadNativeGltf(payload, invalidate) {
  const bytes = Uint8Array.from(atob(payload.glb), ch => ch.charCodeAt(0));
  const manager = new LoadingManager();
  const loader = new GLTFLoader(manager);
  // All buffers live in GLB's BIN chunk. TextureLoader decodes its blob URLs
  // through <img>, so disabling JS fetch in a sidebar also works for images.
  loader.register(parser => {
    parser.textureLoader = new TextureLoader(manager);
    return {name:'EmbeddedImages'};
  });
  const {scene:root, animations} = await loader.parseAsync(bytes.buffer, '');
  const data = inspector(root);
  const player = playback(animations, root, invalidate);
  return {
    root, inspector: {meshes:data.rows, materials:data.materials, textures:data.textures},
    update(wire, normals, isolated, normalMaterial) {
      player?.tick();
      for (const row of data.rows) {
        row.object.visible = row.visible && (isolated < 0 || row.material === isolated);
        row.object.material = normals && row.object.isMesh ? normalMaterial : row.original;
        if (row.object.isMesh) row.original.wireframe = wire;
      }
    },
    dispose() { player?.dispose(); root.removeFromParent(); for (const item of data.disposables) item.dispose(); }
  };
}
