import { useState, useEffect } from 'react';
import { Volume2, VolumeX, ShieldCheck, Zap, Globe, Radio } from 'lucide-react';
import { cyberAudio } from '../../utils/audio';

interface CyberHeaderProps {
  lang: 'zh' | 'en';
  setLang: (lang: 'zh' | 'en') => void;
}

export function CyberHeader({ lang, setLang }: CyberHeaderProps) {
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [timeStr, setTimeStr] = useState('');
  const [latency] = useState((1.2 + Math.random() * 0.8).toFixed(1));

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toLocaleTimeString('zh-CN', { hour12: false }) + ' CST');
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const toggleSound = () => {
    const next = !soundEnabled;
    setSoundEnabled(next);
    cyberAudio.enabled = next;
    if (next) cyberAudio.playClick();
  };

  return (
    <header className="relative z-30 w-full border-b border-cyan-500/20 bg-slate-950/80 backdrop-blur-md px-4 lg:px-8 py-3 flex items-center justify-between text-xs font-tech">
      <div className="flex items-center space-x-4">
        <div className="flex items-center space-x-2 text-cyan-400 font-bold tracking-wider">
          <div className="p-1.5 rounded bg-cyan-500/10 border border-cyan-500/30 text-cyan-400 animate-pulse">
            <Zap className="w-4 h-4 text-cyan-400" />
          </div>
          <span className="text-sm font-cyber uppercase tracking-widest text-cyan-300">
            SG-LFP // Cyber-Grid
          </span>
        </div>

        <div className="hidden sm:flex items-center space-x-3 text-slate-400 border-l border-slate-800 pl-4">
          <span className="flex items-center space-x-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping"></span>
            <span className="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span className="text-emerald-400 font-mono">
              {lang === 'zh' ? 'AI神经网络模型：已加载 (ST-GCN)' : 'AI Model: Loaded (ST-GCN)'}
            </span>
          </span>
          <span className="text-slate-600">|</span>
          <span className="text-slate-400 font-mono">Ping: {latency}ms</span>
        </div>
      </div>

      <div className="flex items-center space-x-3 sm:space-x-4">
        <div className="hidden md:flex items-center space-x-1.5 px-2.5 py-1 rounded bg-slate-900/80 border border-cyan-500/20 text-cyan-300 font-mono">
          <Radio className="w-3.5 h-3.5 text-cyan-400 animate-pulse" />
          <span>{timeStr}</span>
        </div>

        <div className="hidden lg:flex items-center space-x-1.5 px-2.5 py-1 rounded bg-purple-950/40 border border-purple-500/30 text-purple-300">
          <ShieldCheck className="w-3.5 h-3.5 text-purple-400" />
          <span className="tracking-wide">{lang === 'zh' ? '毕业设计机密考核级' : 'Level-4 Defense Clearance'}</span>
        </div>

        <button
          onClick={toggleSound}
          onMouseEnter={() => cyberAudio.playHover()}
          className={`flex items-center space-x-1 px-2.5 py-1 rounded border transition-all duration-200 ${
            soundEnabled
              ? 'bg-cyan-950/50 border-cyan-500/50 text-cyan-300 shadow-[0_0_10px_rgba(6,182,212,0.2)]'
              : 'bg-slate-900 border-slate-700 text-slate-500'
          }`}
          title={lang === 'zh' ? '网络音效开关' : 'Toggle Cyber Audio'}
        >
          {soundEnabled ? <Volume2 className="w-3.5 h-3.5 text-cyan-400" /> : <VolumeX className="w-3.5 h-3.5" />}
          <span className="hidden sm:inline font-mono uppercase">{soundEnabled ? 'SFX ON' : 'SFX OFF'}</span>
        </button>

        <button
          onClick={() => {
            cyberAudio.playClick();
            setLang(lang === 'zh' ? 'en' : 'zh');
          }}
          onMouseEnter={() => cyberAudio.playHover()}
          className="flex items-center space-x-1 px-2.5 py-1 rounded bg-slate-900 border border-slate-700 hover:border-cyan-500/50 text-slate-300 hover:text-cyan-300 transition-all font-mono"
        >
          <Globe className="w-3.5 h-3.5 text-cyan-400" />
          <span>{lang === 'zh' ? 'EN' : '中文'}</span>
        </button>
      </div>
    </header>
  );
}
