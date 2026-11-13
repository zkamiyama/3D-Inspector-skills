// Exercise the actual Three.js cameras and OrbitControls without a GPU.
import assert from 'node:assert/strict';
import { Vector3 } from 'three/webgpu';
import { createInspectorCamera } from '../src/inspector-camera.mjs';

const eventRoot = new EventTarget();
const surface = Object.assign(new EventTarget(), {
  ownerDocument: eventRoot, getRootNode: () => eventRoot, style: {}, clientWidth: 390, clientHeight: 760
});
const center = new Vector3(9, -6, 15);
const rig = createInspectorCamera(surface, center, 4, () => {});
const close = (a, b) => assert.ok(Math.abs(a - b) < 1e-5, `${a} should equal ${b}`);
function measureTargetPlane() {
  rig.active.updateMatrixWorld();
  const right = new Vector3(1, 0, 0).applyQuaternion(rig.active.quaternion);
  return center.clone().add(right).project(rig.active).x - center.clone().project(rig.active).x;
}

try {
  let size = measureTargetPlane();
  rig.projection(true);
  close(measureTargetPlane(), size);
  rig.active.zoom *= 2;
  rig.active.updateProjectionMatrix();
  size = measureTargetPlane();
  rig.projection(false);
  close(measureTargetPlane(), size);
  rig.projection(true);
  close(measureTargetPlane(), size);
  rig.projection(false);

  const directions = {
    right:[1,0,0], left:[-1,0,0], top:[0,1,0],
    bottom:[0,-1,0], front:[0,0,1], back:[0,0,-1]
  };
  for (const [key,vector] of Object.entries(directions)) {
    rig.view(key);
    rig.active.updateMatrixWorld();
    const outward = rig.basis()[2];
    vector.forEach((value,index) => close(outward[index], value));
    close(measureTargetPlane(), size);
  }
  rig.orbit(.34, -.18);
  rig.active.updateMatrixWorld();
  assert.ok(rig.basis()[2][2] > -.99);
  const direction = rig.basis()[2];
  rig.fit();
  rig.active.updateMatrixWorld();
  direction.forEach((value,index) => close(rig.basis()[2][index], value));
  const right = new Vector3(...rig.basis()[0]);
  const edge = center.clone().addScaledVector(right, 4).project(rig.active);
  assert.ok(edge.x < 1 && edge.x > .5, 'Frame must account for narrow viewport');
  surface.clientWidth = 1120;
  rig.resize();
  rig.fit();
  rig.projection(true);
  close(center.clone().project(rig.active).x, 0);
  console.log('Camera projection scale, zoom, six directions, orbit and framing passed');
} finally {
  rig.dispose();
}
