# 智能电网负荷预测系统 - 前端

## 🚀 项目概述

这是一个基于 React + TypeScript 的智能电网负荷预测系统前端，提供实时监控、数据可视化和预测结果展示功能。

## 📋 功能特性

### 核心页面
- **总览仪表板** - 系统关键指标实时监控
- **负荷预测** - 24小时负荷预测趋势图和详细数据
- **气象监控** - 新英格兰地区6个站点实时气象数据
- **光伏发电** - 光伏发电量估算和效率分析
- **系统状态** - 模型服务运行状态监控
- **历史分析** - 历史数据对比和趋势分析(开发中)

### 技术特性
- **响应式设计** - 支持桌面端和移动端
- **实时数据** - 与后端API实时同步
- **数据可视化** - 使用 Recharts 构建专业图表
- **双模式工作台** - 顶栏可切换正式工作台与深色监控，自动记住外观；图表、表格和气象地图随主题切换，保留数据质量与异常提示
- **组件化** - 高度模块化的组件设计

## 🛠️ 技术栈

- **前端框架**: React 18 + TypeScript
- **构建工具**: Vite
- **样式框架**: Tailwind CSS 与项目统一样式
- **图表库**: Recharts
- **HTTP客户端**: Axios
- **路由**: React Router
- **状态管理**: React Context
- **图标**: Lucide React

## 📦 项目结构

```
src/
├── components/          # 可复用组件
│   ├── MetricCard.tsx         # 指标卡片组件
│   ├── LoadForecastChart.tsx  # 负荷预测图表
│   ├── WeatherCard.tsx        # 气象数据卡片
│   ├── Header.tsx             # 顶部导航
│   └── Sidebar.tsx            # 侧边栏导航
├── pages/              # 页面组件
│   ├── Dashboard.tsx          # 总览仪表板
│   ├── LoadForecast.tsx       # 负荷预测页面
│   ├── WeatherMonitor.tsx     # 气象监控页面
│   ├── SolarGeneration.tsx    # 光伏发电页面
│   ├── SystemStatus.tsx       # 系统状态页面
│   └── HistoricalAnalysis.tsx # 历史分析页面
├── services/           # API服务
│   └── api.ts                # 后端API封装
├── contexts/           # React Context
│   └── ApiContext.tsx        # API状态管理
├── types/              # TypeScript类型定义
│   └── index.ts              # 数据接口定义
├── utils/              # 工具函数
│   └── formatters.ts         # 数据格式化工具
├── App.tsx             # 应用入口
└── main.tsx            # 渲染入口
```

## 🚀 快速开始

### 环境要求
- Node.js >= 16
- npm >= 8

### 安装依赖
```bash
cd OOOOOO
npm install
```

### 开发运行
```bash
npm run dev
```

### 生产构建
```bash
npm run build
```

### 预览构建结果
```bash
npm run preview
```

## 🌐 API集成

### 开发环境配置
- **API基础地址**: `http://localhost:8000`
- **WebSocket地址**: `ws://localhost:8000` (未来功能)

### 主要API端点
- `GET /api/weather/current` - 获取当前气象数据
- `POST /api/prediction/load` - 执行负荷预测
- `GET /api/system/status` - 获取系统状态
- `POST /api/prediction/batch` - 批量预测

### CORS配置
前端已配置代理，开发环境无需担心跨域问题。

## 📊 数据模型

### 负荷预测响应
```typescript
interface LoadPredictionResponse {
  status: string
  predictions: HourlyPrediction[]  // 24小时预测数据
  model_info: ModelInfo[]          // 模型信息
  ensemble_weights: Record<string, number> // 模型权重
  inference_time_ms: number        // 推理时间
  data_source: string             // 数据来源
  timestamp: string              // 时间戳
}
```

### 气象数据响应
```typescript
interface WeatherResponse {
  status: string
  stations: WeatherStationData[]    // 站点数据
  regional_average: Partial<WeatherData> // 区域平均
  timestamp: string
}
```

