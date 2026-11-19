/**
 * Draws a MuJoCo model with three.js. Every visible geom (groups 0-2; group 3 holds collision
 * shapes) becomes a mesh built from the compiled model's own vertex, texture and material data,
 * and each frame copies the geom poses from MjData. The world stays Z-up, as in MuJoCo.
 */
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import type { MainModule, MjModel } from '@mujoco/mujoco';

import type { Simulation } from '../sim/simulation';
import { makeTableLabel } from './tableLabel';

const VISIBLE_GROUPS = 2; // geoms in groups 0..2 are drawn
const MJ_GEOM = { plane: 0, sphere: 2, capsule: 3, ellipsoid: 4, cylinder: 5, box: 6, mesh: 7 } as const;
const TEXROLE_RGB = 1;
const TEXTURE_2D = 0;
const FALLBACK_NTEXROLE = 10;
const LOOK_AT = new THREE.Vector3(0.2, 0, 0.03);

export interface CameraView {
  azimuthDeg: number;
  elevationDeg: number;
  distance: number;
}

const WIDE_VIEW: CameraView = { azimuthDeg: 128, elevationDeg: -27, distance: 0.92 };
const TALL_VIEW: CameraView = { azimuthDeg: 140, elevationDeg: -38, distance: 1.25 };
const TALL_SHIFT = 0.1; // fraction of the height the picture moves up on tall screens

interface DrawnGeom {
  index: number;
  mesh: THREE.Mesh;
}

const FLOOR_SHADOW_OPACITY = 0.3; // with a splat room behind, the floor plane only catches shadows
/**
 * The splat room is turned about the table's centre (sim/simple_table.py TABLE_CENTER_X_M) so the
 * default view shows the restaurant's tables and chairs on the left and its windows on the right
 * (90 would put the windows straight behind the table); the camera views stay as they are.
 * The room was cut out around the table spot, so turning it keeps the same clearance on every side.
 */
const TABLE_CENTER = new THREE.Vector3(0.275, 0, 0);
const BACKDROP_YAW = THREE.MathUtils.degToRad(60);

export class SceneView {
  readonly renderer: THREE.WebGLRenderer;
  readonly camera: THREE.PerspectiveCamera;
  readonly controls: OrbitControls;
  private readonly scene = new THREE.Scene();
  private readonly root = new THREE.Group();
  private drawn: DrawnGeom[] = [];
  private objectMeshes: THREE.Mesh[] = [];
  private readonly raycaster = new THREE.Raycaster();
  private readonly tablePlane = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
  private readonly textures = new Map<number, THREE.Texture>();
  private readonly textureCopies: THREE.Texture[] = []; // per-geom repeats of a shared texture
  private tall = false;
  private floorMeshes: THREE.Mesh[] = [];
  private readonly floorShadow = new THREE.ShadowMaterial({ opacity: FLOOR_SHADOW_OPACITY });
  private backdrop: THREE.Object3D | null = null; // a Gaussian-splat room around the table, if loaded
  private backdropOn = false;
  private readonly fog: THREE.Fog;

  constructor(
    private readonly canvas: HTMLCanvasElement,
    private readonly mj: MainModule,
    background: string,
  ) {
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFShadowMap;
    this.scene.background = new THREE.Color(background);
    this.fog = new THREE.Fog(background, 2.2, 5.5);
    this.scene.fog = this.fog;

    this.camera = new THREE.PerspectiveCamera(38, 1, 0.01, 20);
    this.camera.up.set(0, 0, 1);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.target.copy(LOOK_AT);
    this.controls.enablePan = false;
    this.controls.enableZoom = false; // the wheel scrolls the page down to the story; the views are framed already
    this.controls.enableDamping = true;
    this.controls.minDistance = 0.45;
    this.controls.maxDistance = 1.9;
    this.controls.maxPolarAngle = THREE.MathUtils.degToRad(84); // never below the table top
    this.controls.minPolarAngle = THREE.MathUtils.degToRad(12);

    this.addLights();
    this.scene.add(this.root);
    this.tall = this.isTall();
    this.resize();
    this.setView(this.tall ? TALL_VIEW : WIDE_VIEW);
  }

  /** Unit vector on the table pointing away from the camera (for moving the object with the keyboard). */
  groundForward(): [number, number] {
    const dx = this.controls.target.x - this.camera.position.x;
    const dy = this.controls.target.y - this.camera.position.y;
    const length = Math.hypot(dx, dy) || 1;
    return [dx / length, dy / length];
  }

  private isTall(): boolean {
    return this.canvas.clientHeight > this.canvas.clientWidth * 1.05;
  }

