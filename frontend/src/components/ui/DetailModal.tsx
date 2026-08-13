import { useEffect, type ReactNode } from 'react'
import Icon from '../ui/Icon'

/* 详情 modal（侧栏卡片点击弹窗）：遮罩/Esc/✕ 三出口 + 150ms 动画 + 14px 正文 + 内部滚动
   role=dialog + aria-modal（WCAG 顺手）；中等尺寸 max-w-520 / max-h-75vh */
interface DetailModalProps {
  title: string
  open: boolean
  onClose: () => void
  children: ReactNode
  footer?: ReactNode
}

export default function DetailModal({ title, open, onClose, children, footer }: DetailModalProps) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 遮罩：点击关闭 */}
      <div className="absolute inset-0 bg-black/50 animate-fade-in" onClick={onClose} aria-hidden="true" />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className="relative w-full max-w-[520px] max-h-[75vh] flex flex-col rounded-xl border border-hairline bg-elevated shadow-2xl animate-modal-pop"
      >
        <div className="flex items-center justify-between px-4 py-3 border-b border-hairline shrink-0">
          <h3 className="text-[14px] font-medium text-[rgba(236,233,225,0.9)]">{title}</h3>
          <button
            onClick={onClose}
            aria-label="关闭"
            className="p-1 rounded hover:bg-surface text-[rgba(236,233,225,0.5)] hover:text-[rgba(236,233,225,0.8)] transition-colors"
          >
            <Icon name="x" size={16} />
          </button>
        </div>
        <div className="flex-1 min-h-0 overflow-y-auto px-4 py-3 text-[14px] leading-relaxed text-[rgba(236,233,225,0.85)] whitespace-pre-wrap">
          {children}
        </div>
        {footer && (
          <div className="px-4 py-2.5 border-t border-hairline flex justify-end gap-2 shrink-0">{footer}</div>
        )}
      </div>
    </div>
  )
}
