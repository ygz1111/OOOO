import { useState, useEffect } from 'react';
import { Scan, X, CheckCircle2, UserCheck, Sparkles, Cpu } from 'lucide-react';
import { cyberAudio } from '../../utils/audio';

interface BiometricScannerModalProps {
  isOpen: boolean;
  onClose: () => void;
  lang: 'zh' | 'en';
}

export function BiometricScannerModal({ isOpen, onClose, lang }: BiometricScannerModalProps) {
  const [progress, setProgress] = useState(0);
  const [scanStep, setScanStep] = useState<'initializing' | 'scanning_face' | 'verifying_quantum' | 'authenticated'>('initializing');

  useEffect(() => {
    if (!isOpen) {
      setProgress(0);
      setScanStep('initializing');
      return;
    }

    cyberAudio.playScanBeep();
    setScanStep('scanning_face');

    const interval = setInterval(() => {
      setProgress((prev) => {
        if (prev >= 100) {
          clearInterval(interval);
          setScanStep('authenticated');
          cyberAudio.playSuccess();
          return 100;
        }
        if (prev === 40) {
          setScanStep('verifying_quantum');
          cyberAudio.playScanBeep();
        }
        return prev + 2;
      });
    }, 45);

    return () => clearInterval(interval);
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-xl animate-fadeIn font-tech">
      <div className="relative w-full max-w-md rounded-2xl cyber-glass p-6 border border-cyan-500/50 shadow-[0_0_60px_rgba(6,182,212,0.3)]">
        <div className="cyber-corner-tl" />
        <div className="cyber-corner-tr" />
        <div className="cyber-corner-bl" />
        <div className="cyber-corner-br" />

        <button
          onClick={() => { cyberAudio.playClick(); onClose(); }}
          className="absolute top-4 right-4 p-1 rounded-lg text-slate-400 hover:text-cyan-300 hover:bg-cyan-500/10 border border-transparent hover:border-cyan-500/30 transition-all"
        >
          <X className="w-5 h-5" />
        </button>

        <div className="text-center mb-6">
          <div className="inline-flex p-3 rounded-2xl bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 mb-3 animate-pulse">
            <Scan className="w-8 h-8 text-cyan-300" />
          </div>
          <h3 className="text-xl font-cyber font-bold text-cyan-300">{lang === 'zh' ? '量子神经网络 · 人脸/基因特征校验' : 'Quantum Neural Biometric Verification'}</h3>
          <p className="text-xs text-slate-400 mt-1 font-mono">{lang === 'zh' ? '智能电网调度中心最高特权级免密快速通道' : 'Highest Privilege Quick Access Channel'}</p>
        </div>

        <div className="relative w-48 h-48 mx-auto my-4 rounded-2xl border-2 border-cyan-500/40 bg-slate-950/90 overflow-hidden flex items-center justify-center shadow-[inset_0_0_20px_rgba(6,182,212,0.3)]">
          {scanStep !== 'authenticated' && (
            <div className="absolute inset-x-0 h-1 bg-gradient-to-r from-transparent via-cyan-400 to-transparent shadow-[0_0_15px_#00f0ff] animate-cyber-scan" />
          )}
          <div className="absolute inset-0 bg-[radial-gradient(#06b6d4_1px,transparent_1px)] [background-size:12px_12px] opacity-30 pointer-events-none" />
          <div className="relative z-10 text-center">
            {scanStep === 'authenticated' ? (
              <div className="flex flex-col items-center animate-bounce">
                <CheckCircle2 className="w-16 h-16 text-emerald-400 drop-shadow-[0_0_15px_rgba(52,211,153,0.8)]" />
                <span className="text-xs text-emerald-300 font-bold font-cyber mt-2">{lang === 'zh' ? '身份认证匹配成功' : 'VERIFIED 100%'}</span>
              </div>
            ) : (
              <div className="relative flex flex-col items-center">
                <UserCheck className="w-16 h-16 text-cyan-400/80 animate-pulse" />
                <div className="absolute -inset-4 border border-dashed border-cyan-400/50 rounded-full animate-spin [animation-duration:8s]" />
              </div>
            )}
          </div>
        </div>

        <div className="space-y-3 font-mono">
          <div className="flex justify-between text-xs text-slate-300">
            <span className="flex items-center gap-1.5 text-cyan-300">
              <Cpu className="w-3.5 h-3.5 text-cyan-400 animate-spin" />
              {scanStep === 'scanning_face' && (lang === 'zh' ? '正在扫描人脸特征节点...' : 'Scanning facial landmark mesh...')}
              {scanStep === 'verifying_quantum' && (lang === 'zh' ? '正在解密电网调度量子令牌...' : 'Decrypting grid quantum token...')}
              {scanStep === 'authenticated' && (lang === 'zh' ? '授权完成！请使用账号登录' : 'Done! Use username login')}
            </span>
            <span className="text-cyan-400 font-bold">{progress}%</span>
          </div>
          <div className="w-full h-2 bg-slate-900 rounded-full overflow-hidden border border-cyan-500/30">
            <div className="h-full bg-gradient-to-r from-cyan-500 via-purple-500 to-emerald-400 transition-all duration-100 ease-out shadow-[0_0_10px_#06b6d4]" style={{ width: `${progress}%` }} />
          </div>
          {scanStep === 'authenticated' && (
            <div className="pt-2 text-center">
              <span className="inline-flex items-center gap-1 text-[11px] text-purple-300 bg-purple-950/50 px-3 py-1 rounded-full border border-purple-500/30">
                <Sparkles className="w-3 h-3 text-purple-400" />
                {lang === 'zh' ? '演示功能：请使用账号密匙登录系统' : 'Demo: Please use username/password login'}
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
