import { createThreeViewer as createViewer } from './three-bridge.mjs';
import { loadNativeBox } from './native-box.mjs';

export function createThreeViewer(options) {
  return createViewer({ ...options, loadNativeBox });
}
