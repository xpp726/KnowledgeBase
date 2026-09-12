import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 后端 FastAPI 默认 8000（config.port，python -m app.run）；SSE 需禁用缓冲
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // 语音识别 WebSocket 代理转发
        ws: true,
      },
    },
  },
})
