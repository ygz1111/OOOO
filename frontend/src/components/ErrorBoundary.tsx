/**
 * 全局错误边界组件
 * 捕获子组件树中的 JavaScript 错误，展示降级 UI 并提供恢复操作
 */
import { Component, ErrorInfo, ReactNode } from 'react'
import { AlertTriangle, RefreshCw, Home } from 'lucide-react'

interface ErrorBoundaryProps {
  children: ReactNode
  /** 自定义降级 UI */
  fallback?: ReactNode
}

interface ErrorBoundaryState {
  hasError: boolean
  error: Error | null
}

class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props)
    this.state = { hasError: false, error: null }
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error }
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    // 控制台输出完整堆栈，便于调试
    console.error('[ErrorBoundary] 捕获到未处理错误:', error)
    console.error('[ErrorBoundary] 组件堆栈:', errorInfo.componentStack)
  }

  handleReset = (): void => {
    this.setState({ hasError: false, error: null })
  }

  handleGoHome = (): void => {
    this.setState({ hasError: false, error: null })
    window.location.href = '/'
  }

  render(): ReactNode {
    if (this.state.hasError) {
      // 如果提供了自定义降级 UI，则使用它
      if (this.props.fallback) {
        return this.props.fallback
      }

      // 默认降级 UI
      return (
        <div
          className="flex flex-col items-center justify-center min-h-[400px] p-8 text-center animate-fade-in"
          role="alert"
          aria-live="assertive"
        >
          <div className="relative mb-6">
            <div className="absolute inset-0 rounded-full bg-danger-500/10 blur-2xl" aria-hidden="true" />
            <AlertTriangle className="w-16 h-16 text-danger-400 relative z-10" aria-hidden="true" />
          </div>
          <h2 className="text-xl font-bold text-white mb-2">
            页面渲染出错
          </h2>
          <p className="text-sm text-dark-300 mb-1 max-w-md">
            组件在渲染过程中发生了异常，请尝试重新加载。
          </p>
          {this.state.error && (
            <p className="text-xs text-dark-500 mb-6 max-w-md font-mono truncate w-full">
              {this.state.error.message}
            </p>
          )}
          <div className="flex items-center gap-3">
            <button
              onClick={this.handleReset}
              className="btn btn-primary"
              aria-label="重新尝试渲染"
            >
              <RefreshCw className="w-4 h-4" aria-hidden="true" />
              重试
            </button>
            <button
              onClick={this.handleGoHome}
              className="btn btn-ghost"
              aria-label="返回首页"
            >
              <Home className="w-4 h-4" aria-hidden="true" />
              返回首页
            </button>
          </div>
        </div>
      )
    }

    return this.props.children
  }
}

export default ErrorBoundary
