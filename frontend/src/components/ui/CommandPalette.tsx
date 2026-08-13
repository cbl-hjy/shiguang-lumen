import { useEffect, useMemo, useRef, useState } from 'react'
import Icon, { type IconName } from './Icon'
import { useUiStore } from '../../store/uiStore'
import { useChatStore } from '../../store/chatStore'

/* Cmd+K 命令面板：模糊搜索动作 + 键盘导航（↑↓ 选择 / Enter 执行 / Esc 关闭）
   重度用户主导航（Linear/Cursor 范式）——学习搭子版：新对话/思考显隐/打开面板 */
interface Action {
  id: string
  label: string
  hint: string
  icon: IconName
  run: () => void
}

export default function CommandPalette({ onOpenPanel }: { onOpenPanel: (p: 'path' | 'memory') => void }) {
  const open = useUiStore((s) => s.commandOpen)
  const setOpen = useUiStore((s) => s.setCommandOpen)
  const showThinking = useUiStore((s) => s.showThinking)
  const toggleThinking = useUiStore((s) => s.toggleThinking)
  const clear = useChatStore((s) => s.clear)
  const [query, setQuery] = useState('')
  const [sel, setSel] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  const actions = useMemo<Action[]>(() => {
    const list: Action[] = [
      { id: 'clear', label: '新对话', hint: '清空当前会话', icon: 'arrow-right', run: () => { clear() } },
      {
        id: 'thinking',
        label: showThinking ? '隐藏思考过程' : '显示思考过程',
        hint: showThinking ? '当前：显示' : '当前：折叠',
        icon: 'brain',
        run: toggleThinking,
      },
      { id: 'path', label: '打开学习路径', hint: '查看目标与进度', icon: 'book', run: () => onOpenPanel('path') },
      { id: 'memory', label: '打开记忆面板', hint: '查看与修正记忆', icon: 'user', run: () => onOpenPanel('memory') },
    ]
    const q = query.trim().toLowerCase()
    if (!q) return list
    return list.filter((a) => a.label.toLowerCase().includes(q) || a.hint.toLowerCase().includes(q))
  }, [query, showThinking, clear, toggleThinking, onOpenPanel])

  useEffect(() => {
    if (open) {
      setQuery('')
      setSel(0)
      setTimeout(() => inputRef.current?.focus(), 30)
    }
  }, [open])

  useEffect(() => {
    setSel(0)
  }, [query])

  if (!open) return null

  const exec = (a: Action) => {
    a.run()
    setOpen(false)
  }

  /* 匹配高亮：把 label 中命中的片段用 teal "光照"标记（.lumen-mark） */
  const highlight = (text: string) => {
    const q = query.trim()
    if (!q) return text
    const idx = text.toLowerCase().indexOf(q.toLowerCase())
    if (idx < 0) return text
    return (
      <>
        {text.slice(0, idx)}
        <mark className="lumen-mark">{text.slice(idx, idx + q.length)}</mark>
        {text.slice(idx + q.length)}
      </>
    )
  }

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[18vh] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="命令面板"
      onClick={() => setOpen(false)}
    >
      <div
        className="w-full max-w-lg rounded-xl bg-elevated border border-hairline shadow-2xl animate-msg-in overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2 px-4 border-b border-hairline">
          <Icon name="search" size={15} className="text-[rgba(236,233,225,0.4)]" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Escape') setOpen(false)
              else if (e.key === 'ArrowDown') setSel((s) => Math.min(s + 1, actions.length - 1))
              else if (e.key === 'ArrowUp') setSel((s) => Math.max(s - 1, 0))
              else if (e.key === 'Enter' && actions[sel]) exec(actions[sel])
            }}
            placeholder="输入命令或搜索…"
            className="flex-1 h-11 bg-transparent outline-none text-[14px] placeholder:text-[rgba(236,233,225,0.35)]"
            aria-label="搜索命令"
          />
          <kbd className="text-[10px] text-[rgba(236,233,225,0.35)] border border-hairline rounded px-1.5 py-0.5">
            Esc
          </kbd>
        </div>
        <div className="py-1.5">
          {actions.length === 0 && (
            <div className="px-4 py-4 text-[12px] text-[rgba(236,233,225,0.4)]">没有匹配的命令</div>
          )}
          {actions.map((a, i) => (
            <button
              key={a.id}
              onMouseEnter={() => setSel(i)}
              onClick={() => exec(a)}
              className={`w-full flex items-center gap-3 px-4 py-2.5 text-left transition-colors duration-100 ${
                i === sel ? 'bg-primary/10' : ''
              }`}
            >
              <Icon name={a.icon} size={15} className="text-[rgba(236,233,225,0.55)]" />
              <span className="text-[13px] text-[rgba(236,233,225,0.9)] flex-1">{highlight(a.label)}</span>
              <span className="text-[11px] text-[rgba(236,233,225,0.35)]">{a.hint}</span>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
