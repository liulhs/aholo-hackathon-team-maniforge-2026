/**
 * Slides for the story's two object carousels; the scrolling, dots and autoplay are carousel.ts.
 * - Step 1 (Lux3D): each object's Lux3D inputs and three renders of the model it produced.
 * - Step 2 (physics): each object standing in the grasp scene.
 * Images come from sim/build_lux3d_gallery.py and sim/build_scene_gallery.py.
 */
import { bindCarousel } from './carousel';
import { LUX3D_OBJECTS, VIEW_NAMES, type Lux3dObject } from './lux3dObjects';

const INPUT_PX = 240;
const VIEW_PX = 520;
const SCENE_W = 1120;
const SCENE_H = 630;

function el<K extends keyof HTMLElementTagNameMap>(tag: K, className?: string, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function image(src: string, alt: string, width: number, height: number, eager: boolean): HTMLImageElement {
  const img = el('img');
  img.src = src;
  img.alt = alt;
  img.width = width;
  img.height = height;
  img.loading = eager ? 'eager' : 'lazy';
  img.decoding = 'async';
  return img;
}

function slideShell(label: string, index: number, total: number): HTMLLIElement {
  const item = el('li', 'carousel__slide');
  item.setAttribute('role', 'group');
  item.setAttribute('aria-roledescription', '幻灯片');
  item.setAttribute('aria-label', `${index + 1} / ${total}：${label}`);
  return item;
}

function lux3dSlide(object: Lux3dObject, index: number, total: number, base: string): HTMLLIElement {
  const eager = index === 0;
  const item = slideShell(object.label, index, total);
  item.classList.add('lux3d__slide');

  const head = el('header', 'lux3d__head');
  head.append(el('h4', 'lux3d__name', object.label), el('span', 'lux3d__count', `${index + 1} / ${total}`));

  const inputs = el('figure', 'lux3d__inputs');
  const strip = el('ul', 'lux3d__strip');
  object.inputs.forEach((kind, k) => {
    const cell = el('li', 'lux3d__input');
    const tag = el('span', kind === '主图' ? 'lux3d__kind lux3d__kind--main' : 'lux3d__kind', kind);
    cell.append(image(`${base}/input-${k + 1}.webp`, `${object.label}参考图 ${k + 1}（${kind}）`, INPUT_PX, INPUT_PX, eager), tag);
    strip.append(cell);
  });
  inputs.append(el('figcaption', 'lux3d__label', `参考图 · ${object.inputs.length} 张`), strip, el('p', 'lux3d__source', object.source));

  const result = el('figure', 'lux3d__result');
  const views = el('ul', 'lux3d__views');
  VIEW_NAMES.forEach((view, k) => {
    const cell = el('li', 'lux3d__view');
    cell.append(image(`${base}/view-${k + 1}.webp`, `Lux3D 生成的${object.label}模型，${view}`, VIEW_PX, VIEW_PX, eager));
    views.append(cell);
  });
  result.append(el('figcaption', 'lux3d__label', '生成结果 · MuJoCo 渲染'), views, el('p', 'lux3d__note', object.result));

  item.append(head, inputs, result);
  return item;
}

function sceneSlide(object: Lux3dObject, index: number, total: number, src: string): HTMLLIElement {
  const item = slideShell(object.label, index, total);
  item.classList.add('scene-slide');
  const figure = el('figure', 'scene-slide__figure');
  const caption = el('figcaption', 'scene-slide__caption');
  caption.append(el('span', 'scene-slide__name', object.label), el('span', 'lux3d__count', `${index + 1} / ${total}`));
  figure.append(image(src, `抓取场景中的${object.label}：立在深色垫子上，机械臂处于初始姿态。`, SCENE_W, SCENE_H, index === 0), caption);
  item.append(figure);
  return item;
}

function fill(rootId: string, build: (object: Lux3dObject, index: number, total: number) => HTMLLIElement): void {
  const root = document.getElementById(rootId);
  const track = root?.querySelector('.carousel__track');
  if (!root || !track) return;
  const total = LUX3D_OBJECTS.length;
  track.replaceChildren(...LUX3D_OBJECTS.map((object, i) => build(object, i, total)));
  bindCarousel(root, LUX3D_OBJECTS.map((o) => o.label));
}

export function bindStoryCarousels(assetBase: string): void {
  fill('lux3d', (o, i, n) => lux3dSlide(o, i, n, `${assetBase}media/lux3d/${o.name}`));
  fill('scene-carousel', (o, i, n) => sceneSlide(o, i, n, `${assetBase}media/scene/${o.name}.webp`));
}
