import { defineConfig } from 'vite';

// base './': the built site works from any sub-path (ModelScope studio, a mirror, a local folder).
export default defineConfig({
  base: './',
  optimizeDeps: {
    exclude: ['@mujoco/mujoco', 'onnxruntime-web'], // both load their own .wasm next to their .js
  },
  build: {
    target: 'es2022',
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 1500,
  },
  server: { port: 5173 },
});
