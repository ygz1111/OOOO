import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { ThemeProvider, initializeWorkspaceTheme } from './contexts/ThemeContext'
import './index.css'

// 注意: 全站 UI 基于 Tailwind 自研设计系统（index.css），
// 已移除 MUI/Emotion 依赖（2026-08 瘦身）：
// 全局样式重置由 Tailwind Preflight (@tailwind base) 承担，
// 工作台背景、文字和控件样式由 index.css 与各组件承担。
initializeWorkspaceTheme()
ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <ThemeProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </ThemeProvider>
  </React.StrictMode>,
)
