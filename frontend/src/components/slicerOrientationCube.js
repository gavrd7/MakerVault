import * as THREE from "three";

/**
 * Interactive, renderer-owned orientation cube for the Z-up model editor.
 * The cube uses a separate scene and the existing WebGL context (no second
 * canvas, animation loop, renderer, or GPU context).
 */
export const ORIENTATION_CUBE_SIZE = 116;
export const ORIENTATION_CUBE_MARGIN = 10;

export const ORIENTATION_FACES = Object.freeze(["right", "left", "rear", "front", "top", "bottom"]);

function faceMaterial(text, fill) {
  const canvas = document.createElement("canvas");
  canvas.width = 128;
  canvas.height = 128;
  const context = canvas.getContext("2d");
  if (context) {
    context.fillStyle = fill;
    context.fillRect(0, 0, 128, 128);
    context.strokeStyle = "#0d1828";
    context.lineWidth = 5;
    context.strokeRect(2, 2, 124, 124);
    context.fillStyle = "#fafcff";
    context.font = "bold 29px system-ui, sans-serif";
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.fillText(text, 64, 66, 116);
  }
  const map = new THREE.CanvasTexture(canvas);
  map.colorSpace = THREE.SRGBColorSpace;
  return new THREE.MeshBasicMaterial({ map, side: THREE.DoubleSide, depthTest: true });
}

export class SlicerOrientationCube {
  constructor(camera, renderer) {
    this.camera = camera;
    this.renderer = renderer;
    this.scene = new THREE.Scene();
    this.ortho = new THREE.OrthographicCamera(-1.9, 1.9, 1.9, -1.9, 0.1, 10);
    this.ortho.position.set(0, 0, 5);
    this.ortho.lookAt(0, 0, 0);
    this.mesh = new THREE.Mesh(new THREE.BoxGeometry(1.75, 1.75, 1.75), [
      faceMaterial("RIGHT", "#c54d60"), faceMaterial("LEFT", "#9d384e"),
      faceMaterial("REAR", "#3a80bb"), faceMaterial("FRONT", "#286292"),
      faceMaterial("TOP", "#6551c7"), faceMaterial("BOTTOM", "#4e3b9a"),
    ]);
    this.scene.add(this.mesh);
    this.raycaster = new THREE.Raycaster();
  }

  render() {
    const renderer = this.renderer;
    const previous = new THREE.Vector4();
    renderer.getViewport(previous);
    const rect = renderer.domElement.getBoundingClientRect();
    if (rect.width < 130 || rect.height < 130) return;
    this.mesh.quaternion.copy(this.camera.quaternion).invert();
    this.mesh.updateMatrixWorld();
    const previousAutoClear = renderer.autoClear;
    renderer.autoClear = false;
    renderer.clearDepth();
    renderer.setViewport(
      rect.width - ORIENTATION_CUBE_SIZE - ORIENTATION_CUBE_MARGIN,
      rect.height - ORIENTATION_CUBE_SIZE - ORIENTATION_CUBE_MARGIN,
      ORIENTATION_CUBE_SIZE, ORIENTATION_CUBE_SIZE,
    );
    try {
      renderer.render(this.scene, this.ortho);
    } finally {
      renderer.setViewport(previous.x, previous.y, previous.z, previous.w);
      renderer.autoClear = previousAutoClear;
    }
  }

  pick(event) {
    const rect = this.renderer.domElement.getBoundingClientRect();
    if (rect.width < 130 || rect.height < 130) return null;
    const x = event.clientX - (rect.right - ORIENTATION_CUBE_SIZE - ORIENTATION_CUBE_MARGIN);
    const y = event.clientY - (rect.top + ORIENTATION_CUBE_MARGIN);
    if (x < 0 || y < 0 || x > ORIENTATION_CUBE_SIZE || y > ORIENTATION_CUBE_SIZE) return null;
    const pointer = new THREE.Vector2(
      x / ORIENTATION_CUBE_SIZE * 2 - 1,
      1 - y / ORIENTATION_CUBE_SIZE * 2,
    );
    this.raycaster.setFromCamera(pointer, this.ortho);
    const hit = this.raycaster.intersectObject(this.mesh)[0];
    return hit ? ORIENTATION_FACES[hit.face.materialIndex] : null;
  }

  dispose() {
    this.mesh.geometry.dispose();
    for (const material of this.mesh.material) {
      material.map?.dispose();
      material.dispose();
    }
    this.scene.clear();
  }
}
