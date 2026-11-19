/**
 * The grasp policy in the browser: an ACT model exported to ONNX (sim/export_policy.py) with its
 * normalisation built in. It sees the six arm joint angles and the object's 12-number state, and
 * returns target joint angles for the next frame, smoothed by temporal ensembling (the setting
 * that scored best in sim/evaluate.py).
 */
import * as ort from 'onnxruntime-web/wasm'; // CPU (WebAssembly) build only: the model is small
import ortWasmUrl from 'onnxruntime-web/ort-wasm-simd-threaded.wasm?url';

import { TemporalEnsembler } from './temporalEnsembler';

export interface PolicyInfo {
  chunk_size: number;
  fps: number;
  joint_names: string[];
  temporal_ensemble_coeff: number;
  object_position?: 'origin' | 'com'; // absent in older exports: origin
  inputs: Record<string, { shape: number[] }>;
  outputs: Record<string, { shape: number[] }>;
}

const STATE_INPUT = 'state';
const ENV_INPUT = 'env_state';
const ACTION_OUTPUT = 'actions';

function assetUrl(path: string): string {
  return `${import.meta.env.BASE_URL}${path}`;
}

export class ActPolicy {
  private constructor(
    private readonly session: ort.InferenceSession,
    readonly info: PolicyInfo,
    private readonly ensembler: TemporalEnsembler,
  ) {}

  static async load(onProgress?: (fraction: number) => void): Promise<ActPolicy> {
    ort.env.wasm.numThreads = 1; // threads need cross-origin isolation, which static hosts rarely give
    ort.env.wasm.wasmPaths = { wasm: ortWasmUrl }; // bundled with the site, no CDN
    const info = (await fetchJson(assetUrl('policy/policy.json'))) as PolicyInfo;
    const weights = await fetchBytes(assetUrl('policy/policy.onnx'), onProgress);
    const session = await ort.InferenceSession.create(weights, { executionProviders: ['wasm'] });
    const actionDim = info.joint_names.length;
    return new ActPolicy(session, info, new TemporalEnsembler(info.temporal_ensemble_coeff, info.chunk_size, actionDim));
  }

  /** Forget the previous predictions; call before every new attempt. */
  reset(): void {
    this.ensembler.reset();
  }

  /** Target joint angles (rad) for this frame. */
  async act(jointRad: ArrayLike<number>, objectState: ArrayLike<number>): Promise<Float64Array> {
    const feeds = {
      [STATE_INPUT]: new ort.Tensor('float32', Float32Array.from(jointRad), [1, jointRad.length]),
      [ENV_INPUT]: new ort.Tensor('float32', Float32Array.from(objectState), [1, objectState.length]),
    };
    const result = await this.session.run(feeds);
    const chunk = result[ACTION_OUTPUT];
    try {
      return this.ensembler.update(chunk.data as Float32Array);
    } finally {
      for (const tensor of Object.values(result)) tensor.dispose();
    }
  }
}

async function fetchJson(url: string): Promise<unknown> {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

/** Download with progress; a .gz file is unpacked on the way (the scenes ship gzipped, any static host works). */
export async function fetchBytes(url: string, onProgress?: (fraction: number) => void): Promise<Uint8Array> {
  const packed = await download(url, onProgress);
  const isGzip = packed[0] === 0x1f && packed[1] === 0x8b; // a host may already have unpacked it (Content-Encoding)
  if (!url.endsWith('.gz') || !isGzip) return packed;
  const stream = new Blob([packed as Uint8Array<ArrayBuffer>]).stream().pipeThrough(new DecompressionStream('gzip'));
  return new Uint8Array(await new Response(stream).arrayBuffer());
}

async function download(url: string, onProgress?: (fraction: number) => void): Promise<Uint8Array> {
  const response = await fetch(url);
  if (!response.ok || !response.body) throw new Error(`${url}: HTTP ${response.status}`);
  const total = Number(response.headers.get('content-length')) || 0;
  const reader = response.body.getReader();
  const parts: Uint8Array[] = [];
  let received = 0;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    parts.push(value);
    received += value.length;
    if (total && onProgress) onProgress(Math.min(received / total, 1));
  }
  const bytes = new Uint8Array(received);
  let offset = 0;
  for (const part of parts) {
    bytes.set(part, offset);
    offset += part.length;
  }
  onProgress?.(1);
  return bytes;
}
