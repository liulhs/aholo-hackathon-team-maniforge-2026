// Removes DWARF debug sections (custom sections named ".debug_*") from the built MuJoCo .wasm.
// They are about 6 MB of the 11 MB file and only serve debuggers; code and data are untouched.
//   node tools/strip-wasm-debug.mjs dist/assets
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

function readLeb(bytes, offset) {
  let value = 0;
  let shift = 0;
  let length = 0;
  for (;;) {
    const byte = bytes[offset + length];
    value |= (byte & 0x7f) << shift;
    length += 1;
    if ((byte & 0x80) === 0) return { value: value >>> 0, length };
    shift += 7;
  }
}

/** The module with its .debug_* custom sections left out, and their names. */
export function stripDebug(bytes) {
  if (bytes[0] !== 0x00 || bytes[1] !== 0x61 || bytes[2] !== 0x73 || bytes[3] !== 0x6d) throw new Error('not a wasm module');
  const kept = [bytes.subarray(0, 8)];
  const removed = [];
  let offset = 8;
  while (offset < bytes.length) {
    const id = bytes[offset];
    const size = readLeb(bytes, offset + 1);
    const end = offset + 1 + size.length + size.value;
    let name = '';
    if (id === 0) {
      const nameLength = readLeb(bytes, offset + 1 + size.length);
      const start = offset + 1 + size.length + nameLength.length;
      name = new TextDecoder().decode(bytes.subarray(start, start + nameLength.value));
    }
    if (id === 0 && name.startsWith('.debug')) removed.push(name);
    else kept.push(bytes.subarray(offset, end));
    offset = end;
  }
  const out = new Uint8Array(kept.reduce((sum, part) => sum + part.length, 0));
  let at = 0;
  for (const part of kept) {
    out.set(part, at);
    at += part.length;
  }
  return { out, removed };
}

const dir = process.argv[2] ?? 'dist/assets';
for (const file of readdirSync(dir).filter((f) => /^mujoco.*\.wasm$/.test(f))) {
  const path = join(dir, file);
  const before = readFileSync(path);
  const { out, removed } = stripDebug(new Uint8Array(before));
  if (!(await WebAssembly.validate(out))) throw new Error(`${file}: stripped module does not validate`);
  writeFileSync(path, out);
  console.log(`${file}: ${(before.length / 1e6).toFixed(1)} MB -> ${(out.length / 1e6).toFixed(1)} MB (removed ${removed.join(', ') || 'nothing'})`);
}
