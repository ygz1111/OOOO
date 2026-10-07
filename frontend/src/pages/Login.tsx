import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Activity, ChartColumn, CalendarDays, Sun } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { RegisterRequest } from '../types/auth'
import { CyberLoginForm } from '../components/cyber/CyberLoginForm'
import { RegisterModal } from '../components/cyber/RegisterModal'

const Login: React.FC = () => {
  const { login, register, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [lang, setLang] = useState<'zh' | 'en'>('zh')
  const [isRegisterOpen, setIsRegisterOpen] = useState(false)

  useEffect(() => {
    if (isAuthenticated) navigate('/', { replace: true })
  }, [isAuthenticated, navigate])

  const handleLoginSuccess = async (username: string, password: string, rememberMe: boolean) => {
    await login({ username, password, remember_me: rememberMe }, rememberMe)
    navigate('/', { replace: true })
  }

  const handleRegisterSuccess = async (data: RegisterRequest) => {
    await register(data)
  }

  const functions = lang === 'zh'
    ? [
        { icon: ChartColumn, title: '负荷与电价预测', description: '查看未来 24 小时预测曲线与小时明细。' },
        { icon: Sun, title: '光伏出力分析', description: '结合区域气象数据，分析光伏出力变化。' },
        { icon: CalendarDays, title: '历史回测与误差分析', description: '按日期查询历史结果，核对预测与真实观测。' },
      ]
    : [
        { icon: ChartColumn, title: 'Load and price forecasts', description: 'Review the next 24 hours of forecasts and hourly results.' },
        { icon: Sun, title: 'Solar generation analysis', description: 'Analyze generation alongside regional weather data.' },
        { icon: CalendarDays, title: 'Historical evaluation', description: 'Compare dated predictions with observed results.' },
      ]

  return (
    <div className="formal-login min-h-screen flex flex-col bg-canvas text-ink">
      <header className="bg-surface-header border-b border-edge">
        <div className="max-w-6xl mx-auto px-6 sm:px-8 h-20 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="flex items-center justify-center w-11 h-11 rounded bg-primary-600 text-white" aria-hidden="true">
              <Activity className="w-6 h-6" strokeWidth={1.8} />
            </div>
            <div>
              <div className="text-lg sm:text-xl font-semibold tracking-wide text-ink">
                {lang === 'zh' ? '智能电网负荷预测系统' : 'Smart Grid Forecasting System'}
              </div>
              <div className="hidden sm:block text-xs text-muted mt-1">
                {lang === 'zh' ? '负荷预测 · 电价分析 · 光伏出力 · 历史回测' : 'Load · Price · Solar generation · Historical evaluation'}
              </div>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setLang(lang === 'zh' ? 'en' : 'zh')}
            className="text-sm text-muted hover:text-primary-600 px-2 py-2 shrink-0"
            aria-label={lang === 'zh' ? 'Switch to English' : '切换中文'}
          >
            {lang === 'zh' ? 'English' : '中文'}
          </button>
        </div>
      </header>

      <main className="flex-1 flex items-center py-12 sm:py-16">
        <div className="w-full max-w-6xl mx-auto px-6 sm:px-8 grid lg:grid-cols-[1fr_420px] gap-12 lg:gap-20 items-center">
          <section className="formal-login-intro">
            <div className="text-sm font-medium text-primary-600 mb-4">
              {lang === 'zh' ? '电力数据分析与预测' : 'Power data analysis and forecasting'}
            </div>
            <h1 className="text-3xl sm:text-4xl font-semibold text-ink leading-tight tracking-wide">
              {lang === 'zh' ? '电网负荷预测与运行分析' : 'Grid load forecasts and operational analysis'}
            </h1>
            <p className="text-sm sm:text-base text-muted leading-7 mt-5 max-w-xl">
              {lang === 'zh'
                ? '基于 ISO-NE 新英格兰区域电网数据，提供负荷、电价及光伏预测，支持历史数据查询和预测误差分析。'
                : 'Forecast load, electricity prices and solar generation using ISO-NE New England data, with historical queries and forecast evaluation.'}
            </p>
            <div className="mt-8 border-t border-edge max-w-xl">
              {functions.map(({ icon: Icon, title, description }) => (
                <div key={title} className="flex gap-4 py-5 border-b border-edge">
                  <Icon className="w-5 h-5 text-primary-600 shrink-0 mt-1" strokeWidth={1.7} aria-hidden="true" />
                  <div>
                    <h2 className="text-sm font-semibold text-ink">{title}</h2>
                    <p className="text-sm text-muted mt-1 leading-6">{description}</p>
                  </div>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted mt-5 leading-6">
              {lang === 'zh' ? '数据来源：ISO-NE、Open-Meteo　｜　时间基准：美国东部时间' : 'Data: ISO-NE and Open-Meteo · Time zone: US Eastern'}
            </p>
          </section>

          <CyberLoginForm
            onLoginSuccess={handleLoginSuccess}
            onOpenRegister={() => setIsRegisterOpen(true)}
            lang={lang}
          />
        </div>
      </main>

      <footer className="px-6 py-5 text-center text-xs text-muted border-t border-edge bg-surface-header leading-6">
        {lang === 'zh' ? '基于 TensorFlow 的智能电网负荷预测系统　｜　本地运行' : 'TensorFlow Smart Grid Forecasting System · Local operation'}
      </footer>

      <RegisterModal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        onRegisterSuccess={handleRegisterSuccess}
        lang={lang}
      />
    </div>
  )
}

export default Login
