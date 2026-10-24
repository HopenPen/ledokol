import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

// В dev все запросы /api проксируются на FastAPI — фронт и бэк живут на одном origin, CORS не нужен.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://127.0.0.1:8000'
  return {
    plugins: [vue()],
    server: {
      host: '127.0.0.1',   // на Windows «localhost» иногда слушает только IPv6 — фиксируем IPv4
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': apiTarget,
        '/meta': apiTarget,
      },
    },
  }
})
