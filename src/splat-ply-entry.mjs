import { GaussianSplatPLYLoader } from 'three/addons/loaders/GaussianSplatPLYLoader.js';
import { createSplatViewer } from './splat-entry.mjs';

export function createThreeViewer(options) {
  return createSplatViewer(options, GaussianSplatPLYLoader);
}
