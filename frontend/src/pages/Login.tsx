import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Radio, Activity, Cpu, Sparkles, CheckCircle2 } from 'lucide-react'
import { useAuth } from '../contexts/AuthContext'
import { RegisterRequest } from '../types/auth'
import { CyberHeader } from '../components/cyber/CyberHeader'
import { CyberFooter } from '../components/cyber/CyberFooter'
import { CyberMatrixCanvas } from '../components/cyber/CyberMatrixCanvas'
import { CyberLoginForm } from '../components/cyber/CyberLoginForm'
import { GridForecastPreviewHUD } from '../components/cyber/GridForecastPreviewHUD'
import { BiometricScannerModal } from '../components/cyber/BiometricScannerModal'
import { RegisterModal } from '../components/cyber/RegisterModal'

const Login: React.FC = () => {
  const { login, register, isAuthenticated } = useAuth()
  const navigate = useNavigate()
  const [lang, setLang] = useState<'zh' | 'en'>('zh')
  const [isBiometricOpen, setIsBiometricOpen] = useState(false)
  const [isRegisterOpen, setIsRegisterOpen] = useState(false)

  // 已登录用户自动跳转首页
  if (isAuthenticated) {
    navigate('/', { replace: true })
  }

  const handleLoginSuccess = async (username: string, password: string, rememberMe: boolean) => {
    await login({ username, password, remember_me: rememberMe })
    navigate('/', { replace: true })
  }

  const handleRegisterSuccess = async (data: RegisterRequest) => {
    await register(data)
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 relative overflow-x-hidden selection:bg-cyan-500 selection:text-slate-950">
      {/* Dynamic Cyber Matrix Node Canvas Backdrop */}
      <CyberMatrixCanvas intensity={1.2} />

      {/* Cyberpunk Futuristic Wallpaper Layer */}
      <div
        className="fixed inset-0 pointer-events-none z-0 bg-cover bg-center bg-no-repeat opacity-25 mix-blend-luminosity scale-105 transition-all duration-1000"
        style={{ backgroundImage: `url('/images/smart-grid-cyber.jpg')` }}
      />

      {/* Futuristic Scanline Overlay */}
      <div className="fixed inset-0 pointer-events-none z-10 scanline opacity-60" />

      {/* Dark Vignette radial gradient */}
      <div className="fixed inset-0 pointer-events-none z-10 bg-[radial-gradient(ellipse_at_center,transparent_0%,rgba(2,6,23,0.85)_100%)]" />

      {/* Top Header */}
      <CyberHeader lang={lang} setLang={setLang} />

      {/* Main Content Area */}
      <main className="relative z-20 min-h-[calc(100vh-110px)] pb-12">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-8 space-y-6">
          {/* Ticker Bar: Live Grid Status */}
          <div className="relative rounded-xl border border-cyan-500/20 bg-slate-950/80 backdrop-blur-md px-4 py-2.5 flex flex-wrap items-center justify-between text-xs font-mono text-slate-300 gap-2 shadow-[0_0_20px_rgba(6,182,212,0.1)]">
            <div className="flex items-center space-x-2">
              <span className="flex h-2.5 w-2.5 relative">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-cyan-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-cyan-500"></span>
              </span>
              <span className="text-cyan-300 font-bold font-cyber">
                {lang === 'zh' ? '国家电网调度中心 - 实时计算节点 #08' : 'State Grid Dispatch Node #08'}
              </span>
            </div>

            <div className="hidden sm:flex items-center space-x-6 text-[11px] text-slate-400">
              <span className="flex items-center space-x-1">
                <Radio className="w-3.5 h-3.5 text-cyan-400" />
                <span>{lang === 'zh' ? '全省主干电压: 220.4 kV (正常)' : 'Voltage: 220.4kV'}</span>
              </span>
              <span className="flex items-center space-x-1">
                <Activity className="w-3.5 h-3.5 text-emerald-400" />
                <span>{lang === 'zh' ? '系统频率: 49.98 Hz' : 'Frequency: 49.98Hz'}</span>
              </span>
              <span className="flex items-center space-x-1">
                <Cpu className="w-3.5 h-3.5 text-purple-400" />
                <span>{lang === 'zh' ? '神经网络拟合度: R² 0.987' : 'Model R²: 0.987'}</span>
              </span>
            </div>

            <div className="text-[11px] text-emerald-400 font-semibold bg-emerald-950/60 px-2.5 py-0.5 rounded border border-emerald-500/30 flex items-center gap-1">
              <CheckCircle2 className="w-3 h-3" />
              <span>{lang === 'zh' ? '毕业设计答辩系统 Ready' : 'Thesis Portal Online'}</span>
            </div>
          </div>

          {/* Main Dual Grid Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 lg:gap-8 items-start pt-2">
            {/* Left Column (Desktop): Grid Load Forecasting Live Preview HUD */}
            <div className="hidden lg:block lg:col-span-6 space-y-5">
              <GridForecastPreviewHUD lang={lang} />

              {/* Thesis Highlights Box */}
              <div className="rounded-2xl cyber-glass p-5 border border-purple-500/30 space-y-3 font-tech text-xs">
                <div className="flex items-center space-x-2 text-purple-300 font-cyber font-bold text-sm">
                  <Sparkles className="w-4 h-4 text-purple-400" />
                  <span>{lang === 'zh' ? '毕业设计核心创新点亮点展示' : 'Thesis Research Innovations'}</span>
                </div>

                <div className="grid grid-cols-2 gap-3 font-mono">
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                    <div className="text-cyan-400 font-bold mb-0.5">01 / 时空结合 (ST-GCN)</div>
                    <div className="text-slate-400 text-[11px]">{lang === 'zh' ? '构建变电站拓扑图，捕获空间电量分流传递' : 'Captures spatial topology load transfers'}</div>
                  </div>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                    <div className="text-purple-400 font-bold mb-0.5">02 / Transformer注意力</div>
                    <div className="text-slate-400 text-[11px]">{lang === 'zh' ? '多头自注意力机制提取气象突变与时间周期性' : 'Multi-head attention for weather spikes'}</div>
                  </div>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                    <div className="text-amber-400 font-bold mb-0.5">03 / 超短期负荷削峰</div>
                    <div className="text-slate-400 text-[11px]">{lang === 'zh' ? '提前15分钟提供可信度98%以上的调峰指令' : '15-min ahead peak shaving alert'}</div>
                  </div>
                  <div className="p-2.5 rounded-xl bg-slate-900/80 border border-slate-800">
                    <div className="text-emerald-400 font-bold mb-0.5">04 / 低算力延迟 (GPU)</div>
                    <div className="text-slate-400 text-[11px]">{lang === 'zh' ? '单个批次推理耗时仅1.8ms，满足实效调度' : 'Inference latency under 1.8ms'}</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Right Column: High-end Cyberpunk Login Form */}
            <div className="lg:col-span-6 w-full flex justify-center">
              <CyberLoginForm
                onLoginSuccess={handleLoginSuccess}
                onOpenBiometric={() => setIsBiometricOpen(true)}
                onOpenRegister={() => setIsRegisterOpen(true)}
                lang={lang}
              />
            </div>

            {/* Mobile-only Preview HUD below login on small screens */}
            <div className="block lg:hidden col-span-1 mt-4">
              <GridForecastPreviewHUD lang={lang} />
            </div>
          </div>
        </div>
      </main>

      {/* Modals */}
      <BiometricScannerModal
        isOpen={isBiometricOpen}
        onClose={() => setIsBiometricOpen(false)}
        lang={lang}
      />

      <RegisterModal
        isOpen={isRegisterOpen}
        onClose={() => setIsRegisterOpen(false)}
        onRegisterSuccess={handleRegisterSuccess}
        lang={lang}
      />

      {/* Footer */}
      <CyberFooter lang={lang} />
    </div>
  )
}

export default Login
