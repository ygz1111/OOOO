import { useEffect, useState } from 'react'
import { X, CheckCircle2, AlertCircle } from 'lucide-react'

interface RegisterModalProps {
  isOpen: boolean
  onClose: () => void
  onRegisterSuccess: (data: {
    username: string
    email: string
    password: string
    full_name?: string
    department?: string
    phone?: string
  }) => Promise<void>
  lang: 'zh' | 'en'
}

const DEPARTMENTS = ['调度中心', '运维部', '技术部', '数据部', '管理部门']
const inputClass = 'w-full h-10 rounded border border-edge px-3 text-sm text-ink bg-surface-raised placeholder-slate-500 focus:border-primary-600 focus:ring-1 focus:ring-primary-600 outline-none'

export function RegisterModal({ isOpen, onClose, onRegisterSuccess, lang }: RegisterModalProps) {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    full_name: '',
    department: '',
    phone: '',
    password: '',
    confirmPassword: '',
  })
  const [submitted, setSubmitted] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')
  const zh = lang === 'zh'

  useEffect(() => {
    if (!isOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !isLoading) onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [isOpen, isLoading, onClose])

  useEffect(() => {
    if (!submitted) return
    const timer = setTimeout(() => {
      setSubmitted(false)
      onClose()
    }, 2000)
    return () => clearTimeout(timer)
  }, [submitted, onClose])

  if (!isOpen) return null

  // Keep registration validation aligned with the existing backend schema.
  const validate = (): string | null => {
    if (!formData.username || formData.username.length < 3) return zh ? '用户名至少 3 个字符' : 'Username must be at least 3 characters'
    if (!/^[a-zA-Z0-9]+$/.test(formData.username)) return zh ? '用户名只能包含字母和数字' : 'Username must be alphanumeric only'
    if (!formData.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) return zh ? '邮箱格式不正确' : 'Invalid email format'
    if (!formData.password || formData.password.length < 8) return zh ? '密码至少 8 位' : 'Password must be at least 8 characters'
    if (!/[A-Z]/.test(formData.password)) return zh ? '密码必须包含大写字母' : 'Password must contain an uppercase letter'
    if (!/\d/.test(formData.password)) return zh ? '密码必须包含数字' : 'Password must contain a digit'
    if (formData.password !== formData.confirmPassword) return zh ? '两次输入的密码不一致' : 'Passwords do not match'
    return null
  }

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setErrorMessage('')
    const validationError = validate()
    if (validationError) {
      setErrorMessage(validationError)
      return
    }

    setIsLoading(true)
    try {
      await onRegisterSuccess({
        username: formData.username,
        email: formData.email,
        password: formData.password,
        full_name: formData.full_name || undefined,
        department: formData.department || undefined,
        phone: formData.phone || undefined,
      })
      setSubmitted(true)
    } catch (error: unknown) {
      setErrorMessage(error instanceof Error ? error.message : (zh ? '注册失败，请稍后重试' : 'Registration failed. Please try again.'))
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="formal-register fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40">
      <section role="dialog" aria-modal="true" aria-labelledby="register-title" className="relative w-full max-w-lg max-h-[90vh] overflow-y-auto rounded-lg border border-edge bg-surface p-6 sm:p-8 shadow-xl text-ink">
        <button
          type="button" onClick={onClose} disabled={isLoading}
          aria-label={zh ? '关闭注册窗口' : 'Close registration'}
          className="absolute top-5 right-5 p-1 text-muted hover:text-ink disabled:opacity-40"
        >
          <X className="w-5 h-5" />
        </button>

        {submitted ? (
          <div className="py-10 text-center">
            <CheckCircle2 className="w-10 h-10 text-green-700 mx-auto" aria-hidden="true" />
            <h3 id="register-title" className="text-xl font-semibold text-ink mt-4">{zh ? '账号注册成功' : 'Account created'}</h3>
            <p className="text-sm text-muted mt-3">{zh ? '请使用刚刚注册的账号和密码登录。' : 'Sign in with the account and password you just registered.'}</p>
          </div>
        ) : (
          <>
            <div className="mb-6 pb-5 border-b border-edge">
              <h3 id="register-title" className="text-xl font-semibold text-ink">{zh ? '注册账号' : 'Register an account'}</h3>
              <p className="text-sm text-muted mt-2">{zh ? '填写账号信息，用于登录预测与分析系统。' : 'Create an account for the forecasting and analysis system.'}</p>
            </div>

            {errorMessage && (
              <div role="alert" className="mb-5 flex items-start gap-2 p-3 border border-red-200 rounded bg-red-50 text-red-700 text-sm">
                <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" aria-hidden="true" />
                <span>{errorMessage}</span>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4 text-sm">
              <div>
                <label htmlFor="register-username" className="block text-ink mb-2">{zh ? '账号' : 'Username'}</label>
                <input id="register-username" name="username" type="text" autoComplete="username" required minLength={3} autoFocus
                  value={formData.username} onChange={event => setFormData({ ...formData, username: event.target.value })}
                  placeholder={zh ? '至少 3 位，仅限字母和数字' : '3+ letters and digits'} className={inputClass} />
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="register-email" className="block text-ink mb-2">{zh ? '邮箱' : 'Email'}</label>
                  <input id="register-email" name="email" type="email" autoComplete="email" required
                    value={formData.email} onChange={event => setFormData({ ...formData, email: event.target.value })}
                    placeholder={zh ? '请输入邮箱' : 'Enter your email'} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="register-name" className="block text-ink mb-2">{zh ? '姓名（选填）' : 'Full name (optional)'}</label>
                  <input id="register-name" name="name" type="text" autoComplete="name"
                    value={formData.full_name} onChange={event => setFormData({ ...formData, full_name: event.target.value })}
                    placeholder={zh ? '请输入姓名' : 'Enter your name'} className={inputClass} />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="register-phone" className="block text-ink mb-2">{zh ? '电话（选填）' : 'Phone (optional)'}</label>
                  <input id="register-phone" name="tel" type="tel" autoComplete="tel"
                    value={formData.phone} onChange={event => setFormData({ ...formData, phone: event.target.value })}
                    placeholder={zh ? '请输入联系电话' : 'Enter your phone'} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="register-department" className="block text-ink mb-2">{zh ? '部门（选填）' : 'Department (optional)'}</label>
                  <select id="register-department" value={formData.department} onChange={event => setFormData({ ...formData, department: event.target.value })} className={inputClass}>
                    <option value="">{zh ? '请选择部门' : 'Select department'}</option>
                    {DEPARTMENTS.map(department => <option key={department} value={department}>{department}</option>)}
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label htmlFor="register-password" className="block text-ink mb-2">{zh ? '密码' : 'Password'}</label>
                  <input id="register-password" name="password" type="password" autoComplete="new-password" required minLength={8}
                    value={formData.password} onChange={event => setFormData({ ...formData, password: event.target.value })}
                    placeholder={zh ? '请输入密码' : 'Enter a password'} className={inputClass} />
                </div>
                <div>
                  <label htmlFor="register-password-confirm" className="block text-ink mb-2">{zh ? '确认密码' : 'Confirm password'}</label>
                  <input id="register-password-confirm" name="confirm-password" type="password" autoComplete="new-password" required
                    value={formData.confirmPassword} onChange={event => setFormData({ ...formData, confirmPassword: event.target.value })}
                    placeholder={zh ? '请再次输入密码' : 'Repeat the password'} className={inputClass} />
                </div>
              </div>
              <p className="text-xs text-muted">{zh ? '密码至少 8 位，须包含大写字母和数字。' : 'Use at least 8 characters, including an uppercase letter and a digit.'}</p>

              <button type="submit" disabled={isLoading} className="w-full h-11 rounded bg-primary-600 hover:bg-primary-700 text-white font-medium disabled:opacity-60 disabled:cursor-wait">
                {isLoading ? (zh ? '正在提交…' : 'Submitting…') : (zh ? '注册账号' : 'Register')}
              </button>
            </form>
          </>
        )}
      </section>
    </div>
  )
}