  private addLights(): void {
    this.scene.add(new THREE.HemisphereLight(0xf2f5f8, 0x8d8a84, 1.25));
    const key = new THREE.DirectionalLight(0xfff4e6, 2.4);
    key.position.set(0.9, -1.0, 1.6); // the key light of sim/simple_table.py
    key.target.position.copy(LOOK_AT);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -0.6;
    key.shadow.camera.right = 0.6;
    key.shadow.camera.top = 0.6;
    key.shadow.camera.bottom = -0.6;
    key.shadow.camera.near = 0.5;
    key.shadow.camera.far = 4;
    key.shadow.bias = -0.0004;
    key.shadow.normalBias = 0.01;
    const fill = new THREE.DirectionalLight(0xdfe8f2, 0.55);
    fill.position.set(-0.6, 0.8, 1.2);
    this.scene.add(key, key.target, fill);
  }

  setView(view: CameraView): void {
    const az = THREE.MathUtils.degToRad(view.azimuthDeg);
    const el = THREE.MathUtils.degToRad(view.elevationDeg);
    const forward = new THREE.Vector3(Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el));
    this.camera.position.copy(LOOK_AT).addScaledVector(forward, -view.distance);
    this.controls.target.copy(LOOK_AT);
    this.controls.update();
  }

  resize(): void {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    if (!width || !height) return;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    const tall = this.isTall();
    // On a phone held upright the shelf and controls cover the lower third: draw the scene higher.
    if (tall) this.camera.setViewOffset(width, height, 0, Math.round(height * TALL_SHIFT), width, height);
    else this.camera.clearViewOffset();
    this.camera.updateProjectionMatrix();
    if (tall !== this.tall) {
      this.tall = tall;
      this.setView(tall ? TALL_VIEW : WIDE_VIEW); // the phone was turned
    }
  }

  /** Print a line of text on the tabletop (see tableLabel.ts); it stays across scene swaps. */
  setTableLabel(text: string): void {
    this.scene.add(makeTableLabel(text, this.renderer.capabilities.getMaxAnisotropy()));
  }

  /** Replace what is drawn with the geoms of `sim`'s model. */
  show(sim: Simulation): void {
    this.clear();
    const model = sim.model;
    const geometryCache = new Map<number, THREE.BufferGeometry>();
    for (let g = 0; g < model.ngeom; g += 1) {
      if (model.geom_group[g] > VISIBLE_GROUPS) continue;
      const material = this.material(model, g);
      if (!material) continue;
      const geometry = this.geometry(model, g, geometryCache);
      if (!geometry) continue;
      const mesh = new THREE.Mesh(geometry, material);
      mesh.matrixAutoUpdate = false;
      const isFloor = model.geom_type[g] === MJ_GEOM.plane;
      mesh.castShadow = !isFloor;
      mesh.receiveShadow = true;
      if (isFloor) {
        mesh.userData.solidMaterial = material;
        this.floorMeshes.push(mesh);
      }
      this.root.add(mesh);
      this.drawn.push({ index: g, mesh });
      if (model.geom_bodyid[g] === sim.objectBody) this.objectMeshes.push(mesh);
    }
    this.applyBackdrop();
    this.sync(sim);
  }

  /**
   * Load a Gaussian-splat room (already placed in this scene's frame, see sim/sage3d_background.py)
   * and show it around the table. Spark is imported only here, so visitors who never see the room
   * do not download it.
   */
  async loadBackdrop(url: string): Promise<void> {
    if (this.backdrop) return;
    const { SparkRenderer, SplatMesh } = await import('@sparkjsdev/spark');
    const spark = new SparkRenderer({ renderer: this.renderer });
    const room = new SplatMesh({ url });
    await room.initialized;
    const group = new THREE.Group();
    group.add(spark, room);
    room.rotation.z = BACKDROP_YAW;
    // rotate about the table centre, not the origin: position = c - R(c)
    room.position.copy(TABLE_CENTER).sub(TABLE_CENTER.clone().applyAxisAngle(new THREE.Vector3(0, 0, 1), BACKDROP_YAW));
    this.backdrop = group;
    this.scene.add(group);
    this.setBackdrop(true);
  }

  get hasBackdrop(): boolean {
    return this.backdrop !== null;
  }

  get backdropVisible(): boolean {
    return this.backdropOn;
  }

  setBackdrop(on: boolean): void {
    this.backdropOn = on && this.backdrop !== null;
    this.applyBackdrop();
  }

  private applyBackdrop(): void {
    if (this.backdrop) this.backdrop.visible = this.backdropOn;
    this.scene.fog = this.backdropOn ? null : this.fog;
    for (const mesh of this.floorMeshes) {
      mesh.material = this.backdropOn ? this.floorShadow : (mesh.userData.solidMaterial as THREE.Material);
    }
  }

  private clear(): void {
    for (const { mesh } of this.drawn) {
      this.root.remove(mesh);
      const own = (mesh.userData.solidMaterial as THREE.Material | undefined) ?? (mesh.material as THREE.Material);
      own.dispose(); // the shared shadow material stays
    }
    this.floorMeshes = [];
    const geometries = new Set(this.drawn.map(({ mesh }) => mesh.geometry));
    geometries.forEach((geometry) => geometry.dispose());
    this.textures.forEach((texture) => texture.dispose());
    this.textures.clear();
    this.textureCopies.splice(0).forEach((texture) => texture.dispose());
    this.drawn = [];
    this.objectMeshes = [];
  }

  /** Copy every drawn geom's world pose from the simulation. */
  sync(sim: Simulation): void {
    const xpos = sim.data.geom_xpos;
    const xmat = sim.data.geom_xmat;
    for (const { index: g, mesh } of this.drawn) {
      const p = 3 * g;
      const r = 9 * g;
      mesh.matrix.set(
        xmat[r], xmat[r + 1], xmat[r + 2], xpos[p],
        xmat[r + 3], xmat[r + 4], xmat[r + 5], xpos[p + 1],
        xmat[r + 6], xmat[r + 7], xmat[r + 8], xpos[p + 2],
        0, 0, 0, 1,
      );
      mesh.matrixWorldNeedsUpdate = true;
    }
  }

  render(): void {
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  }

  /** Client-pixel position of a world point (for tests and overlays). */
  screenPoint(x: number, y: number, z: number): { x: number; y: number } {
    const rect = this.canvas.getBoundingClientRect();
    const p = new THREE.Vector3(x, y, z).project(this.camera);
    return { x: rect.left + ((p.x + 1) / 2) * rect.width, y: rect.top + ((1 - p.y) / 2) * rect.height };
  }

  /** Where a screen point meets the table top (z = 0), in world metres. */
  tablePoint(clientX: number, clientY: number): { x: number; y: number } | null {
    this.aim(clientX, clientY);
    const hit = new THREE.Vector3();
    return this.raycaster.ray.intersectPlane(this.tablePlane, hit) ? { x: hit.x, y: hit.y } : null;
  }

  /** Whether a screen point is over the object. */
  overObject(clientX: number, clientY: number): boolean {
    this.aim(clientX, clientY);
    return this.raycaster.intersectObjects(this.objectMeshes, false).length > 0;
  }

  private aim(clientX: number, clientY: number): void {
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((clientX - rect.left) / rect.width) * 2 - 1, -((clientY - rect.top) / rect.height) * 2 + 1);
    this.raycaster.setFromCamera(ndc, this.camera);
  }

  private material(model: MjModel, g: number): THREE.MeshStandardMaterial | null {
    const matId = model.geom_matid[g];
    const rgbaSource = matId >= 0 ? model.mat_rgba : model.geom_rgba;
    const k = 4 * (matId >= 0 ? matId : g);
    const alpha = rgbaSource[k + 3];
    if (alpha <= 0.01) return null; // invisible helper geoms
    const color = new THREE.Color().setRGB(rgbaSource[k], rgbaSource[k + 1], rgbaSource[k + 2], THREE.SRGBColorSpace);
    const specular = matId >= 0 ? model.mat_specular[matId] : 0.5;
    const shininess = matId >= 0 ? model.mat_shininess[matId] : 0.5;
    const material = new THREE.MeshStandardMaterial({
      color,
      roughness: THREE.MathUtils.clamp(1 - 0.75 * shininess, 0.25, 0.95),
      metalness: specular > 0.6 ? 0.55 : 0.05,
      transparent: alpha < 1,
      opacity: alpha,
    });
    const texture = matId >= 0 ? this.texture(model, matId) : null;
    if (texture) {
      material.map = texture;
      material.color.set(0xffffff);
      if (model.mat_texuniform[matId] && model.geom_type[g] === MJ_GEOM.box) {
        // texrepeat counts repeats per metre with texuniform; three.js boxes map 0..1 per face
        const s = model.geom_size;
        const repeat = model.mat_texrepeat;
        const map = texture.clone();
        map.repeat.set(2 * s[3 * g] * repeat[2 * matId], 2 * s[3 * g + 1] * repeat[2 * matId + 1]);
        map.needsUpdate = true;
        material.map = map;
        this.textureCopies.push(map);
      }
    }
    return material;
  }

  private texture(model: MjModel, matId: number): THREE.Texture | null {
    const roles = (this.mj as unknown as { mjNTEXROLE?: number }).mjNTEXROLE ?? FALLBACK_NTEXROLE;
    const texId = model.mat_texid[matId * roles + TEXROLE_RGB];
    if (texId < 0 || model.tex_type[texId] !== TEXTURE_2D) return null;
    const cached = this.textures.get(texId);
    if (cached) return cached;
    const width = model.tex_width[texId];
    const height = model.tex_height[texId];
    const channels = model.tex_nchannel[texId];
    const start = model.tex_adr[texId];
    const source: Uint8Array = model.tex_data;
    const rgba = new Uint8Array(width * height * 4);
    for (let i = 0; i < width * height; i += 1) {
      for (let c = 0; c < 3; c += 1) rgba[4 * i + c] = source[start + i * channels + Math.min(c, channels - 1)];
      rgba[4 * i + 3] = channels === 4 ? source[start + i * channels + 3] : 255;
    }
    const texture = new THREE.DataTexture(rgba, width, height, THREE.RGBAFormat);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.magFilter = THREE.LinearFilter;
    texture.minFilter = THREE.LinearMipmapLinearFilter;
    texture.generateMipmaps = true;
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    texture.needsUpdate = true;
    this.textures.set(texId, texture);
    return texture;
  }

  private geometry(model: MjModel, g: number, cache: Map<number, THREE.BufferGeometry>): THREE.BufferGeometry | null {
    const s = model.geom_size;
    const [a, b, c] = [s[3 * g], s[3 * g + 1], s[3 * g + 2]];
    switch (model.geom_type[g]) {
      case MJ_GEOM.plane:
        return new THREE.PlaneGeometry(a > 0 ? 2 * a : 20, b > 0 ? 2 * b : 20);
      case MJ_GEOM.sphere:
        return new THREE.SphereGeometry(a, 32, 16);
      case MJ_GEOM.ellipsoid:
        return new THREE.SphereGeometry(1, 32, 16).scale(a, b, c);
      case MJ_GEOM.capsule:
        return new THREE.CapsuleGeometry(a, 2 * b, 8, 24).rotateX(Math.PI / 2);
      case MJ_GEOM.cylinder:
        return new THREE.CylinderGeometry(a, a, 2 * b, 40).rotateX(Math.PI / 2);
      case MJ_GEOM.box:
        return new THREE.BoxGeometry(2 * a, 2 * b, 2 * c);
      case MJ_GEOM.mesh: {
        const meshId = model.geom_dataid[g];
        const known = cache.get(meshId);
        if (known) return known;
        const built = meshGeometry(model, meshId);
        cache.set(meshId, built);
        return built;
      }
      default:
        return null;
    }
  }
}

