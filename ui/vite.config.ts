import { defineConfig } from 'vite';

// Vite dev server configuration
// - Exposes on 0.0.0.0:5173 for external access
// - Proxies API traffic from /proxy and /mcp to the Flask backend on 5000
const rootDir = new URL('.', import.meta.url).pathname;

export default defineConfig({
  build: {
    rollupOptions: {
      input: {
  trainer: new URL('./index.html', import.meta.url).pathname,
  client: new URL('./client.html', import.meta.url).pathname,
      },
    },
  },
  server: {
    host: true, // 0.0.0.0
    port: 5173,
    proxy: {
      '/proxy': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        ws: false,
      },
      '/mcp': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        ws: false,
      },
      '/pairs': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        ws: false,
      },
      '/admin': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        ws: false,
      },
      '/vision': {
        target: 'http://127.0.0.1:5000',
        changeOrigin: true,
        secure: false,
        ws: false,
      },
    },
  },
});
