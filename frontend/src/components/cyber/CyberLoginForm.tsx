import { useState } from 'react'
import { User, Lock, Eye, EyeOff, RefreshCw, AlertCircle } from 'lucide-react'

interface CyberLoginFormProps {
  onLoginSuccess: (username: string, password: string, rememberMe: boolean) => Promise<void>
  onOpenRegister: () => void
  lang: 'zh' | 'en'
}

export function CyberLoginForm({ onLoginSuccess, onOpenRegister, lang }: CyberLoginFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [captchaInput, setCaptchaInput] = useState('')
  const [captchaCode, setCaptchaCode] = useState(() => Math.floor(1000 + Math.random() * 9000).toString())
  const [rememberMe, setRememberMe] = useState(true)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const [showHelp, setShowHelp] = useState(false)
  const zh = lang === 'zh'

  const refreshCaptcha = () => {
    setCaptchaCode(Math.floor(1000 + Math.random() * 9000).toString())
    setCaptchaInput('')
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setErrorMessage('')
    const trimmedCaptcha = captchaInput.trim()
    if (!trimmedCaptcha) {
      setErrorMessage(zh ? '请输入验证码' : 'Please enter the verification code')
      return
    }
    if (trimmedCaptcha !== captchaCode) {
      setErrorMessage(zh ? '验证码错误，请重新输入' : 'Incorrect verification code')
      return
    }
    setIsLoading(true)
    try {
      await onLoginSuccess(username, password, rememberMe)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : (zh ? '登录失败，请检查账号和密码' : 'Sign-in failed. Check your credentials.'))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <section className="formal-login-form w-full max-w-lg mx-auto bg-surface border border-edge rounded-lg p-7 sm:p-9 shadow-sm">
      <div className="mb-7 pb-5 border-b border-edge">
        <h2 className="text-xl font-semibold text-ink">{zh ? '用户登录' : 'User sign-in'}</h2>
        <p className="text-sm text-muted mt-2">{zh ? '请输入账号和密码进入系统' : 'Enter your account and password to continue'}</p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {errorMessage && (
          <div role="alert" className="flex items-start gap-2 p-3 border border-red-200 rounded bg-red-50 text-red-700 text-sm">
            <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
            <span>{errorMessage}</span>
          </div>
        )}

        <div>
          <label htmlFor="login-username" className="block text-sm text-ink mb-2">{zh ? '账号' : 'Account'}</label>
          <div className="relative">
            <User className="absolute left-3 top-3 w-4 h-4 text-muted" aria-hidden="true" />
            <input
              id="login-username" name="username" type="text" autoComplete="username" required
              value={username} onChange={event => setUsername(event.target.value)}
              placeholder={zh ? '请输入系统账号' : 'Enter your account'}
              className="w-full h-11 rounded border border-edge pl-10 pr-3 text-sm bg-surface-raised text-ink placeholder-slate-500 focus:border-primary-600 focus:ring-1 focus:ring-primary-600 outline-none"
            />
          </div>
        </div>

        <div>
          <label htmlFor="login-password" className="block text-sm text-ink mb-2">{zh ? '密码' : 'Password'}</label>
          <div className="relative">
            <Lock className="absolute left-3 top-3 w-4 h-4 text-muted" aria-hidden="true" />
            <input
              id="login-password" name="password" type={showPassword ? 'text' : 'password'} autoComplete="current-password" required
              value={password} onChange={event => setPassword(event.target.value)}
              placeholder={zh ? '请输入密码' : 'Enter your password'}
              className="w-full h-11 rounded border border-edge pl-10 pr-11 text-sm bg-surface-raised text-ink placeholder-slate-500 focus:border-primary-600 focus:ring-1 focus:ring-primary-600 outline-none"
            />
            <button
              type="button" onClick={() => setShowPassword(!showPassword)}
              aria-label={showPassword ? (zh ? '隐藏密码' : 'Hide password') : (zh ? '显示密码' : 'Show password')}
              className="absolute right-0.5 top-1 flex h-9 w-9 items-center justify-center rounded text-muted hover:text-primary-600 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-primary-600"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>
        </div>

        <div>
          <label htmlFor="login-captcha" className="block text-sm text-ink mb-2">{zh ? '验证码' : 'Verification code'}</label>
          <div className="flex items-center gap-3">
            <input
              id="login-captcha" name="captcha" type="text" inputMode="numeric" autoComplete="off" maxLength={4}
              value={captchaInput} onChange={event => setCaptchaInput(event.target.value)}
              placeholder={zh ? '请输入右侧验证码' : 'Enter the code'}
              className="min-w-0 flex-1 h-11 rounded border border-edge px-3 text-sm bg-surface-raised text-ink placeholder-slate-500 focus:border-primary-600 focus:ring-1 focus:ring-primary-600 outline-none"
            />
            <button
              type="button" onClick={refreshCaptcha} title={zh ? '点击刷新验证码' : 'Refresh code'}
              aria-label={zh ? '刷新验证码' : 'Refresh code'}
              className="flex items-center justify-between gap-3 h-11 px-3 rounded border border-edge bg-surface-muted text-ink"
            >
              <span className="font-mono text-lg font-semibold tracking-[0.2em]">{captchaCode}</span>
              <RefreshCw className="w-3.5 h-3.5 text-muted" aria-hidden="true" />
            </button>
          </div>
        </div>

        <div className="flex items-center justify-between text-sm">
          <label className="flex items-center gap-2 text-muted cursor-pointer">
            <input type="checkbox" checked={rememberMe} onChange={event => setRememberMe(event.target.checked)} className="accent-primary-600" />
            <span>{zh ? '记住登录状态' : 'Remember me'}</span>
          </label>
          <button type="button" onClick={() => setShowHelp(!showHelp)} aria-expanded={showHelp} className="inline-flex min-h-[32px] items-center px-1 text-primary-600 hover:underline">
            {zh ? '登录帮助' : 'Sign-in help'}
          </button>
        </div>
        {showHelp && (
          <p className="text-xs text-muted bg-surface-muted p-3 rounded leading-6">
            {zh ? '如忘记账号或密码，请联系系统管理员。首次使用可通过下方入口注册账号。' : 'Contact the system administrator if you have forgotten your credentials. New users can register below.'}
          </p>
        )}

        <button type="submit" disabled={isLoading} className="w-full h-11 bg-primary-600 hover:bg-primary-700 rounded text-white text-sm font-medium disabled:opacity-60 disabled:cursor-wait">
          {isLoading ? (zh ? '正在登录…' : 'Signing in…') : (zh ? '登 录' : 'Sign in')}
        </button>
      </form>

      <div className="mt-6 pt-5 border-t border-edge text-center text-sm text-muted">
        <span>{zh ? '还没有账号？' : 'Need an account? '}</span>
        <button type="button" onClick={onOpenRegister} className="ml-1 inline-flex min-h-[32px] items-center px-1 text-primary-600 hover:underline">{zh ? '注册账号' : 'Register'}</button>
      </div>
    </section>
  )
}
