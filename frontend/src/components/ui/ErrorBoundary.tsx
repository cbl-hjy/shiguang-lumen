import { Component, Fragment, type ErrorInfo, type ReactNode } from 'react'
import Icon from './Icon'

/* 渲染兜底（2026-08-29 白屏事故后补）：项目此前零 ErrorBoundary——
   任何一处 render 抛异常（典型：data.skills.length of undefined），React 18 会卸载整棵组件树，
   用户只看到 body 背景（"加载一会就只剩背景"），既无法反馈也无法自查。
   边界内出错 → 渲染一张错误卡 + 重试按钮，其余界面照常可用。
   用法：<ErrorBoundary label="成长轨迹"><EvolveFeature /></ErrorBoundary> */

interface ErrorBoundaryProps {
  children: ReactNode
  /** 出错区块名（如「成长轨迹」）——展示在错误卡上，用户报障/排查时一眼定位 */
  label?: string
  /** 卡片额外类名（默认独立成块；嵌入列表时可去掉外边距） */
  className?: string
}

interface ErrorBoundaryState {
  error: Error | null
  /** 递增即 remount 子树（重试：清错误态 + 强制子树重新挂载，数据重新拉取） */
  resetKey: number
}

export default class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null, resetKey: 0 }

  static getDerivedStateFromError(error: Error): Partial<ErrorBoundaryState> {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // 落 console 便于排查（保留完整堆栈 + 组件栈）
    console.error(
      `[ErrorBoundary]${this.props.label ? ` ${this.props.label}` : ''} 渲染异常：`,
      error,
      info.componentStack,
    )
  }

  /** 重试：重置错误态并 remount 子树（key 变化 → React 丢弃旧实例重建） */
  private handleRetry = (): void => {
    this.setState((s: ErrorBoundaryState) => ({ error: null, resetKey: s.resetKey + 1 }))
  }

  render(): ReactNode {
    const { error, resetKey } = this.state
    const { children, label, className = '' } = this.props

    // 无异常：包一层 Fragment（key 驱动 remount，不插入额外 DOM 节点，不影响布局）
    if (!error) {
      return <Fragment key={resetKey}>{children}</Fragment>
    }

    /* 错误卡：沿用项目设计 token（fCard 同款星空渐变 + hairline 描边 + ink 分级文字），
       深色主题，零新依赖——出错时用户看到的是"这块内容坏了"，而不是一片空白背景 */
    return (
      <div
        role="alert"
        className={`rounded-[14px] border border-error/30 bg-[linear-gradient(160deg,rgba(40,28,32,.9),rgba(22,18,22,.92))] px-4 py-3.5 ${className}`}
      >
        <div className="flex items-center gap-2 text-[13px] font-medium tracking-wider text-error">
          <Icon name="alert" size={14} className="shrink-0" />
          这块内容出了点问题
          {label && <span className="text-[11px] font-normal text-ink-dim">· {label}</span>}
        </div>
        <p className="mt-2 text-[11.5px] leading-relaxed text-ink-dim break-words">
          {error.message || String(error)}
        </p>
        <div className="mt-3 flex items-center gap-2">
          <button
            onClick={this.handleRetry}
            className="flex items-center gap-1.5 rounded-lg border border-hairline bg-elevated px-3 py-1.5 text-[12px] text-ink-muted transition-colors duration-150 hover:border-primary/40 hover:text-primary"
          >
            <Icon name="refresh" size={12} />
            重试
          </button>
          <span className="text-[11px] text-ink-dim/70">星图其他部分照常可用</span>
        </div>
      </div>
    )
  }
}
