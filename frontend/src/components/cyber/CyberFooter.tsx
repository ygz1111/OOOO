import { GraduationCap, Cpu, ShieldCheck, Terminal } from 'lucide-react';

interface CyberFooterProps {
  lang: 'zh' | 'en';
}

export function CyberFooter({ lang }: CyberFooterProps) {
  return (
    <footer className="relative z-30 w-full border-t border-cyan-500/20 bg-slate-950/90 backdrop-blur-md px-4 lg:px-8 py-4 text-slate-400 font-tech text-xs">
      <div className="max-w-7xl mx-auto flex flex-col md:flex-row items-center justify-between gap-4">
        <div className="flex flex-wrap items-center justify-center md:justify-start gap-3">
          <span className="flex items-center space-x-1.5 text-cyan-300 font-cyber font-bold">
            <GraduationCap className="w-4 h-4 text-cyan-400" />
            <span>{lang === 'zh' ? '智能电网负荷预测毕业设计系统' : 'Smart Grid Load Forecasting Thesis Project'}</span>
          </span>
          <span className="text-slate-700 hidden sm:inline">|</span>
          <span className="text-slate-400">
            {lang === 'zh' ? '指导教师：张教授 · 答辩组别：AI电气工程专场' : 'Advisor: Prof. Zhang · Group: AI Power Systems'}
          </span>
        </div>

        <div className="flex items-center space-x-4 font-mono text-[11px]">
          <span className="flex items-center space-x-1 text-purple-400 bg-purple-950/40 px-2 py-0.5 rounded border border-purple-500/30">
            <Cpu className="w-3 h-3" />
            <span>ST-GCN + Transformer</span>
          </span>
          <span className="flex items-center space-x-1 text-emerald-400 bg-emerald-950/40 px-2 py-0.5 rounded border border-emerald-500/30">
            <ShieldCheck className="w-3 h-3" />
            <span>PyTorch 2.4</span>
          </span>
          <span className="flex items-center space-x-1 text-cyan-400 bg-cyan-950/40 px-2 py-0.5 rounded border border-cyan-500/30">
            <Terminal className="w-3 h-3" />
            <span>v4.8 Cyber Core</span>
          </span>
        </div>
      </div>

      <div className="max-w-7xl mx-auto mt-2 pt-2 border-t border-slate-900 flex flex-col sm:flex-row items-center justify-between text-[11px] text-slate-500 font-mono">
        <div>
          © 2026 {lang === 'zh' ? '国家电网 / 毕业设计作品集 · 保留所有权利' : 'Smart Grid Research Lab · All Rights Reserved'}
        </div>
        <div className="flex items-center space-x-1 mt-1 sm:mt-0">
          <span>{lang === 'zh' ? '精心打造高级赛博朋克极致体验' : 'Designed with Cyberpunk Aesthetic'}</span>
        </div>
      </div>
    </footer>
  );
}
