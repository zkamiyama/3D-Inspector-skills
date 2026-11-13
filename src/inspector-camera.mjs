import { OrthographicCamera, PerspectiveCamera, Vector3 } from 'three/webgpu';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const directions = {
  iso: [1, 1, 1], front: [0, 0, 1], back: [0, 0, -1],
  right: [1, 0, 0], left: [-1, 0, 0], top: [0, 1, 0], bottom: [0, -1, 0]
};

export function createInspectorCamera(canvas, center, radius, onChange) {
  const near = Math.max(.00001, radius * .001);
  const far = Math.max(50, radius * 120);
  const perspective = new PerspectiveCamera(40, 1, near, far);
  const ortho = new OrthographicCamera(-1, 1, 1, -1, near, far);
  const tangent = Math.tan(perspective.fov * Math.PI / 360);
  let active = perspective;
  let orthoHalfHeight = radius;
  const controls = new OrbitControls(active, canvas);
  controls.screenSpacePanning = true;
  controls.minDistance = radius * .16;
  controls.maxDistance = radius * 75;
  controls.target.copy(center);
  controls.addEventListener('change', onChange);

  function aspectRatio() {
    return Math.max(1, canvas.clientWidth) / Math.max(1, canvas.clientHeight);
  }

  function resize() {
    const aspect = aspectRatio();
    perspective.aspect = aspect;
    perspective.updateProjectionMatrix();
    ortho.top = orthoHalfHeight;
    ortho.bottom = -orthoHalfHeight;
    ortho.right = orthoHalfHeight * aspect;
    ortho.left = -ortho.right;
    ortho.updateProjectionMatrix();
    controls.minZoom = orthoHalfHeight / (controls.maxDistance * tangent);
    controls.maxZoom = orthoHalfHeight / (controls.minDistance * tangent);
  }

  function setDirection(dir, distance) {
    active.position.copy(controls.target).addScaledVector(dir, distance);
    controls.update();
  }

  function fit() {
    const limitingAngle = Math.atan(tangent * Math.min(1, aspectRatio()));
    const distance = radius * 1.05 / Math.sin(limitingAngle);
    const direction = active.position.clone().sub(controls.target).normalize();
    controls.target.copy(center);
    orthoHalfHeight = distance * tangent;
    ortho.zoom = 1;
    resize();
    setDirection(direction, distance);
    onChange();
  }

  function view(key) {
    if (!(key in directions)) return;
    const direction = new Vector3(...directions[key]).normalize();
    setDirection(direction, active.position.distanceTo(controls.target));
  }

  function projection(useOrtho) {
    if (useOrtho === (active === ortho)) return;
    const previous = active;
    active = useOrtho ? ortho : perspective;
    active.quaternion.copy(previous.quaternion);
    active.position.copy(previous.position);
    if (useOrtho) {
      orthoHalfHeight = previous.position.distanceTo(controls.target) * tangent;
      ortho.zoom = 1;
    } else {
      const distance = orthoHalfHeight / (ortho.zoom * tangent);
      active.position.sub(controls.target).setLength(distance).add(controls.target);
    }
    resize();
    controls.object = active;
    controls.update();
    onChange();
  }

  function basis() {
    const elements = active.matrix.elements;
    return [0, 4, 8].map(start => elements.slice(start, start + 3));
  }

  function orbit(horizontal, vertical) {
    controls.rotateLeft(horizontal);
    controls.rotateUp(vertical);
  }

  active.position.copy(center).add(new Vector3(1, 1, 1).normalize().multiplyScalar(radius * 3));
  controls.update();
  fit();
  return { get active() { return active; }, fit, view, projection, resize, basis, orbit,
    dispose() { controls.dispose(); } };
}
