import { useState } from 'react';
import { User, Mail, KeyRound, School, X, Check, Sparkles, Building2, Phone } from 'lucide-react';
import { cyberAudio } from '../../utils/audio';

interface RegisterModalProps {
  isOpen: boolean;
  onClose: () => void;
  onRegisterSuccess: (data: {
    username: string;
    email: string;
    password: string;
    full_name?: string;
    department?: string;
    phone?: string;
  }) => Promise<void>;
  lang: 'zh' | 'en';
}

const DEPARTMENTS = ['调度中心', '运维部', '技术部', '数据部', '管理部门'];

export function RegisterModal({ isOpen, onClose, onRegisterSuccess, lang }: RegisterModalProps) {
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    studentId: '',
    researchTopic: 'short_term_load',
    full_name: '',
    department: '',
    phone: '',
    password: '',
    confirmPassword: '',
  });
  const [submitted, setSubmitted] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [errorMessage, setErrorMessage] = useState('');

  if (!isOpen) return null;

  // 前端校验（与后端 UserCreate schema 一致）
  const validate = (): string | null => {
    if (!formData.username || formData.username.length < 3) {
      return lang === 'zh' ? '用户名至少3个字符' : 'Username must be at least 3 characters';
    }
    if (!/^[a-zA-Z0-9]+$/.test(formData.username)) {
      return lang === 'zh' ? '用户名只能包含字母和数字' : 'Username must be alphanumeric only';
    }
    if (!formData.email || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(formData.email)) {
      return lang === 'zh' ? '邮箱格式不正确' : 'Invalid email format';
    }
    if (!formData.password || formData.password.length < 8) {
      return lang === 'zh' ? '密码至少8位' : 'Password must be at least 8 characters';
    }
    if (!/[A-Z]/.test(formData.password)) {
      return lang === 'zh' ? '密码必须包含大写字母' : 'Password must contain an uppercase letter';
    }
    if (!/\d/.test(formData.password)) {
      return lang === 'zh' ? '密码必须包含数字' : 'Password must contain a digit';
    }
    if (formData.password !== formData.confirmPassword) {
      return lang === 'zh' ? '两次输入的密匙不一致' : 'Passwords do not match';
    }
    return null;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMessage('');

    const validationError = validate();
    if (validationError) {
      setErrorMessage(validationError);
      return;
    }

    setIsLoading(true);
    try {
      await onRegisterSuccess({
        username: formData.username,
        email: formData.email,
        password: formData.password,
        full_name: formData.full_name || undefined,
        department: formData.department || undefined,
        phone: formData.phone || undefined,
      });
      cyberAudio.playSuccess();
      setSubmitted(true);
      setTimeout(() => {
        setSubmitted(false);
        onClose();
      }, 2000);
    } catch (err: any) {
      const apiMsg =
        err?.message ||
        (lang === 'zh' ? '注册申请提交失败，请稍后重试' : 'Registration failed. Please try again.');
      setErrorMessage(String(apiMsg));
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/85 backdrop-blur-xl animate-fadeIn font-tech text-slate-100">
      <div className="relative w-full max-w-lg rounded-2xl cyber-glass p-6 lg:p-8 border border-purple-500/40 shadow-[0_0_60px_rgba(168,85,247,0.25)]">
        <div className="cyber-corner-tl" />
        <div className="cyber-corner-tr" />
        <div className="cyber-corner-bl" />
        <div className="cyber-corner-br" />

        <button
          onClick={() => { cyberAudio.playClick(); onClose(); }}
          className="absolute top-4 right-4 p-1.5 rounded-lg text-slate-400 hover:text-purple-300 hover:bg-purple-500/10 border border-transparent hover:border-purple-500/30 transition-all"
        >
          <X className="w-5 h-5" />
        </button>

        {submitted ? (
          <div className="py-12 text-center space-y-4">
            <div className="inline-flex p-4 rounded-full bg-emerald-500/20 text-emerald-400 border border-emerald-500/40 animate-bounce">
              <Check className="w-10 h-10" />
            </div>
            <h3 className="text-2xl font-cyber font-bold text-emerald-300">{lang === 'zh' ? '申请提交成功！' : 'Application Submitted!'}</h3>
            <p className="text-sm text-slate-300">{lang === 'zh' ? '毕业设计课题账号已创建，初始密匙已下发，请返回登录页面...' : 'Account created successfully. Please login...'}</p>
          </div>
        ) : (
          <div>
            <div className="mb-6">
              <div className="flex items-center space-x-2 text-purple-400">
                <Sparkles className="w-5 h-5" />
                <h3 className="text-xl font-cyber font-bold text-purple-300">{lang === 'zh' ? '科研/毕业设计账号权限申请' : 'Request Project Research Clearance'}</h3>
              </div>
              <p className="text-xs text-slate-400 mt-1">{lang === 'zh' ? '录入高校学号/工号，开通智能电网负荷预测算力节点权限' : 'Register student credentials for Smart Grid load forecasting GPU node'}</p>
            </div>

            {errorMessage && (
              <div className="mb-4 p-3 rounded-xl bg-rose-950/80 border border-rose-500/50 text-rose-300 text-xs flex items-center justify-between">
                <span>⚠️ {errorMessage}</span>
                <button type="button" onClick={() => setErrorMessage('')} className="text-rose-400 font-bold ml-2">×</button>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4 text-xs font-mono">
              <div>
                <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '用户账号' : 'Username'}</label>
                <div className="relative">
                  <User className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                  <input
                    type="text" required minLength={3}
                    value={formData.username}
                    onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                    placeholder={lang === 'zh' ? '仅字母和数字，如：gridadmin' : 'Alphanumeric only, e.g. gridadmin'}
                    className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                  />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '学术邮箱' : 'Academic Email'}</label>
                  <div className="relative">
                    <Mail className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <input
                      type="email" required
                      value={formData.email}
                      onChange={(e) => setFormData({ ...formData, email: e.target.value })}
                      placeholder="student@edu.cn"
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '全名（选填）' : 'Full Name'}</label>
                  <div className="relative">
                    <School className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <input
                      type="text"
                      value={formData.full_name}
                      onChange={(e) => setFormData({ ...formData, full_name: e.target.value })}
                      placeholder={lang === 'zh' ? '如：李云飞' : 'e.g. John Doe'}
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                    />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '电话（选填）' : 'Phone'}</label>
                  <div className="relative">
                    <Phone className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <input
                      type="tel"
                      value={formData.phone}
                      onChange={(e) => setFormData({ ...formData, phone: e.target.value })}
                      placeholder="13800138000"
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                    />
                  </div>
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '部门（选填）' : 'Department'}</label>
                  <div className="relative">
                    <Building2 className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <select
                      value={formData.department}
                      onChange={(e) => setFormData({ ...formData, department: e.target.value })}
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all cursor-pointer"
                    >
                      <option value="">{lang === 'zh' ? '请选择部门' : 'Select department'}</option>
                      {DEPARTMENTS.map(dept => <option key={dept} value={dept}>{dept}</option>)}
                    </select>
                  </div>
                </div>
              </div>

              <div>
                <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '毕业设计细分方向' : 'Graduation Topic Area'}</label>
                <select
                  value={formData.researchTopic}
                  onChange={(e) => setFormData({ ...formData, researchTopic: e.target.value })}
                  className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg px-3 py-2 text-slate-100 outline-none transition-all"
                >
                  <option value="short_term_load">{lang === 'zh' ? '超短期电力负荷预测 (Short-Term Load)' : 'Short-Term Load Forecasting'}</option>
                  <option value="st_gcn">{lang === 'zh' ? '时空图卷积网络 (ST-GCN Grid Spatial)' : 'ST-GCN Busbar Spatial Model'}</option>
                  <option value="pv_storage">{lang === 'zh' ? '光伏+储能协同分布式预测' : 'PV + Energy Storage Forecast'}</option>
                  <option value="extreme_weather">{lang === 'zh' ? '极端天气下防灾负荷预警' : 'Extreme Weather Grid Resilience'}</option>
                </select>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '设置登录密匙' : 'Password'}</label>
                  <div className="relative">
                    <KeyRound className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <input
                      type="password" required minLength={8}
                      value={formData.password}
                      onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                      placeholder={lang === 'zh' ? '至少8位，含大写字母和数字' : '8+ chars, uppercase + digit'}
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                    />
                    {/* 密码要求提示 */}
                    <p className="mt-1 text-[10px] text-slate-500 font-mono">
                      {lang === 'zh' ? '要求：至少8位 + 大写字母 + 数字' : 'Requires: 8+ chars + uppercase + digit'}
                    </p>
                  </div>
                </div>
                <div>
                  <label className="block text-slate-300 mb-1 font-sans">{lang === 'zh' ? '确认密匙' : 'Confirm Password'}</label>
                  <div className="relative">
                    <KeyRound className="absolute left-3 top-2.5 w-4 h-4 text-slate-500" />
                    <input
                      type="password" required
                      value={formData.confirmPassword}
                      onChange={(e) => setFormData({ ...formData, confirmPassword: e.target.value })}
                      placeholder="••••••••"
                      className="w-full bg-slate-900/90 border border-slate-700 focus:border-purple-500 rounded-lg pl-9 pr-3 py-2 text-slate-100 outline-none transition-all"
                    />
                  </div>
                </div>
              </div>

              <div className="pt-2">
                <button
                  type="submit" disabled={isLoading}
                  onMouseEnter={() => cyberAudio.playHover()}
                  className="w-full py-3 rounded-xl bg-gradient-to-r from-purple-600 via-indigo-600 to-cyan-600 hover:from-purple-500 hover:to-cyan-500 text-white font-cyber font-bold tracking-wider shadow-[0_0_20px_rgba(168,85,247,0.4)] transition-all cursor-pointer disabled:opacity-60"
                >
                  {isLoading ? (lang === 'zh' ? '提交中...' : 'SUBMITTING...') : (lang === 'zh' ? '提交毕设密匙授权申请' : 'SUBMIT CLEARANCE REQUEST')}
                </button>
              </div>
            </form>
          </div>
        )}
      </div>
    </div>
  );
}
