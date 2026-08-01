import { useState } from 'react';
import {
  User,
  Lock,
  Eye,
  EyeOff,
  ShieldCheck,
  Zap,
  Scan,
  UserPlus,
  KeyRound,
  Sparkles,
  ArrowRight,
  CheckCircle,
  HelpCircle,
} from 'lucide-react';
import { cyberAudio } from '../../utils/audio';

interface CyberLoginFormProps {
  onLoginSuccess: (username: string, password: string, rememberMe: boolean) => Promise<void>;
  onOpenBiometric: () => void;
  onOpenRegister: () => void;
  lang: 'zh' | 'en';
}

export function CyberLoginForm({
  onLoginSuccess,
  onOpenBiometric,
  onOpenRegister,
  lang,
}: CyberLoginFormProps) {
  const [selectedRole, setSelectedRole] = useState<'dispatcher' | 'analyst' | 'expert' | 'admin'>('dispatcher');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [captchaInput, setCaptchaInput] = useState('');
  const [captchaCode, setCaptchaCode] = useState('7892');
  const [rememberMe, setRememberMe] = useState(true);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  const getPasswordStrength = (pwd: string) => {
    if (!pwd) return { score: 0, label: lang === 'zh' ? '未输入' : 'Empty', color: 'bg-slate-700' };
    if (pwd.length < 6) return { score: 1, label: lang === 'zh' ? '弱' : 'Weak', color: 'bg-rose-500' };
    if (pwd.length < 10) return { score: 2, label: lang === 'zh' ? '中等' : 'Medium', color: 'bg-amber-400' };
    return { score: 3, label: lang === 'zh' ? '量子加密级' : 'Quantum Safe', color: 'bg-emerald-400' };
  };

  const strength = getPasswordStrength(password);

  const refreshCaptcha = () => {
    cyberAudio.playScanBeep();
    const newCode = Math.floor(1000 + Math.random() * 9000).toString();
    setCaptchaCode(newCode);
    setCaptchaInput('');
  };

  const handleRoleSelect = (role: 'dispatcher' | 'analyst' | 'expert' | 'admin') => {
    cyberAudio.playClick();
    setSelectedRole(role);
    setErrorMessage('');
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage('');

    if (captchaInput && captchaInput !== captchaCode) {
      cyberAudio.playScanBeep();
      setErrorMessage(lang === 'zh' ? '动态验证码错误，请重新输入' : 'Invalid Cyber Captcha Code');
      return;
    }

    cyberAudio.playClick();
    setIsLoading(true);

    try {
      await onLoginSuccess(username, password, rememberMe);
    } catch (err: any) {
      cyberAudio.playScanBeep();
      const apiMsg =
        err?.message ||
        (lang === 'zh' ? '电网身份验证失败，请检查账号密匙' : 'Authentication failed. Check credentials.');
      setErrorMessage(String(apiMsg));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="relative w-full max-w-lg mx-auto rounded-3xl cyber-glass p-6 sm:p-8 border border-cyan-500/40 shadow-[0_0_80px_rgba(6,182,212,0.25)] overflow-hidden font-tech text-slate-100">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-transparent via-cyan-400 via-purple-500 to-transparent shadow-[0_0_15px_#06b6d4]" />

      <div className="cyber-corner-tl" />
      <div className="cyber-corner-tr" />
      <div className="cyber-corner-bl" />
      <div className="cyber-corner-br" />

      <div className="text-center mb-6">
        <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-cyan-950/70 border border-cyan-500/40 text-cyan-300 text-xs font-mono mb-2 shadow-[0_0_12px_rgba(6,182,212,0.3)]">
          <Zap className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span>SG-LOAD FORECAST v4.8 // AUTH PORTAL</span>
        </div>

        <h2 className="text-2xl sm:text-3xl font-cyber font-black tracking-wider bg-gradient-to-r from-cyan-300 via-purple-200 to-cyan-400 bg-clip-text text-transparent drop-shadow-[0_0_20px_rgba(6,182,212,0.5)]">
          {lang === 'zh' ? '智能电网负荷预测系统' : 'Smart Grid Load Forecasting'}
        </h2>
        <p className="text-xs text-slate-400 mt-1 font-mono">
          {lang === 'zh'
            ? '基于AI与时序神经网络的电网负荷精准预测平台 · 毕业设计控制端'
            : 'AI-Powered Power Load Forecasting Graduation Design System'}
        </p>
      </div>

      {/* Role Selection Tabs */}
      <div className="mb-5">
        <label className="block text-[11px] font-mono text-cyan-300/80 uppercase mb-1.5 flex items-center justify-between">
          <span>{lang === 'zh' ? '1. 选择登入角色身份' : '1. SELECT ACCESS ROLE'}</span>
          <span className="text-purple-400 text-[10px]">({lang === 'zh' ? '身份标签（需输入账号密匙）' : 'Role tag (enter credentials)'})</span>
        </label>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs font-mono">
          <button
            type="button" onClick={() => handleRoleSelect('dispatcher')}
            className={`p-2 rounded-xl border text-center transition-all flex flex-col items-center justify-center space-y-1 cursor-pointer ${
              selectedRole === 'dispatcher' ? 'bg-cyan-500/25 border-cyan-400 text-cyan-300 shadow-[0_0_15px_rgba(6,182,212,0.4)]' : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-cyan-300 hover:border-slate-700'
            }`}
          >
            <Zap className="w-4 h-4" />
            <span className="text-[11px] font-bold">{lang === 'zh' ? '调度员' : 'Dispatcher'}</span>
          </button>
          <button
            type="button" onClick={() => handleRoleSelect('analyst')}
            className={`p-2 rounded-xl border text-center transition-all flex flex-col items-center justify-center space-y-1 cursor-pointer ${
              selectedRole === 'analyst' ? 'bg-purple-500/25 border-purple-400 text-purple-300 shadow-[0_0_15px_rgba(168,85,247,0.4)]' : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-purple-300 hover:border-slate-700'
            }`}
          >
            <Sparkles className="w-4 h-4" />
            <span className="text-[11px] font-bold">{lang === 'zh' ? '算法工程师' : 'AI Analyst'}</span>
          </button>
          <button
            type="button" onClick={() => handleRoleSelect('expert')}
            className={`p-2 rounded-xl border text-center transition-all flex flex-col items-center justify-center space-y-1 cursor-pointer ${
              selectedRole === 'expert' ? 'bg-amber-500/25 border-amber-400 text-amber-300 shadow-[0_0_15px_rgba(245,158,11,0.4)]' : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-amber-300 hover:border-slate-700'
            }`}
          >
            <ShieldCheck className="w-4 h-4" />
            <span className="text-[11px] font-bold">{lang === 'zh' ? '答辩评委' : 'Reviewer'}</span>
          </button>
          <button
            type="button" onClick={() => handleRoleSelect('admin')}
            className={`p-2 rounded-xl border text-center transition-all flex flex-col items-center justify-center space-y-1 cursor-pointer ${
              selectedRole === 'admin' ? 'bg-emerald-500/25 border-emerald-400 text-emerald-300 shadow-[0_0_15px_rgba(16,185,129,0.4)]' : 'bg-slate-900/80 border-slate-800 text-slate-400 hover:text-emerald-300 hover:border-slate-700'
            }`}
          >
            <KeyRound className="w-4 h-4" />
            <span className="text-[11px] font-bold">{lang === 'zh' ? '系统管理员' : 'Admin'}</span>
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4 font-mono text-xs">
        {errorMessage && (
          <div className="p-3 rounded-xl bg-rose-950/80 border border-rose-500/50 text-rose-300 animate-shake flex items-center justify-between text-xs">
            <span>⚠️ {errorMessage}</span>
            <button type="button" onClick={() => setErrorMessage('')} className="text-rose-400 font-bold ml-2">×</button>
          </div>
        )}

        {/* Username Field */}
        <div>
          <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '控制台账号 / 编号' : 'Account Key / User ID'}</label>
          <div className="relative group">
            <User className="absolute left-3.5 top-3 w-4 h-4 text-cyan-400/80 group-focus-within:text-cyan-300 transition-colors" />
            <input
              type="text" required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder={lang === 'zh' ? '请输入系统账号' : 'User Account Key'}
              className="w-full bg-slate-950/80 border border-cyan-500/30 group-focus-within:border-cyan-400 group-focus-within:shadow-[0_0_15px_rgba(6,182,212,0.3)] rounded-xl pl-10 pr-3 py-2.5 text-slate-100 placeholder-slate-600 outline-none transition-all"
            />
          </div>
        </div>

        {/* Password Field */}
        <div>
          <div className="flex justify-between items-center mb-1">
            <label className="text-slate-300 font-sans">{lang === 'zh' ? '加密授权密匙' : 'Cyber Password'}</label>
            <div className="flex items-center space-x-1 text-[10px]">
              <span className="text-slate-400">{lang === 'zh' ? '强度:' : 'Strength:'}</span>
              <span className={`font-bold ${strength.color.replace('bg-', 'text-')}`}>{strength.label}</span>
            </div>
          </div>

          <div className="relative group">
            <Lock className="absolute left-3.5 top-3 w-4 h-4 text-cyan-400/80 group-focus-within:text-cyan-300 transition-colors" />
            <input
              type={showPassword ? 'text' : 'password'} required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full bg-slate-950/80 border border-cyan-500/30 group-focus-within:border-cyan-400 group-focus-within:shadow-[0_0_15px_rgba(6,182,212,0.3)] rounded-xl pl-10 pr-10 py-2.5 text-slate-100 placeholder-slate-600 outline-none transition-all"
            />
            <button
              type="button"
              onClick={() => { cyberAudio.playClick(); setShowPassword(!showPassword); }}
              className="absolute right-3 top-3 text-slate-400 hover:text-cyan-300 transition-colors"
            >
              {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
            </button>
          </div>

          <div className="flex space-x-1 mt-1.5 h-1">
            {[1, 2, 3].map((step) => (
              <div key={step} className={`h-full flex-1 rounded-full transition-all duration-300 ${strength.score >= step ? strength.color : 'bg-slate-800'}`} />
            ))}
          </div>
        </div>

        {/* Captcha */}
        <div>
          <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '电网动态防御校验码' : 'Security Captcha Token'}</label>
          <div className="flex items-center space-x-3">
            <div className="relative flex-1">
              <ShieldCheck className="absolute left-3.5 top-3 w-4 h-4 text-cyan-400/80" />
              <input
                type="text" value={captchaInput}
                onChange={(e) => setCaptchaInput(e.target.value)}
                placeholder={lang === 'zh' ? '输入右侧校验码' : 'Enter code'}
                className="w-full bg-slate-950/80 border border-cyan-500/30 focus:border-cyan-400 rounded-xl pl-10 pr-3 py-2.5 text-slate-100 placeholder-slate-600 outline-none transition-all"
              />
            </div>
            <button
              type="button" onClick={refreshCaptcha}
              title={lang === 'zh' ? '点击刷新校验码' : 'Refresh Token'}
              className="px-4 py-2.5 bg-cyan-950/80 border border-cyan-500/50 rounded-xl font-cyber text-base text-cyan-300 tracking-widest font-black shadow-[inset_0_0_10px_rgba(6,182,212,0.3)] hover:border-cyan-400 transition-all cursor-pointer relative overflow-hidden group"
            >
              <span className="relative z-10">{captchaCode}</span>
              <div className="absolute inset-0 bg-cyan-500/10 transform -skew-x-12 group-hover:translate-x-full transition-transform duration-500" />
            </button>
          </div>
        </div>

        {/* Remember me & Help */}
        <div className="flex items-center justify-between text-[11px] pt-1 text-slate-400">
          <label className="flex items-center space-x-2 cursor-pointer group">
            <input
              type="checkbox" checked={rememberMe}
              onChange={(e) => setRememberMe(e.target.checked)}
              className="rounded bg-slate-900 border-slate-700 text-cyan-500 focus:ring-0 accent-cyan-500 cursor-pointer"
            />
            <span className="group-hover:text-slate-200 transition-colors">{lang === 'zh' ? '记住电网控制台凭证 (Remember Token)' : 'Remember Grid Credentials'}</span>
          </label>
          <button
            type="button"
            onClick={() => { cyberAudio.playClick(); alert(lang === 'zh' ? '如遗失密匙，请联系指导教师或答辩组系统管理员。或使用下面的注册通道申请新账号！' : 'Contact Professor or use the Register button below!'); }}
            className="text-cyan-400 hover:underline flex items-center gap-0.5"
          >
            <HelpCircle className="w-3 h-3" />
            <span>{lang === 'zh' ? '忘记密匙?' : 'Reset Token?'}</span>
          </button>
        </div>

        {/* Submit Button */}
        <div className="pt-2">
          <button
            type="submit" disabled={isLoading}
            onMouseEnter={() => cyberAudio.playHover()}
            className="w-full py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 via-blue-600 to-purple-600 hover:from-cyan-400 hover:to-purple-500 text-slate-950 font-cyber font-black tracking-widest text-sm shadow-[0_0_25px_rgba(6,182,212,0.5)] transition-all flex items-center justify-center space-x-2 cursor-pointer group"
          >
            {isLoading ? (
              <div className="flex items-center space-x-2 text-slate-950">
                <span className="w-4 h-4 border-2 border-slate-950 border-t-transparent rounded-full animate-spin"></span>
                <span>{lang === 'zh' ? '电网网络身份安全解密中...' : 'AUTHENTICATING...'}</span>
              </div>
            ) : (
              <>
                <span>{lang === 'zh' ? '验证授权并进入负荷预测大厅' : 'AUTHORIZE & ENTER CONSOLE'}</span>
                <ArrowRight className="w-4 h-4 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </button>
        </div>
      </form>

      {/* Alternative Access */}
      <div className="mt-6 pt-5 border-t border-cyan-500/20 space-y-3 font-mono text-xs">
        <div className="text-slate-400 text-[11px] text-center">{lang === 'zh' ? '—— 答辩评审快捷极速通道 ——' : '—— Quick Reviewer Channels ——'}</div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
          <button
            type="button" onClick={() => { cyberAudio.playClick(); onOpenBiometric(); }}
            className="w-full py-2.5 px-3 rounded-xl bg-purple-950/50 hover:bg-purple-900/60 border border-purple-500/40 text-purple-300 hover:text-purple-200 transition-all flex items-center justify-center space-x-2 shadow-[0_0_12px_rgba(168,85,247,0.2)] cursor-pointer"
          >
            <Scan className="w-4 h-4 text-purple-400" />
            <span className="font-bold">{lang === 'zh' ? '人脸/量子特征扫码登录' : 'Biometric Cyber Scan'}</span>
          </button>
          <button
            type="button" onClick={() => { cyberAudio.playClick(); onOpenRegister(); }}
            className="w-full py-2.5 px-3 rounded-xl bg-amber-950/50 hover:bg-amber-900/60 border border-amber-500/40 text-amber-300 hover:text-amber-200 transition-all flex items-center justify-center space-x-2 shadow-[0_0_12px_rgba(245,158,11,0.2)] cursor-pointer"
          >
            <CheckCircle className="w-4 h-4 text-amber-400" />
            <span className="font-bold">{lang === 'zh' ? '注册账号' : 'Register Account'}</span>
          </button>
        </div>
        <div className="pt-1 text-center">
          <button
            type="button" onClick={() => { cyberAudio.playClick(); onOpenRegister(); }}
            className="text-slate-400 hover:text-cyan-300 text-xs transition-colors inline-flex items-center space-x-1.5"
          >
            <UserPlus className="w-3.5 h-3.5 text-cyan-400" />
            <span>{lang === 'zh' ? '没有账号？点击注册' : 'No account? Register here'}</span>
          </button>
        </div>
      </div>
    </div>
  );
}
