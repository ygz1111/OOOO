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
          // MUI — 体积大，独立拆分
          'vendor-mui': ['@mui/material', '@mui/icons-material', '@emotion/react', '@emotion/styled'],
          // 工具库
          'vendor-utils': ['axios', 'date-fns', 'lucide-react', 'clsx'],
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
      // MUI + Emotion 依赖链包含 CJS 模块（如 hoist-non-react-statics），
      // 必须由 Vite 预构建统一转换，否则 dev server 报 export default 错误
      '@mui/material',
      '@mui/icons-material',
      '@emotion/react',
      '@emotion/styled',
    ],
  },
})
