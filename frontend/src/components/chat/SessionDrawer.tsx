import { useEffect, useState } from 'react'
import type { SessionMeta } from '../../types/chat'
import Icon from '../ui/Icon'

/* 夜谈记录抽屉（B，DeepSeek 式）：新建夜谈 + 历史列表（标题/时间/消息数）+ 点击恢复 + hover 熄星（治理权 2026-08-18） */
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
  onDelete,
}: {
  open: boolean
  sessions: SessionMeta[]
  currentId: string
  onClose: () => void
  onNew: () => void
  onOpen: (sid: string) => void
  onDelete: (sid: string, title: string) => Promise<void>
}) {
  const [confirmSid, setConfirmSid] = useState<string | null>(null)

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
        aria-label="夜谈记录"
      >
        <div className="flex items-center justify-between px-4 h-12 border-b border-hairline shrink-0">
          <div className="flex items-center gap-2 text-[13px] text-ink">
            <Icon name="history" size={14} className="text-primary" />
            夜谈记录
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
              className="p-1.5 rounded-lg text-ink-dim hover:text-ink transition-colors duration-150"
              aria-label="关闭"
            >
              <Icon name="x" size={15} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-2 py-2">
          {sessions.length === 0 ? (
            <div className="text-[12px] text-ink-dim/80 text-center py-10 leading-relaxed">
              还没有历史夜谈——聊点什么，它会出现在这里。
            </div>
          ) : (
            sessions.map((s) => {
              const active = s.id === currentId
              return (
                <div
                  key={s.id}
                  className={`group relative w-full text-left px-3 py-2.5 rounded-lg mb-0.5 transition-colors duration-150 cursor-pointer ${
                    active ? 'bg-primary/10' : 'hover:bg-surface'
                  }`}
                  onClick={() => onOpen(s.id)}
                >
                  <div className="text-[13px] text-ink truncate pr-6">
                    {s.title || '新夜谈'}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-[11px] text-ink-dim">
                    <span>{fmtTime(s.created_at)}</span>
                    {s.msg_count > 0 && <span>· {s.msg_count} 条消息</span>}
                    {active && <span className="text-primary">· 当前</span>}
                  </div>
                  {/* hover 熄星（治理权：显式确认，防误删）——阻止冒泡避免误触发打开 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      setConfirmSid(s.id)
                    }}
                    className="absolute right-2 top-2 p-1 rounded-md text-ink-dim/70 opacity-0 group-hover:opacity-100 hover:text-error hover:bg-elevated transition-opacity duration-150"
                    aria-label={`熄星夜谈：${s.title || '新夜谈'}`}
                    title="熄星夜谈（归档后熄星）"
                  >
                    <Icon name="trash" size={13} />
                  </button>
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* 熄星确认（治理权=破坏性操作必须显式确认） */}
      {confirmSid && (
        <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center" onClick={() => setConfirmSid(null)}>
          <div
            className="max-w-[300px] rounded-xl bg-elevated border border-hairline p-4 animate-msg-in"
            onClick={(e) => e.stopPropagation()}
            role="alertdialog"
            aria-label="确认熄星夜谈"
          >
            <div className="text-[13px] text-ink mb-1">熄星这个夜谈？</div>
            <div className="text-[12px] text-ink-dim leading-relaxed mb-3">
              对话记录会先归档到本地（data/archive），然后从列表移除。此操作不可在界面上撤销。
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => setConfirmSid(null)}
                className="px-3 py-1.5 rounded-lg text-[12px] text-ink-muted hover:text-ink transition-colors"
              >
                取消
              </button>
              <button
                onClick={async () => {
                  const target = confirmSid
                  setConfirmSid(null)
                  if (target) await onDelete(target, '')
                }}
                className="px-3 py-1.5 rounded-lg text-[12px] bg-error/20 text-error hover:bg-error/30 transition-colors"
              >
                熄星
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
