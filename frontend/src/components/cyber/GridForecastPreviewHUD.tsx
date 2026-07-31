import { useState, useEffect } from 'react';
import { Activity, TrendingUp, Cpu, Thermometer, Layers, Radio, RefreshCw } from 'lucide-react';
import { cyberAudio } from '../../utils/audio';

interface GridForecastPreviewHUDProps {
  lang: 'zh' | 'en';
}

export function GridForecastPreviewHUD({ lang }: GridForecastPreviewHUDProps) {
  const [activeTab, setActiveTab] = useState<'curve' | 'heatmap' | 'model'>('curve');
  const [temp, setTemp] = useState<number>(28);
  const [humidity, setHumidity] = useState<number>(65);
  const [isSimulating, setIsSimulating] = useState<boolean>(false);

  const generateCurvePoints = (temperature: number) => {
    const points = [];
    const basePeak = 380 + (temperature - 20) * 8.5;
    for (let hour = 0; hour < 24; hour++) {
      let load = 220;
      if (hour >= 7 && hour <= 12) {
        load = basePeak * (0.7 + (hour - 7) * 0.06);
      } else if (hour >= 13 && hour <= 18) {
        load = basePeak * (0.95 + Math.sin(hour) * 0.05);
      } else if (hour >= 19 && hour <= 22) {
        load = basePeak * 0.88;
      } else {
        load = 210 + Math.sin(hour) * 15;
      }
      const actual = load + (Math.random() - 0.5) * 12;
      const forecast = load;
      points.push({ hour: `${hour.toString().padStart(2, '0')}:00`, actual, forecast });
    }
    return points;
  };

  const [dataPoints, setDataPoints] = useState(generateCurvePoints(28));

  useEffect(() => {
    setDataPoints(generateCurvePoints(temp));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [temp]);

  const triggerSimulation = () => {
    cyberAudio.playScanBeep();
    setIsSimulating(true);
    setTimeout(() => {
      setDataPoints(generateCurvePoints(temp + (Math.random() * 2 - 1)));
      setIsSimulating(false);
    }, 600);
  };

  const peakLoad = Math.max(...dataPoints.map((p) => p.forecast)).toFixed(1);
  const currentLoad = dataPoints[14].forecast.toFixed(1);

  return (
    <div className="relative w-full rounded-2xl cyber-glass p-5 lg:p-6 shadow-[0_0_50px_rgba(6,182,212,0.15)] border border-cyan-500/30 overflow-hidden font-tech text-slate-100">
      <div className="absolute inset-0 opacity-10 bg-[url('/images/grid-forecast-hub.jpg')] bg-cover bg-center pointer-events-none" />

      <div className="cyber-corner-tl" />
      <div className="cyber-corner-tr" />
      <div className="cyber-corner-bl" />
      <div className="cyber-corner-br" />

      <div className="relative z-10 flex flex-wrap items-center justify-between gap-3 pb-4 border-b border-cyan-500/20">
        <div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse shadow-[0_0_8px_#06b6d4]"></span>
            <h3 className="text-lg lg:text-xl font-bold font-cyber text-cyan-300 tracking-wider flex items-center gap-2">
              <Activity className="w-5 h-5 text-cyan-400" />
              {lang === 'zh' ? '智能电网负荷实时预测中心' : 'Smart Grid Load Forecast Console'}
            </h3>
          </div>
          <p className="text-xs text-cyan-400/70 mt-0.5">
            {lang === 'zh'
              ? '演示界面 · 数据为模拟生成 · 正式预测以主系统实时 API 为准'
              : 'Demo UI · Simulated data · Real forecasts served by main system API'}
          </p>
        </div>

        <div className="flex items-center space-x-1 bg-slate-900/90 p-1 rounded-lg border border-cyan-500/30 text-xs">
          <button
            onClick={() => { cyberAudio.playClick(); setActiveTab('curve'); }}
            className={`px-3 py-1.5 rounded-md font-semibold transition-all flex items-center space-x-1 ${
              activeTab === 'curve'
                ? 'bg-gradient-to-r from-cyan-500 to-blue-600 text-slate-950 shadow-[0_0_12px_rgba(6,182,212,0.5)] font-cyber'
                : 'text-slate-400 hover:text-cyan-300'
            }`}
          >
            <TrendingUp className="w-3.5 h-3.5" />
            <span>{lang === 'zh' ? '负荷曲线' : 'Load Curve'}</span>
          </button>
          <button
            onClick={() => { cyberAudio.playClick(); setActiveTab('heatmap'); }}
            className={`px-3 py-1.5 rounded-md font-semibold transition-all flex items-center space-x-1 ${
              activeTab === 'heatmap'
                ? 'bg-gradient-to-r from-purple-500 to-indigo-600 text-white shadow-[0_0_12px_rgba(168,85,247,0.5)] font-cyber'
                : 'text-slate-400 hover:text-purple-300'
            }`}
          >
            <Layers className="w-3.5 h-3.5" />
            <span>{lang === 'zh' ? '母线拓扑' : 'Busbar Map'}</span>
          </button>
          <button
            onClick={() => { cyberAudio.playClick(); setActiveTab('model'); }}
            className={`px-3 py-1.5 rounded-md font-semibold transition-all flex items-center space-x-1 ${
              activeTab === 'model'
                ? 'bg-gradient-to-r from-amber-500 to-orange-600 text-slate-950 shadow-[0_0_12px_rgba(245,158,11,0.5)] font-cyber'
                : 'text-slate-400 hover:text-amber-300'
            }`}
          >
            <Cpu className="w-3.5 h-3.5" />
            <span>{lang === 'zh' ? '算法指标' : 'AI Metrics'}</span>
          </button>
        </div>
      </div>

      <div className="relative z-10 my-4">
        {activeTab === 'curve' && (
          <div className="space-y-4">
            <div className="relative bg-slate-950/80 border border-cyan-500/20 rounded-xl p-4 shadow-inner">
              <div className="flex items-center justify-between text-xs text-slate-400 mb-2 font-mono">
                <div className="flex items-center space-x-4">
                  <span className="flex items-center space-x-1.5 text-cyan-400">
                    <span className="w-2.5 h-0.5 bg-cyan-400 inline-block"></span>
                    <span>{lang === 'zh' ? '预测负荷 (MW)' : 'Forecasted (MW)'}</span>
                  </span>
                  <span className="flex items-center space-x-1.5 text-purple-400">
                    <span className="w-2.5 h-0.5 bg-purple-400 inline-block border-t border-dashed"></span>
                    <span>{lang === 'zh' ? '模拟采样 (MW, 演示)' : 'Simulated (MW, demo)'}</span>
                  </span>
                </div>
                <div className="text-emerald-400 font-semibold flex items-center gap-1">
                  <Radio className="w-3 h-3 animate-pulse" />
                  <span>{lang === 'zh' ? '演示数据' : 'DEMO DATA'}</span>
                </div>
              </div>

              <div className="h-44 w-full relative">
                <svg className="w-full h-full overflow-visible" viewBox="0 0 500 150">
                  <defs>
                    <linearGradient id="cyanGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#06b6d4" stopOpacity="0.4" />
                      <stop offset="100%" stopColor="#06b6d4" stopOpacity="0.0" />
                    </linearGradient>
                    <linearGradient id="lineGlow" x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor="#38bdf8" />
                      <stop offset="50%" stopColor="#a855f7" />
                      <stop offset="100%" stopColor="#06b6d4" />
                    </linearGradient>
                  </defs>

                  {[30, 70, 110].map((yVal, idx) => (
                    <line key={idx} x1="0" y1={yVal} x2="500" y2={yVal} stroke="rgba(255,255,255,0.06)" strokeDasharray="4 4" />
                  ))}

                  <polygon
                    points={`0,140 ${dataPoints.map((d, i) => `${(i / 23) * 500},${140 - (d.forecast / 500) * 110}`).join(' ')} 500,140`}
                    fill="url(#cyanGradient)"
                  />
                  <polyline
                    fill="none" stroke="url(#lineGlow)" strokeWidth="2.5"
                    points={dataPoints.map((d, i) => `${(i / 23) * 500},${140 - (d.forecast / 500) * 110}`).join(' ')}
                  />
                  <polyline
                    fill="none" stroke="#a855f7" strokeWidth="1.5" strokeDasharray="3 3" opacity="0.8"
                    points={dataPoints.map((d, i) => `${(i / 23) * 500},${140 - (d.actual / 500) * 110}`).join(' ')}
                  />

                  {dataPoints.length > 0 && (
                    <g transform={`translate(280, ${140 - (dataPoints[13].forecast / 500) * 110})`}>
                      <circle r="5" fill="#00f0ff" className="animate-ping opacity-75" />
                      <circle r="4" fill="#00f0ff" />
                      <text x="8" y="-5" fill="#00f0ff" fontSize="10" fontFamily="Orbitron" fontWeight="bold">{currentLoad} MW</text>
                    </g>
                  )}
                </svg>
              </div>

              <div className="flex justify-between text-[10px] text-slate-500 font-mono mt-1">
                <span>00:00</span><span>04:00</span><span>08:00</span><span>12:00</span><span>16:00</span><span>20:00</span><span>23:00</span>
              </div>
            </div>

            <div className="bg-slate-900/80 border border-slate-800 rounded-xl p-3.5 space-y-2">
              <div className="flex items-center justify-between text-xs font-semibold text-slate-300">
                <span className="flex items-center space-x-1.5 text-cyan-300">
                  <Thermometer className="w-4 h-4 text-amber-400" />
                  <span>{lang === 'zh' ? '气象因数实时演化模拟' : 'Meteorological Factor Simulation'}</span>
                </span>
                <button
                  onClick={triggerSimulation} disabled={isSimulating}
                  className="px-2 py-0.5 rounded bg-cyan-500/20 hover:bg-cyan-500/30 text-cyan-300 border border-cyan-500/40 text-[11px] flex items-center space-x-1 transition-all"
                >
                  <RefreshCw className={`w-3 h-3 ${isSimulating ? 'animate-spin' : ''}`} />
                  <span>{lang === 'zh' ? '重算负荷' : 'Recalculate'}</span>
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
                <div>
                  <div className="flex justify-between text-slate-400 mb-1">
                    <span>{lang === 'zh' ? '预报气温' : 'Forecast Temp'}:</span>
                    <span className="text-amber-400 font-mono font-bold">{temp}°C</span>
                  </div>
                  <input type="range" min="10" max="40" value={temp} onChange={(e) => setTemp(Number(e.target.value))} className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-amber-400" />
                </div>
                <div>
                  <div className="flex justify-between text-slate-400 mb-1">
                    <span>{lang === 'zh' ? '相对湿度' : 'Humidity'}:</span>
                    <span className="text-cyan-400 font-mono font-bold">{humidity}%</span>
                  </div>
                  <input type="range" min="20" max="95" value={humidity} onChange={(e) => setHumidity(Number(e.target.value))} className="w-full h-1.5 bg-slate-800 rounded-lg appearance-none cursor-pointer accent-cyan-400" />
                </div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'heatmap' && (
          <div className="bg-slate-950/80 border border-purple-500/20 rounded-xl p-4 text-center space-y-3">
            <p className="text-xs text-purple-300 font-mono">{lang === 'zh' ? '区域128个变电站母线负荷热力分布 map' : '128 Regional Busbar Substation Load Map'}</p>
            <div className="grid grid-cols-8 gap-1.5 py-2">
              {Array.from({ length: 32 }).map((_, i) => {
                const loadFactor = Math.sin(i * 0.7) * 0.5 + 0.5;
                const color = loadFactor > 0.8 ? 'bg-rose-500 shadow-[0_0_8px_#f43f5e]' : loadFactor > 0.5 ? 'bg-amber-500 shadow-[0_0_8px_#f59e0b]' : 'bg-cyan-500 shadow-[0_0_8px_#06b6d4]';
                return (
                  <div key={i} className={`h-8 rounded flex items-center justify-center font-mono text-[10px] text-slate-950 font-bold transition-all hover:scale-110 cursor-pointer ${color}`} title={`Substation Node #${i + 1}: ${(loadFactor * 100).toFixed(0)}% Load`}>B{i + 1}</div>
                );
              })}
            </div>
            <div className="flex justify-center space-x-4 text-[11px] text-slate-400">
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-cyan-500"></span> {lang === 'zh' ? '正常 (30-60%)' : 'Normal'}</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-amber-500"></span> {lang === 'zh' ? '高峰 (60-85%)' : 'High Peak'}</span>
              <span className="flex items-center gap-1"><span className="w-2.5 h-2.5 rounded bg-rose-500"></span> {lang === 'zh' ? '预警 (>85%)' : 'Alert Zone'}</span>
            </div>
          </div>
        )}

        {activeTab === 'model' && (
          <div className="bg-slate-950/80 border border-amber-500/20 rounded-xl p-4 space-y-3 font-mono text-xs">
            <div className="grid grid-cols-2 gap-3">
              <div className="p-2.5 rounded bg-slate-900/90 border border-amber-500/30">
                <span className="text-slate-400 block text-[10px]">{lang === 'zh' ? '神经网络架构' : 'Model Architecture'}</span>
                <span className="text-amber-300 font-bold text-sm">LSTM / BiGRU / TCN / Transformer 集成</span>
              </div>
              <div className="p-2.5 rounded bg-slate-900/90 border border-cyan-500/30">
                <span className="text-slate-400 block text-[10px]">{lang === 'zh' ? '平均绝对误差 MAE' : 'MAE Loss'}</span>
                <span className="text-cyan-300 font-bold text-sm">-- (演示)</span>
              </div>
              <div className="p-2.5 rounded bg-slate-900/90 border border-emerald-500/30">
                <span className="text-slate-400 block text-[10px]">{lang === 'zh' ? '拟合优度 R² Score' : 'R² Score'}</span>
                <span className="text-emerald-300 font-bold text-sm">-- (演示)</span>
              </div>
              <div className="p-2.5 rounded bg-slate-900/90 border border-purple-500/30">
                <span className="text-slate-400 block text-[10px]">{lang === 'zh' ? '训练耗时 (GPU)' : 'Training Epoch Time'}</span>
                <span className="text-purple-300 font-bold text-sm">2.4ms / batch</span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="relative z-10 grid grid-cols-2 sm:grid-cols-4 gap-2.5 pt-3 border-t border-cyan-500/20 text-xs">
        <div className="bg-slate-900/70 p-2.5 rounded-lg border border-cyan-500/20">
          <div className="text-slate-400 text-[10px] uppercase font-mono">{lang === 'zh' ? '当前区域总负荷' : 'Total Load'}</div>
          <div className="text-base font-bold font-cyber text-cyan-300">{currentLoad} <span className="text-xs text-cyan-500">MW</span></div>
        </div>
        <div className="bg-slate-900/70 p-2.5 rounded-lg border border-purple-500/20">
          <div className="text-slate-400 text-[10px] uppercase font-mono">{lang === 'zh' ? '预测峰值负荷' : 'Peak Forecast'}</div>
          <div className="text-base font-bold font-cyber text-purple-300">{peakLoad} <span className="text-xs text-purple-500">MW</span></div>
        </div>
        <div className="bg-slate-900/70 p-2.5 rounded-lg border border-amber-500/20">
          <div className="text-slate-400 text-[10px] uppercase font-mono">{lang === 'zh' ? '电网电压稳定度' : 'Voltage Index'}</div>
          <div className="text-base font-bold font-cyber text-amber-300">--</div>
        </div>
        <div className="bg-slate-900/70 p-2.5 rounded-lg border border-emerald-500/20">
          <div className="text-slate-400 text-[10px] uppercase font-mono">{lang === 'zh' ? '数据来源' : 'Data Source'}</div>
          <div className="text-base font-bold font-cyber text-emerald-300 flex items-center gap-1">
            <span>{lang === 'zh' ? '模拟生成' : 'Simulated'}</span>
            <span className="text-[10px] bg-emerald-500/20 text-emerald-300 px-1 rounded">DEMO</span>
          </div>
        </div>
      </div>
    </div>
  );
}
