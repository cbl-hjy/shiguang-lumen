import { useEffect, useState } from 'react'
import { useChatStore } from '../../store/chatStore'

const PIN_KEY = 'shiguang_pinned_sessions'

/* 历史记录栏（v3 聚合 2026-08-26：侧边栏只保留历史记录——可收起/展开、可删除、可置顶） */
export default function SessionRail() {
  const sessions = useChatStore((s) => s.sessions)
  const currentId = useChatStore((s) => s.sessionId)
  const newSession = useChatStore((s) => s.newSession)
  const openSession = useChatStore((s) => s.openSession)
  const deleteSession = useChatStore((s) => s.deleteSession)
  const [collapsed, setCollapsed] = useState(false)
  const [pinned, setPinned] = useState<string[]>(() => {
    try {
      return JSON.parse(localStorage.getItem(PIN_KEY) || '[]')
    } catch {
      return []
    }
  })

  useEffect(() => {
    try {
      localStorage.setItem(PIN_KEY, JSON.stringify(pinned))
    } catch {
      /* 忽略 */
    }
  }, [pinned])

  const togglePin = (id: string) => {
    setPinned((p) => (p.includes(id) ? p.filter((x) => x !== id) : [id, ...p]))
  }

  const remove = async (id: string) => {
    if (!window.confirm('删除这条夜谈？此操作不可撤销。')) return
    await deleteSession(id)
  }

  /* 置顶排前，其余按创建时间倒序 */
  const ordered = [...sessions].sort((a, b) => {
    const pa = pinned.includes(a.id) ? 1 : 0
    const pb = pinned.includes(b.id) ? 1 : 0
    if (pa !== pb) return pb - pa
    return String(b.created_at).localeCompare(String(a.created_at))
  })

  /* 单 aside 宽度过渡（收起/展开动画自然，2026-08-26 用户要求） */
  return (
    <aside
      className={`hidden md:flex shrink-0 h-full flex-col border-r border-hairline bg-surface/40 transition-[width] duration-300 ease-out overflow-hidden ${
        collapsed ? 'w-10 items-center' : 'w-[232px]'
      }`}
    >
      {collapsed ? (
        <div className="flex flex-col items-center py-2">
          <button
            onClick={() => setCollapsed(false)}
            className="w-8 h-8 rounded-lg flex items-center justify-center text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
            aria-label="展开历史记录"
            title="展开历史记录"
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
              <path
                d="M14 6l-6 6 6 6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <span className="mt-3 text-[9px] tracking-widest text-ink-dim [writing-mode:vertical-lr]">
            夜谈
          </span>
        </div>
      ) : (
        <>
          <div className="px-3.5 h-12 flex items-center justify-between border-b border-hairline shrink-0">
            <span className="text-[11px] tracking-[0.3em] text-ink-muted">夜谈记录</span>
            <div className="flex items-center gap-1">
              <button
                onClick={newSession}
                className="p-1.5 rounded-lg text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
                aria-label="新建夜谈"
                title="新建夜谈"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M12 5v14M5 12h14"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                  />
                </svg>
              </button>
              <button
                onClick={() => setCollapsed(true)}
                className="p-1.5 rounded-lg text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
                aria-label="收起历史记录"
                title="收起历史记录"
              >
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M10 6l6 6-6 6"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-0.5 animate-fade-in">
            {ordered.length === 0 && (
              <p className="px-2.5 py-2 text-[11px] text-ink-dim">还没有夜谈——说点什么开始</p>
            )}
            {ordered.map((s) => {
              const isPinned = pinned.includes(s.id)
              return (
                <div
                  key={s.id}
                  className={`group rounded-lg transition-colors duration-150 ${
                    s.id === currentId ? 'bg-elevated' : 'hover:bg-elevated/60'
                  }`}
                >
                  <button
                    onClick={() => openSession(s.id)}
                    className={`w-full text-left px-2.5 pt-2 pb-1 ${
                      s.id === currentId ? 'text-primary' : 'text-ink-muted group-hover:text-ink'
                    }`}
                  >
                    <span className="block text-[12px] truncate leading-snug">
                      {isPinned && <span className="text-amber mr-1">●</span>}
                      {s.title || '未命名夜谈'}
                    </span>
                    <span className="block text-[10px] text-ink-dim mt-0.5 font-mono">
                      {s.created_at?.slice(5, 16) || ''}
                    </span>
                  </button>
                  {/* hover 操作：置顶/删除 */}
                  <div className="hidden group-hover:flex items-center justify-end gap-0.5 px-1.5 pb-1">
                    <button
                      onClick={() => togglePin(s.id)}
                      className="p-1 rounded text-ink-dim hover:text-amber hover:bg-elevated transition-colors duration-150"
                      aria-label={isPinned ? '取消置顶' : '置顶'}
                      title={isPinned ? '取消置顶' : '置顶'}
                    >
                      <svg
                        width="11"
                        height="11"
                        viewBox="0 0 24 24"
                        fill={isPinned ? '#e6be78' : 'none'}
                      >
                        <path
                          d="M9 4h6v6l2 3v1H7v-1l2-3zM12 14v6"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                    <button
                      onClick={() => remove(s.id)}
                      className="p-1 rounded text-ink-dim hover:text-error hover:bg-elevated transition-colors duration-150"
                      aria-label="删除夜谈"
                      title="删除"
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path
                          d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </>
      )}
    </aside>
  )
}
