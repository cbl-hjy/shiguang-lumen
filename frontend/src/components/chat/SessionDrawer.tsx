import { useEffect } from 'react'
import type { SessionMeta } from '../../types/chat'
import Icon from '../ui/Icon'

/* 会话历史抽屉（B，DeepSeek 式）：新建会话 + 历史列表（标题/时间/消息数）+ 点击恢复 */
function fmtTime(ts: string): string {
  const d = new Date(ts.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return ts
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  const yesterday = new Date(now.getTime() - 86400000)
  const isYesterday = d.toDateString() === yesterday.toDateString()
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (sameDay) return `今天 ${hm}`
  if (isYesterday) return `昨天 ${hm}`
  return `${d.getMonth() + 1}-${String(d.getDate()).padStart(2, '0')} ${hm}`
}

export default function SessionDrawer({
  open,
  sessions,
  currentId,
  onClose,
  onNew,
  onOpen,
}: {
  open: boolean
  sessions: SessionMeta[]
  currentId: string
  onClose: () => void
  onNew: () => void
  onOpen: (sid: string) => void
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null
  return (
    <div
      className="fixed inset-0 z-40 bg-black/50 flex items-start justify-end animate-toast-in"
      onClick={onClose}
    >
      <div
        className="w-[320px] h-full bg-elevated border-l border-hairline flex flex-col animate-msg-in"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="会话历史"
      >
        <div className="flex items-center justify-between px-4 h-12 border-b border-hairline shrink-0">
          <div className="flex items-center gap-2 text-[13px] text-[rgba(236,233,225,0.9)]">
            <Icon name="history" size={14} className="text-primary" />
            会话历史
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={onNew}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-primary/15 text-primary text-[12px] hover:bg-primary/25 transition-colors duration-150"
            >
              <Icon name="plus" size={13} />
              新建
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg text-[rgba(236,233,225,0.5)] hover:text-[rgba(236,233,225,0.9)] transition-colors duration-150"
              aria-label="关闭"
            >
              <Icon name="x" size={15} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {sessions.length === 0 ? (
            <div className="text-[12px] text-[rgba(236,233,225,0.35)] text-center py-10 leading-relaxed">
              还没有历史会话——聊点什么，它会出现在这里。
            </div>
          ) : (
            sessions.map((s) => {
              const active = s.id === currentId
              return (
                <button
                  key={s.id}
                  onClick={() => onOpen(s.id)}
                  className={`w-full text-left px-3 py-2.5 rounded-lg mb-0.5 transition-colors duration-150 group ${
                    active ? 'bg-primary/10' : 'hover:bg-surface'
                  }`}
                >
                  <div className="text-[13px] text-[rgba(236,233,225,0.9)] truncate">
                    {s.title || '新会话'}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[rgba(236,233,225,0.4)]">
                    <span>{fmtTime(s.created_at)}</span>
                    {s.msg_count > 0 && <span>· {s.msg_count} 条消息</span>}
                    {active && <span className="text-primary">· 当前</span>}
                  </div>
                </button>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
