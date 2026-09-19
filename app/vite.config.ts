import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

const root = path.resolve(import.meta.dirname);

export default defineConfig({
  root,
  base: '/',
  plugins: [react()],
  resolve: { alias: { '@': path.join(root, 'src') } },
  build: {
    outDir: path.join(root, 'dist'),
    emptyOutDir: true,
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Keep the 3D bundle separate so the 2D fallback path stays small.
        manualChunks: {
          three: ['three', '@react-three/fiber', '@react-three/drei'],
          charts: ['recharts'],
        },
      },
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8080', changeOrigin: true, ws: false },
    },
  },
});
