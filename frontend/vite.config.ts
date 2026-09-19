import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
// 2026-08-27 移动端 APK（lw.Web2Android 官方要求）：base:"./"——本地资源相对 URL，
// 否则 /assets/... 会指向 APK 应用域名根目录而非 assets/www/；桌面版同源服务不受影响
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0', // 允许手机等局域网设备访问（真机测试移动端）
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        /* 2026-08-28 性能优化：vendor 拆分利于长缓存（react 系几乎不变，改业务代码不重下）；
           大面板已走 React.lazy（StarMap/Settings/MeDrawer/SessionDrawer 独立 chunk 按需拉） */
        manualChunks(id) {
          if (
            id.includes('node_modules/react') ||
            id.includes('node_modules/zustand') ||
            id.includes('node_modules/scheduler')
          ) {
            return 'react-vendor'
          }
          if (id.includes('node_modules/lucide-react')) {
            return 'lucide'
          }
        },
      },
    },
  },
})
