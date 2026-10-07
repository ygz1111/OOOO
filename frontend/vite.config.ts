import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        secure: false
      }
    }
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
    // ── 代码分割：将第三方依赖拆分为独立 chunk，优化缓存命中率 ──
    rollupOptions: {
      output: {
        manualChunks: {
          // React 核心 — 变更频率极低，长期缓存
          'vendor-react': ['react', 'react-dom', 'react-router-dom'],
          // 图表库 — 体积大，独立拆分
          'vendor-recharts': ['recharts'],
          // 工具库
          'vendor-utils': ['axios', 'date-fns', 'lucide-react'],
        },
      },
    },
    // 提高警告阈值，避免 vendor chunk 拆分后产生误报
    chunkSizeWarningLimit: 600,
    // 启用 CSS 代码分割
    cssCodeSplit: true,
    // 预压缩资源
    assetsInlineLimit: 4096,
  },
  // ── 依赖预构建：显式包含所有 CJS 依赖，由 esbuild 统一转换为 ESM ──
  optimizeDeps: {
    include: [
      'react',
      'react-dom',
      'react-router-dom',
      'axios',
      'recharts',
      'date-fns',
      'lucide-react',
    ],
  },
})
