import { GaussianSplat } from 'three/addons/objects/GaussianSplat.js';
import { createThreeViewer as createViewer } from './three-bridge.mjs';

export function createSplatViewer(options, Loader) {
  function loadSplats(payload) {
    const raw = Uint8Array.from(atob(payload.bytes), char => char.charCodeAt(0));
    const geometry = new Loader().parse(raw.buffer);
    try {
      const model = new GaussianSplat(geometry);
      return {
        model,
        dispose() {
          model.removeFromParent();
          model.material.dispose();
          model.geometry.dispose();
          geometry.dispose();
        }
      };
    } catch (error) {
      geometry.dispose();
      throw error;
    }
  }
  return createViewer({...options, loadSplats});
}
