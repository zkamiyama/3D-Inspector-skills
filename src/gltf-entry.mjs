import {createThreeViewer as createViewer} from './three-bridge.mjs';
import {loadNativeGltf} from './native-gltf.mjs';

export function createThreeViewer(options) {
  return createViewer({...options, loadNativeGltf});
}
