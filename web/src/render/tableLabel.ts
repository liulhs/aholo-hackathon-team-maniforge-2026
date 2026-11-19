/**
 * A line of text printed flat on the tabletop, in the open wood beside the mat's +x edge (to the
 * right of the mat in the default view), running parallel to that edge and reading upward from the
 * bottom left in that view. It is drawn only:
 * not part of the MuJoCo model, so it never touches physics, picking or the policy's inputs.
 */
import * as THREE from 'three';

/** Where the line sits on the table (m, MuJoCo world frame; the table top is z = 0). */
// between the mat's +x edge and the table's near edge, centred on the table's short side (y = 0,
// the table spans y = ±0.26 m, sim/simple_table.py); z just above the wood so it never z-fights
const CENTER = new THREE.Vector3(0.4, 0, 0.0008);
const HEIGHT_M = 0.02; // cap height of the printed line
const INK = '#1b2733';
const OPACITY = 0.62; // printed into the wood rather than floating on it

const CANVAS_HEIGHT_PX = 160;
const FONT_PX = 104;
const FONT = `700 ${FONT_PX}px 'PingFang SC', 'Hiragino Sans GB', 'Noto Sans SC', 'Source Han Sans SC', 'Microsoft YaHei', sans-serif`;
const PAD_PX = 24;

function drawText(text: string): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  const context = canvas.getContext('2d');
  if (!context) throw new Error('2D canvas is not available for the table label');
  context.font = FONT;
  canvas.width = Math.ceil(context.measureText(text).width) + PAD_PX * 2;
  canvas.height = CANVAS_HEIGHT_PX;
  context.font = FONT; // resizing the canvas resets its state
  context.fillStyle = INK;
  context.textAlign = 'center';
  context.textBaseline = 'middle';
  context.fillText(text, canvas.width / 2, canvas.height / 2);
  return canvas;
}

export function makeTableLabel(text: string, maxAnisotropy: number): THREE.Mesh {
  const canvas = drawText(text);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.anisotropy = maxAnisotropy; // the camera sees the table at a low angle
  const height = (HEIGHT_M * CANVAS_HEIGHT_PX) / FONT_PX;
  const width = (height * canvas.width) / canvas.height;
  const material = new THREE.MeshBasicMaterial({
    map: texture,
    transparent: true,
    opacity: OPACITY,
    depthWrite: false,
    toneMapped: false,
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(width, height), material);
  // the plane lies in z = const; turn it so text runs along +y with its top toward -x (the arm),
  // which reads left to right from the default camera on the +x, -y side of the table
  mesh.rotation.z = Math.PI / 2;
  mesh.position.copy(CENTER);
  mesh.renderOrder = 1;
  return mesh;
}
