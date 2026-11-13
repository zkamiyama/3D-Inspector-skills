import { build } from 'esbuild';
import { dirname, resolve } from 'node:path';
import { mkdir, readFile, writeFile } from 'node:fs/promises';

const root=resolve(import.meta.dirname,'..');
const out=resolve(root,'skills/chat-3d-viewer/assets/native-runtime.bundle.js');
await mkdir(dirname(out),{recursive:true});
await build({
  entryPoints:[resolve(root,'src/three-bridge.mjs')],
  outfile:out,
  bundle:true,
  format:'iife',
  globalName:'ChatInspectorThree',
  platform:'browser',
  target:['es2022'],
  minify:true,
  legalComments:'none',
  logLevel:'info',
});
const bytes=(await readFile(out)).length;
console.log('Native bundle bytes:',bytes);