/** A compiled MuJoCo mesh as an unindexed BufferGeometry (positions, normals, UVs per face corner). */
function meshGeometry(model: MjModel, meshId: number): THREE.BufferGeometry {
  const vertAdr = model.mesh_vertadr[meshId];
  const faceAdr = model.mesh_faceadr[meshId];
  const faceNum = model.mesh_facenum[meshId];
  const normalAdr = model.mesh_normaladr[meshId];
  const texAdr = model.mesh_texcoordadr[meshId];
  const hasUv = texAdr >= 0 && model.mesh_texcoordnum[meshId] > 0;
  const verts = model.mesh_vert;
  const faces = model.mesh_face;
  const normals = model.mesh_normal;
  const faceNormals = model.mesh_facenormal;
  const texcoords = model.mesh_texcoord;
  const faceTex = model.mesh_facetexcoord;
  const positions = new Float32Array(faceNum * 9);
  const normalOut = new Float32Array(faceNum * 9);
  const uvs = hasUv ? new Float32Array(faceNum * 6) : null;
  for (let f = 0; f < faceNum; f += 1) {
    for (let k = 0; k < 3; k += 1) {
      const corner = 3 * (faceAdr + f) + k;
      const out = 3 * (3 * f + k);
      const v = 3 * (vertAdr + faces[corner]);
      const n = 3 * (normalAdr + faceNormals[corner]);
      for (let i = 0; i < 3; i += 1) {
        positions[out + i] = verts[v + i];
        normalOut[out + i] = normals[n + i];
      }
      if (uvs) {
        const t = 2 * (texAdr + faceTex[corner]);
        uvs[2 * (3 * f + k)] = texcoords[t];
        uvs[2 * (3 * f + k) + 1] = texcoords[t + 1];
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('normal', new THREE.BufferAttribute(normalOut, 3));
  if (uvs) geometry.setAttribute('uv', new THREE.BufferAttribute(uvs, 2));
  geometry.computeBoundingSphere();
  return geometry;
}
