import { useRef, useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'
import ActivityMeter from './ActivityMeter'

/* 输入区：多行自适应输入（Enter 发送 / Shift+Enter 换行）+ 上传（图片/PDF/文档）+ 发送 */
export default function InputBar() {
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
    await send(text.trim() || '(请看一下我上传的文件)', pending ?? undefined)
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
        <div className="mb-2 text-[12px] text-[rgba(62,201,176,0.9)] flex items-center gap-2">
          <Icon name="paperclip" size={13} />
          <span>{pending.name}</span>
          <button
            onClick={() => setPending(null)}
            className="text-[rgba(236,233,225,0.4)] hover:text-[rgba(236,233,225,0.8)] transition-colors duration-150"
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
          aria-label="上传图片或文档"
          title="上传图片/文档"
        >
          <Icon name="paperclip" size={17} className="text-[rgba(236,233,225,0.6)]" />
        </button>
        <textarea
          ref={textRef}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            resize()
          }}
          onKeyDown={(e) => {
            /* Enter 发送（IME 组合中不触发）；Shift+Enter 换行 */
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="输入你想学的 / 想问的…（Enter 发送，Shift+Enter 换行）"
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
              : 'bg-elevated text-[rgba(236,233,225,0.3)]'
          }`}
          aria-label="发送"
        >
          {streaming ? (
            <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
          ) : (
            <Icon name="arrow-right" size={17} />
          )}
        </button>
      </div>
    </div>
  )
}
