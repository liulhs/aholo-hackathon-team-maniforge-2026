/**
 * What the Lux3D carousel shows for each object: the images given to Lux3D (in order; the first is
 * the main image) and three renders of the model it produced. Images come from
 * sim/build_lux3d_gallery.py; the notes follow experiments/2026-11-18-lux3d-objects/README.md and
 * the 2026-11-08 takeout-box entry in the project README.
 */

export type InputKind = '主图' | 'AI 补全' | '实拍';

export interface Lux3dObject {
  name: string; // folder under media/lux3d/
  label: string;
  source: string; // where the input images came from
  inputs: readonly InputKind[];
  result: string;
}

const MAIN_PLUS_FOUR: readonly InputKind[] = ['主图', 'AI 补全', 'AI 补全', 'AI 补全', 'AI 补全'];

export const LUX3D_OBJECTS: readonly Lux3dObject[] = [
  {
    name: 'takeout_box',
    label: '外卖盒',
    source: 'Wikimedia Commons 的 CC0 照片，裁出合盖的中式外卖盒，单图输入。',
    inputs: ['主图'],
    result: '仅凭一张图片，盒身的塔形图案与折口结构均得以还原。',
  },
  {
    name: 'labubu',
    label: 'Labubu',
    source: '泡泡玛特官网正面商品图，加 AI 多视图补全的 4 个视角。',
    inputs: MAIN_PLUS_FOUR,
    result: '与单图版本相比，背面的毛发纹理更完整。',
  },
  {
    name: 'twinkle_devil',
    label: '星星人',
    source: '泡泡玛特官网的正面、侧面、背面 3 张实拍白底图。',
    inputs: ['实拍', '实拍', '实拍'],
    result: '背面的尾巴得以生成，翅膀与角的形状更准确。',
  },
  {
    name: 'airpods',
    label: 'AirPods',
    source: 'Apple 官网 AirPods Pro 3 开盖商品图，加 AI 多视图补全的 4 个视角。',
    inputs: MAIN_PLUS_FOUR,
    result: '表面干净无噪点，厚度正确，背面有转轴与按键；右侧有一小块绿色瑕疵。',
  },
  {
    name: 'aholo_mascot',
    label: 'Aholo 吉祥物',
    source: 'Aholo3D 工作台页面上的吉祥物图，加 AI 多视图补全的 4 个视角。',
    inputs: MAIN_PLUS_FOUR,
    result: '正面的眼睛与图片卡片准确，背面为纯紫色，有少量色斑。',
  },
  {
    name: 'tamagotchi',
    label: '拓麻歌子',
    source: 'Wikimedia Commons 照片（CC BY-SA 3.0），加 AI 多视图补全的 4 个视角。',
    inputs: MAIN_PLUS_FOUR,
    result: '正面尚可，挂链被生成为离散碎块，背面误生成为另一块屏幕，为 8 个物体中最差。',
  },
  {
    name: 'insta360_x5',
    label: 'Insta360 X5',
    source: 'Insta360 官网商品页的 360° 旋转图，取 8 帧作为真实多角度输入。',
    inputs: ['实拍', '实拍', '实拍', '实拍', '实拍', '实拍', '实拍', '实拍'],
    result: '双镜头、屏幕与侧面按键均准确，屏幕上有少量噪点。',
  },
  {
    name: 'insta360_go3s',
    label: 'Insta360 GO 3S',
    source: 'Insta360 官网单机透明底图，加 AI 多视图补全的 4 个视角。',
    inputs: MAIN_PLUS_FOUR,
    result: '镜头、机身纹理与背面按键均准确。',
  },
];

export const VIEW_NAMES = ['正面斜侧', '侧面', '背面斜侧'] as const;
