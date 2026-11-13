import { build } from 'esbuild';
import { resolve } from 'node:path';
import { readFile } from 'node:fs/promises';

const root = resolve(import.meta.dirname, '..');
const entries = {
  native: './box-entry.mjs',
  mesh: './three-bridge.mjs',
  gltf: './gltf-entry.mjs',
  splat: './splat-raw-entry.mjs',
  'splat-ply': './splat-ply-entry.mjs',
};

// r186 projects every covariance with a perspective Jacobian. An orthographic
// camera's screen-space derivative is constant in x/y and zero in z. Keep the
// upstream shader, sorting, SH evaluation and buffers for both backends.
function splatProjection() {
  const path = resolve(root, 'node_modules/three/examples/jsm/objects/GaussianSplat.js');
  return {name:'splat-projection', setup(plugin) {
    plugin.onResolve({filter:/^three\/addons\/objects\/GaussianSplat\.js$/}, () => ({path}));
    plugin.onLoad({filter:/GaussianSplat\.js$/}, async () => {
      let source = await readFile(path,'utf8');
      function replace(from, to) {
        if (!source.includes(from)) throw Error('Recheck the splat projection against the pinned Three.js source.');
        source = source.replace(from,to);
      }
      replace("const j00 = ", "const orthographic = cameraProjectionMatrix[ 2 ].w.equal( 0 );\n\t\tconst j00 = ");
      for (const axis of ['x','y']) {
        const diagonal = `focal.${axis}.negate().mul( invZ )`;
        replace(diagonal, `orthographic.select( focal.${axis}, ${diagonal} )`);
        const depth = `focal.${axis}.mul( viewCenter.${axis} ).mul( invZ2 )`;
        replace(depth, `orthographic.select( 0, ${depth} )`);
      }
      // Keep these dependencies as ordinary addon imports in CDN mode.
      source = source.replaceAll("from '../", "from 'three/addons/");
      return {contents:source, resolveDir:root};
    });
  }};
}

for (const [name, source] of Object.entries(entries)) {
  for (const cdn of [false, true]) {
    const suffix = cdn ? 'cdn.mjs' : 'bundle.js';
    const outfile = resolve(root, 'skills/chat-3d-viewer/assets', name + '-runtime.' + suffix);
    // Both delivery modes share one entry. The CDN build leaves only actual
    // package imports external; esbuild follows local adapter imports.
    const contents = cdn
      ? `import { createThreeViewer } from '${source}';
         globalThis.ChatInspectorThree = { createThreeViewer };
         globalThis.__chat3dCDNReady?.resolve();`
      : `export { createThreeViewer } from '${source}';`;
    await build({
      stdin: { contents, sourcefile: 'runtime-bootstrap.mjs', resolveDir: resolve(root, 'src') },
      plugins: name.startsWith('splat') ? [splatProjection()] : [],
      outfile, bundle: true, packages: cdn ? 'external' : 'bundle',
      format: cdn ? 'esm' : 'iife', globalName: cdn ? undefined : 'ChatInspectorThree',
      platform: 'browser', target: ['es2022'], minify: true, legalComments: 'none',
    });
    console.log(name, suffix, (await readFile(outfile)).length, 'bytes');
  }
}