### 系统状态
```typescript
interface SystemStatus {
  status: 'healthy' | 'degraded' | 'error'
  models_loaded: number
  device: string
  total_inferences: number
  average_inference_time_ms: number
  uptime_seconds: number
  memory_usage_mb?: number
}
```

## 🎨 设计规范

### 颜色规范
- **主色调**: #0ea5e9 (蓝色)
- **成功色**: #22c55e (绿色) 
- **警告色**: #f59e0b (橙色)
- **危险色**: #ef4444 (红色)
- **背景色**: #0f172a (深蓝)
- **卡片色**: #1e293b (深灰)

### 字体规范
- **主要字体**: Inter, system-ui
- **代码字体**: Fira Code, Monaco
- **基础字号**: 14px
- **行高**: 1.5

### 组件规范
- **卡片边框**: 1px solid #334155
- **圆角**: 8px-12px
- **阴影**: 专业电网监控风格
- **动画**: 150-300ms 过渡效果

## 🔧 配置选项

### Tailwind配置
位于 `tailwind.config.js`，包含：
- 自定义颜色主题
- 字体配置
- 响应式断点
- 深色模式支持

### Vite配置 
位于 `vite.config.ts`，包含：
- API代理配置
- 构建优化设置
- 开发服务器配置

### TypeScript配置
位于 `tsconfig.json`，支持：
- 路径别名
- 严格的类型检查
- React 18特性支持

## 📈 性能指标

- **首屏加载**: < 3s
- **API响应时间**: < 100ms
- **图表刷新频率**: 30s
- **内存占用**: < 50MB
- **构建大小**: < 500KB (gzipped)

## 🔄 数据更新策略

1. **自动刷新**: 每30秒自动获取最新数据
2. **手动刷新**: 用户可点击刷新按钮立即更新
3. **错误重试**: API错误时自动重试3次
4. **离线模式**: API不可用时显示缓存数据

## 🧪 测试指南

### 组件测试
```bash
npm run test
```

### E2E测试
```bash
npm run test:e2e
```

### 所有API接口都在 `realtime_api/` 目录下有对应的测试文件
- `test_app.py` - FastAPI应用测试
- `test_openmeteo_client.py` - 气象API客户端测试
- 以及其他模块的单元测试

## 🚀 部署说明

### Docker部署
```bash
# 构建前端Docker镜像
docker build -t smartgrid-frontend .

# 运行容器
docker run -p 3000:3000 smartgrid-frontend
```

### Nginx配置示例
```nginx
server {
    listen 80;
    server_name smartgrid.example.com;
    
    location / {
        root /usr/share/nginx/html;
        index index.html index.htm;
        try_files $uri $uri/ /index.html;
    }
    
    location /api {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

## 🔒 安全考虑

1. **API认证**: 未来集成JWT认证
2. **数据验证**: 前端和后端双重输入验证
3. **HTTPS**: 生产环境必须使用HTTPS
4. **CORS**: 严格限制跨域访问
5. **错误处理**: 优雅处理API错误，不暴露敏感信息

## 📞 故障排查

### 常见问题
1. **API连接失败** - 检查后端服务是否启动
2. **图表不显示** - 检查数据格式是否正确
3. **样式问题** - 清除浏览器缓存
4. **TypeScript错误** - 运行 `npm run type-check`

### 开发调试
- 浏览器开发者工具查看网络请求
- 启用React Developer Tools
- 查看浏览器控制台错误信息
- 检查API响应数据格式

## 🚧 待开发功能

1. **实时WebSocket** - 实时数据推送
2. **用户认证** - JWT登录系统
3. **数据导出** - Excel/PDF报告导出
4. **移动端APP** - React Native版本
5. **更多图表** - 热图、散点图等

## 📄 许可证

MIT License - 详见 LICENSE 文件

## 🆘 支持与反馈

如有问题或建议，please create an issue in the project repository.
