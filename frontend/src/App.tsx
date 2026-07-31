import { useState, Suspense, lazy } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'
import { Spinner } from './components/Skeleton'
import { PageTransition } from './components/ui/Animations'
import CyberBackground from './components/ui/CyberBackground'
import ErrorBoundary from './components/ErrorBoundary'
import { ApiProvider } from './contexts/ApiContext'
import { AuthProvider, useAuth } from './contexts/AuthContext'

// 路由懒加载 - 提升首屏性能
const Login = lazy(() => import('./pages/Login'))
const Dashboard = lazy(() => import('./pages/Dashboard'))
const LoadForecast = lazy(() => import('./pages/LoadForecast'))
const WeatherMonitor = lazy(() => import('./pages/WeatherMonitor'))
const SolarGeneration = lazy(() => import('./pages/SolarGeneration'))
const WindGeneration = lazy(() => import('./pages/WindGeneration'))
const SystemStatus = lazy(() => import('./pages/SystemStatus'))
const HistoricalAnalysis = lazy(() => import('./pages/HistoricalAnalysis'))

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

// ── 主布局 ──
const MainLayout: React.FC = () => {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const location = useLocation()

  const toggleSidebar = () => setSidebarOpen(!sidebarOpen)

  return (
    <div className="flex h-screen relative overflow-hidden" style={{ background: 'var(--cyber-bg)' }}>
      {/* 赛博朋克粒子脉波背景 */}
      <CyberBackground />

      {/* 透视网格底层 */}
      <div
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          backgroundImage: `
            linear-gradient(rgba(0, 240, 255, 0.03) 1px, transparent 1px),
            linear-gradient(90deg, rgba(0, 240, 255, 0.03) 1px, transparent 1px)
          `,
          backgroundSize: '40px 40px',
          maskImage: 'radial-gradient(ellipse at center, black 30%, transparent 80%)',
          WebkitMaskImage: 'radial-gradient(ellipse at center, black 30%, transparent 80%)',
        }}
        aria-hidden="true"
      />

      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex-1 flex flex-col overflow-hidden relative z-10">
        <Header onMenuClick={toggleSidebar} />

        <main className="flex-1 overflow-y-auto p-4 md:p-6 tech-grid-bg">
          <PageTransition pageKey={location.pathname}>
            <ErrorBoundary>
              <Suspense fallback={<PageLoader />}>
                <Routes location={location}>
                  <Route path="/" element={<Dashboard />} />
                  <Route path="/load-forecast" element={<LoadForecast />} />
                  <Route path="/weather-monitor" element={<WeatherMonitor />} />
                  <Route path="/solar-generation" element={<SolarGeneration />} />
                  <Route path="/wind-generation" element={<WindGeneration />} />
                  <Route path="/system-status" element={<SystemStatus />} />
                  <Route path="/historical-analysis" element={<HistoricalAnalysis />} />
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
        {/* 公开路由：登录页 */}
        <Route
          path="/login"
          element={
            <PublicOnlyRoute>
              <Suspense fallback={<PageLoader />}>
                <Login />
              </Suspense>
            </PublicOnlyRoute>
          }
        />

        {/* 受保护路由：需要认证 */}
        <Route
          path="/*"
          element={
            <ProtectedRoute>
              <ApiProvider>
                <MainLayout />
              </ApiProvider>
            </ProtectedRoute>
          }
        />
      </Routes>
    </AuthProvider>
  )
}

export default App
