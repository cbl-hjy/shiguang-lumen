import { useRef, useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'
import ActivityMeter from './ActivityMeter'

/* 输入区：多行自适应输入（Enter 传光 / Shift+Enter 换行）+ 拾入（图片/PDF/文档）+ 会议（星宿多视角研讨）+ 传光 */
export default function InputBar({ onOpenDebate, sagesPending }: { onOpenDebate?: () => void; sagesPending?: number }) {
  const [text, setText] = useState('')
  const [pending, setPending] = useState<{ name: string; b64: string } | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const streaming = useChatStore((s) => s.streaming)
  const send = useChatStore((s) => s.send)

  const canSend = (text.trim() || pending) && !streaming

  /* 自适应高度：1 行 → 最多 6 行，超出滚动 */
  const resize = () => {
    const el = textRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 6 * 24 + 20)}px`
  }

  const handleSend = async () => {
    if (!canSend) return
    await send(text.trim() || '(请看一下我拾入的文件)', pending ?? undefined)
    setText('')
    setPending(null)
    if (fileRef.current) fileRef.current.value = ''
    if (textRef.current) {
      textRef.current.style.height = 'auto'
      textRef.current.focus()
    }
  }

  const handleFile = (f: File) => {
    const reader = new FileReader()
    reader.onload = () => setPending({ name: f.name, b64: String(reader.result) })
    reader.readAsDataURL(f)
  }

  return (
    <div className="p-4 border-t border-hairline">
      <ActivityMeter />
      {pending && (
        <div className="mb-2 text-[12px] text-primary/90 flex items-center gap-2">
          <Icon name="paperclip" size={13} />
          <span>{pending.name}</span>
          <button
            onClick={() => setPending(null)}
            className="text-ink-dim hover:text-ink/85 transition-colors duration-150"
            aria-label="移除附件"
          >
            <Icon name="x" size={13} />
          </button>
        </div>
      )}
      <div className="flex items-end gap-3">
        <input
          ref={fileRef}
          type="file"
          accept="image/*,.pdf,.docx,.pptx,.xlsx,.txt,.md"
          className="hidden"
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
          id="lumen-file"
        />
        <button
          onClick={() => fileRef.current?.click()}
          className="w-10 h-10 shrink-0 rounded-lg border border-hairline bg-surface flex items-center justify-center hover:bg-elevated active:scale-95 transition-all duration-150"
          aria-label="拾入图片或文档"
          title="拾入图片/文档"
        >
          <Icon name="paperclip" size={17} className="text-ink-muted" />
        </button>
        <button
          onClick={onOpenDebate}
          className="relative w-10 h-10 shrink-0 rounded-lg border border-hairline bg-surface flex items-center justify-center hover:bg-elevated active:scale-95 transition-all duration-150"
          aria-label="问星（多视角研讨）"
          title="问星：多位星宿围绕你的问题展开研讨"
        >
          <Icon name="users" size={17} className="text-primary/70" />
          {/* 入口状态信号（2026-08-20 B）：待审卡一眼可见——9px 太小提级 10px，amber 硬编码收编 */}
          {(sagesPending ?? 0) > 0 && (
            <span className="absolute -top-1 -right-1 px-1.5 py-0.5 rounded-md text-[10px] leading-none bg-amber text-[#1a1a1e] font-medium">
              {sagesPending}
            </span>
          )}
        </button>
        <button
          onClick={() => window.open('/obs', '_blank')}
          className="w-10 h-10 shrink-0 rounded-lg border border-hairline bg-surface flex items-center justify-center hover:bg-elevated active:scale-95 transition-all duration-150"
          aria-label="星图（观测台）"
          title="星图：系统观测台（token/工具/错误/延迟）"
        >
          <span className="text-[15px] leading-none" style={{ color: '#D9A441' }}>✦</span>
        </button>
        <textarea
          ref={textRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            resize()
          }}
          onKeyDown={(e) => {
            /* Enter 传光（IME 组合中不触发）；Shift+Enter 换行 */
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="输入你想学的 / 想问的…（Enter 传光，Shift+Enter 换行）"
          rows={1}
          aria-label="输入消息"
          className="flex-1 min-h-10 max-h-[152px] resize-none rounded-lg border border-hairline bg-surface px-3 py-2.5 text-[14px] leading-[1.6] outline-none focus:border-primary/60 focus:ring-1 focus:ring-primary/30 focus:shadow-[0_0_18px_rgba(62,201,176,0.12)] transition-all duration-200"
        />
        <button
          onClick={handleSend}
          disabled={!canSend}
          className={`w-10 h-10 shrink-0 rounded-lg flex items-center justify-center transition-all duration-200 active:scale-95 ${
            canSend
              ? 'bg-primary text-primary-ink hover:opacity-90 glow-primary'
              : 'bg-elevated text-ink-dim/70'
          }`}
          aria-label="传光"
        >
          {streaming ? (
            <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <Icon name="send-light" size={17} />
          )}
        </button>
      </div>
    </div>
  )
}
