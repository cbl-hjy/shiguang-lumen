import { useState } from 'react'
import Icon from '../ui/Icon'
import { useUiStore } from '../../store/uiStore'

/* 思考过程折叠块：默认折叠，点击展开；Cmd+K 可全局切换显示/隐藏 */
export default function ThinkingBlock({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  const showThinking = useUiStore((s) => s.showThinking)
  if (!text || !showThinking) return null
  return (
    <div className="mb-2">
      <button
        onClick={() => setOpen((v) => !v)}
        className="text-[12px] text-[rgba(236,233,225,0.4)] hover:text-[rgba(236,233,225,0.7)] transition-colors duration-150 flex items-center gap-1"
        aria-expanded={open}
      >
        <Icon
          name="chevron-right"
          size={12}
          className={`transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        />
        {open ? '思考过程' : `思考过程（${text.length} 字，点击展开）`}
      </button>
      {open && (
        <div className="mt-1 pl-4 border-l border-hairline text-[12px] text-[rgba(236,233,225,0.45)] leading-relaxed whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  )
}
