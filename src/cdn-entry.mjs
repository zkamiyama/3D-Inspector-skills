import { createThreeViewer } from './three-bridge.mjs';

globalThis.ChatInspectorThree={createThreeViewer};
globalThis.__chat3dCDNReady?.resolve();
