import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// 开发时把 /api/v1 代理到本机后端，浏览器与前端保持同源。
export default defineConfig({
  plugins: [vue()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: {
      '/api/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
