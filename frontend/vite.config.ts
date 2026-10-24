import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// В dev все запросы /api проксируются на FastAPI — фронт и бэк живут на одном origin, CORS не нужен.
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',   // на Windows «localhost» иногда слушает только IPv6 — фиксируем IPv4
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://localhost:8000', '/meta': 'http://localhost:8000' },
  },
})
