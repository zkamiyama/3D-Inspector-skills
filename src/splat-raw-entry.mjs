import { SPLATLoader } from 'three/addons/loaders/SPLATLoader.js';
import { createSplatViewer } from './splat-entry.mjs';

export function createThreeViewer(options) {
  return createSplatViewer(options, SPLATLoader);
}
