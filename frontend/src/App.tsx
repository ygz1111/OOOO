import { useState, useRef, useEffect, useLayoutEffect, useCallback, Suspense, lazy } from 'react'
import { Routes, Route, Navigate, useLocation, useNavigate } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import { Spinner } from './components/Skeleton'
import { PageTransition } from './components/ui/Animations'
import ErrorBoundary from './components/ErrorBoundary'
import { ApiProvider } from './contexts/ApiContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'

// 路由懒加载 - 提升首屏性能
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const LoadForecast = lazy(() => import('./pages/LoadForecast'))
const PriceForecast = lazy(() => import('./pages/PriceForecast'))
const WeatherMonitor = lazy(() => import('./pages/WeatherMonitor'))
const SolarGeneration = lazy(() => import('./pages/SolarGeneration'))
const SystemStatus = lazy(() => import('./pages/SystemStatus'))
const HistoricalAnalysis = lazy(() => import('./pages/HistoricalAnalysis'))
const OperationSituation = lazy(() => import('./pages/OperationSituation'))

const PageLoader = () => (
  <div className="flex items-center justify-center h-full min-h-[400px]">
    <Spinner size="lg" />
  </div>
)

// ── 路由守卫：保护需要认证的页面 ──
const ProtectedRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--cyber-bg)' }}>
        <Spinner size="lg" />
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}

// ── 认证路由：已登录用户访问 /login 时跳转首页 ──
const PublicOnlyRoute: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { isAuthenticated, isLoading } = useAuth()

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-screen" style={{ background: 'var(--cyber-bg)' }}>
        <Spinner size="lg" />
      </div>
    )
  }

  if (isAuthenticated) {
    return <Navigate to="/" replace />
  }

  return <>{children}</>
}

// ── 404 兜底页（2026-08 新增：未知路径不再渲染空白内容）──
const NotFound: React.FC = () => {
  const navigate = useNavigate()
  return (
    <div className="flex flex-col items-center justify-center py-24 gap-4">
      <h1 className="text-4xl font-bold text-primary-600">404</h1>
      <p className="text-dark-300">页面不存在或已被移除</p>
      <button onClick={() => navigate('/')} className="btn btn-primary">
        返回首页
      </button>
    </div>
  )
}

// ── 主布局 ──
const MainLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const shellRef = useRef<HTMLDivElement>(null)
  const mainRef = useRef<HTMLElement>(null)
  const previousSidebarOpen = useRef(false)
  const location = useLocation()

  const toggleSidebar = useCallback(() => setSidebarOpen(open => !open), [])
  const closeSidebar = useCallback(() => setSidebarOpen(false), [])

  useLayoutEffect(() => {
    // 页面滚动发生在 main 内，切换路由（包括前进、后退）时回到新页面页首。
    if (mainRef.current) mainRef.current.scrollTop = 0
    setSidebarOpen(false)
  }, [location.pathname])

  useEffect(() => {
    if (previousSidebarOpen.current && !sidebarOpen) {
      shellRef.current?.querySelector<HTMLButtonElement>('button[aria-label="打开菜单"]')?.focus()
    }
    previousSidebarOpen.current = sidebarOpen
  }, [sidebarOpen])

  return (
    <div ref={shellRef} className="app-shell flex h-screen relative overflow-hidden">
      <Sidebar open={sidebarOpen} onClose={closeSidebar} />

      <div className="flex-1 flex flex-col overflow-hidden relative z-10 min-w-0">
        <Header onMenuClick={toggleSidebar} />

        <main ref={mainRef} className="app-main flex-1 overflow-y-auto p-4 md:p-6 lg:p-7">
          <PageTransition pageKey={location.pathname}>
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Routes location={location}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/load-forecast" element={<LoadForecast />} />
                  <Route path="/price-forecast" element={<PriceForecast />} />
                  <Route path="/weather-monitor" element={<WeatherMonitor />} />
                  <Route path="/solar-generation" element={<SolarGeneration />} />
                  <Route path="/system-status" element={<SystemStatus />} />
                  <Route path="/historical-analysis" element={<HistoricalAnalysis />} />
                  <Route path="/operation-situation" element={<OperationSituation />} />
                  {/* 404 兜底（2026-08 新增） */}
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
            </ErrorBoundary>
          </PageTransition>
        </main>
      </div>
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        {/* 公开路由：登录页（2026-08 修复：Login 页纳入 ErrorBoundary 兜底，避免白屏） */}
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <ErrorBoundary>
                <Suspense fallback={<PageLoader />}>
                  <Login />
                </Suspense>
              </ErrorBoundary>
            </PublicOnlyRoute>
          }
        />

        {/* 受保护路由：需要认证（2026-08 修复：ErrorBoundary 提升到 MainLayout 外层，
            覆盖 Header/Sidebar，此前只包住页面内容区） */}
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <ApiProvider>
                <ErrorBoundary>
                  <MainLayout />
                </ErrorBoundary>
              </ApiProvider>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}

export default App
