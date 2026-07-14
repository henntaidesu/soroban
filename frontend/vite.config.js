import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

// 本地开发：前端默认 8621，代理 /api → 后端默认 8620（免 CORS）。端口可用环境变量
// FRONTEND_PORT / BACKEND_PORT 覆盖（start.sh 会 export 它们，保持前后端一致）。
const BACKEND_PORT = process.env.BACKEND_PORT || '8620'
const FRONTEND_PORT = Number(process.env.FRONTEND_PORT) || 8621
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) }
  },
  server: {
    port: FRONTEND_PORT,
    proxy: {
      '/api': { target: `http://127.0.0.1:${BACKEND_PORT}`, changeOrigin: true }
    }
  }
})
