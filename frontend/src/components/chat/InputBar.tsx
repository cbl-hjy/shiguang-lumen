import { useEffect, useRef, useState, type DragEvent } from 'react'
import { useChatStore } from '../../store/chatStore'
import ActivityMeter from './ActivityMeter'
import Icon from '../ui/Icon'
import { createSpeechRecognition, speechSupported } from '../../hooks/useSpeechInput'

/* 输入区（v3 聚合 2026-08-26 + 移动端豆包式 2026-08-27）：
   - 桌面：低调附件按钮 + 输入框 + 发送，支持拖拽文件上传
   - 移动端：左=相机（capture 直拍）· 右=语音（占位）+ 加号（弹面板：相机/相册/文件）
   三个独立 file input（camera/album/file）分别对应 capture/相册/通用——绕过系统文件选择器面板
   （Android 部分浏览器该面板带"麦克风"入口，用户误以为要开麦克风；capture 直开相机不经过面板） */
export default function InputBar() {
  const [text, setText] = useState('')
  const [pending, setPending] = useState<{ name: string; b64: string } | null>(null)
  const [addOpen, setAddOpen] = useState(false) // 加号面板
  const [voiceTip, setVoiceTip] = useState('') // 语音提示（空=不显示；支持检测/错误/降级）
  const [listening, setListening] = useState(false) // 2026-08-29 语音输入：录音中
  const cameraRef = useRef<HTMLInputElement>(null)
  const albumRef = useRef<HTMLInputElement>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const textRef = useRef<HTMLTextAreaElement>(null)
  const recRef = useRef<{ stop: () => void } | null>(null) // 语音识别控制器
  const voiceBaseRef = useRef('') // 开始录音时输入框内容（识别结果追加其后）
  const voiceTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const streaming = useChatStore((s) => s.streaming)
  const send = useChatStore((s) => s.send)

  /* 2026-08-29 语音输入：切换录音（Web Speech API；不支持→诚实降级提示）。
     设计：录音中 mic 按钮红色脉冲；interim 结果实时填输入框（追加在开始时的内容后）；
     停止保留最终文本；错误/不支持显示中文提示（替代原"开发中"占位）。 */
  const toggleVoice = () => {
    if (voiceTimer.current) clearTimeout(voiceTimer.current)
    if (listening) {
      recRef.current?.stop()
      return
    }
    if (!speechSupported()) {
      setVoiceTip('当前环境不支持语音输入（需 Edge/Chrome 浏览器 + 麦克风权限）')
      voiceTimer.current = setTimeout(() => setVoiceTip(''), 3500)
      return
    }
    voiceBaseRef.current = text
    const rec = createSpeechRecognition({
      onInterim: (t) => setText(voiceBaseRef.current + t),
      onFinal: (t) => setText(voiceBaseRef.current + t),
      onEnd: () => {
        setListening(false)
        recRef.current = null
      },
      onError: (msg) => {
        setListening(false)
        recRef.current = null
        setVoiceTip(msg)
        voiceTimer.current = setTimeout(() => setVoiceTip(''), 3500)
      },
    })
    if (!rec) {
      setVoiceTip('语音输入初始化失败')
      voiceTimer.current = setTimeout(() => setVoiceTip(''), 3500)
      return
    }
    recRef.current = rec
    rec.start()
    setListening(true)
  }

  /* 键盘适配（2026-08-28 UX 优化 A2，对标 LobeChat visualViewport）：
     软键盘弹起/收起时，保证输入框在可视区内（不被键盘遮挡） */
  useEffect(() => {
    const el = textRef.current
    const vv = window.visualViewport
    if (!vv || !el) return
    const onResize = () => {
      // 键盘弹起（可视区变矮）时把输入框滚入可视区
      el.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
    vv.addEventListener('resize', onResize)
    return () => vv.removeEventListener('resize', onResize)
  }, [])

  /* 消息引用/编辑（UX 优化 D7）：MessageBubble 派发 shiguang-quote → 内容回填输入框 */
  useEffect(() => {
    const onQuote = (e: Event) => {
      const text = (e as CustomEvent<string>).detail
      if (!text) return
      setText(text)
      requestAnimationFrame(() => {
        textRef.current?.focus()
        resize()
      })
    }
    window.addEventListener('shiguang-quote', onQuote)
    return () => window.removeEventListener('shiguang-quote', onQuote)
  }, [])

  /* 设备区分（2026-08-28 最终方案）：屏幕宽度驱动（matchMedia）——不依赖 UA/触摸点，
     WebView 手机屏宽 <768px 必然走移动端胶囊布局，绝不再误判桌面端（旧框残留的根因彻底根除） */
  const [isMobile, setIsMobile] = useState(
    () => typeof window !== 'undefined' && window.matchMedia('(max-width: 767px)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 767px)')
    const fn = (e: MediaQueryListEvent) => setIsMobile(e.matches)
    mq.addEventListener('change', fn)
    return () => mq.removeEventListener('change', fn)
  }, [])

  const canSend = (text.trim().length > 0 || pending) && !streaming

  /* 自适应高度：1 行 → 最多 6 行（150px，与 CSS max-h 一致），超出内部滚动。
     2026-08-28 修复：JS 高度上限与 Tailwind max-h-[152px] 对齐（原 164px 不一致）；
     多行后自动滚到光标处（移动端输入法弹起时光标可见） */
  const resize = () => {
    const el = textRef.current
    if (!el) return
    el.style.height = 'auto'
    const h = Math.min(el.scrollHeight, 150)
    el.style.height = `${h}px`
    if (h >= 150) el.scrollTop = el.scrollHeight
  }

  const handleFile = (f: File) => {
    const reader = new FileReader()
    reader.onload = () => setPending({ name: f.name, b64: String(reader.result) })
    reader.readAsDataURL(f)
  }

  /* 触发某个上传渠道（关面板再触发，避免面板遮挡系统选择器） */
  const pick = (ref: React.RefObject<HTMLInputElement | null>) => {
    setAddOpen(false)
    ref.current?.click()
  }

  const clearInput = (ref: React.RefObject<HTMLInputElement | null>) => {
    if (ref.current) ref.current.value = ''
  }

  /* 拖拽上传（桌面）：拖文件到输入区 */
  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    const f = e.dataTransfer.files?.[0]
    if (f) handleFile(f)
  }

  /* 发送光束（2026-08-28：移动端 :active 不可靠 → onClick 加 class 触发 send-beam 动画） */
  const fireBeam = (e: React.MouseEvent<HTMLButtonElement>) => {
    e.currentTarget.classList.remove('beam-fire')
    void e.currentTarget.offsetWidth // 强制 reflow 以重启动画
    e.currentTarget.classList.add('beam-fire')
    setTimeout(() => e.currentTarget.classList.remove('beam-fire'), 550)
  }

  const handleSend = async () => {
    if (!canSend) return
    await send(text.trim() || '(请看一下我拾入的文件)', pending ?? undefined)
    setText('')
    setPending(null)
    clearInput(cameraRef)
    clearInput(albumRef)
    clearInput(fileRef)
    if (textRef.current) {
      textRef.current.style.height = 'auto'
      textRef.current.focus()
    }
  }

  return (
    <div
      className="p-4 border-t border-hairline relative"
      onDragOver={(e) => e.preventDefault()}
      onDrop={onDrop}
    >
      <ActivityMeter />
      {pending && (
        <div className="mb-2 text-[12px] text-primary/90 flex items-center gap-2 max-w-[640px] mx-auto">
          <Icon name="paperclip" size={13} />
          <span className="truncate">{pending.name}</span>
          <button
            onClick={() => setPending(null)}
            className="text-ink-dim hover:text-ink/85 transition-colors duration-150 shrink-0"
            aria-label="移除附件"
          >
            <Icon name="x" size={13} />
          </button>
        </div>
      )}
      {/* 2026-08-28 移动端全宽：外层去掉 max-w-640 对窄屏的干扰，胶囊 flex-1 撑满（豆包式） */}
      <div className="w-full max-w-[640px] mx-auto flex items-center gap-2 relative">
        {/* ===== 三个上传渠道（豆包式）：capture 直拍 / 相册 / 通用文件 ===== */}
        <input
          ref={cameraRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.[0]) handleFile(e.target.files[0])
            clearInput(cameraRef)
          }}
          id="lumen-camera"
        />
        <input
          ref={albumRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.[0]) handleFile(e.target.files[0])
            clearInput(albumRef)
          }}
          id="lumen-album"
        />
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          onChange={(e) => {
            if (e.target.files?.[0]) handleFile(e.target.files[0])
            clearInput(fileRef)
          }}
          id="lumen-file"
        />

        {isMobile ? (
          /* ===== 移动端豆包式胶囊输入框（2026-08-28 彻底重做）：
             聚焦时外观零变化（无边框变色/无光晕/无高亮）——物理上排除"第二个框"；
             光效只出现在按钮和面板上；占满宽度；输入第一个字起其他按钮消失只剩发送 ===== */
          <div
            className="chat-capsule flex-1 min-w-0 flex items-center rounded-[22px] border border-ink/40 bg-elevated pl-1 pr-1 min-h-11 transition-colors duration-300"
            style={{ WebkitTapHighlightColor: 'transparent' }}
          >
            {!text.trim() && !pending && (
              <button
                onClick={() => pick(cameraRef)}
                className="w-11 h-11 shrink-0 rounded-full flex items-center justify-center text-ink-muted hover:text-primary transition-colors duration-150"
                aria-label="拍照"
                title="拍照给拾光看"
              >
                <Icon name="camera" size={17} />
              </button>
            )}
            <textarea
              ref={textRef}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                resize()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="输入你想学的 / 想问的…"
              rows={1}
              aria-label="输入消息"
              className="flex-1 min-w-0 bg-transparent px-1.5 py-2.5 text-[14px] leading-[1.5] resize-none placeholder:text-ink-dim/70 max-h-[150px]"
              style={{
                border: 'none',
                outline: 'none',
                boxShadow: 'none',
                WebkitAppearance: 'none',
                appearance: 'none',
                background: 'transparent',
                WebkitTapHighlightColor: 'transparent',
                scrollbarWidth: 'none', // 隐藏内部滚动条（沉浸胶囊，移动端不出现难看的滚动条）
              }}
            />
            {text.trim() || pending ? (
              <button
                onClick={(e) => { fireBeam(e); handleSend() }}
                disabled={!canSend}
                className={`w-11 h-11 shrink-0 rounded-full flex items-center justify-center transition-all duration-200 active:scale-95 send-beam ripple ${
                  canSend
                    ? 'bg-primary text-primary-ink hover:opacity-90'
                    : 'bg-elevated text-ink-dim/70'
                }`}
                aria-label="传光"
              >
                {streaming ? (
                  <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                    <path
                      d="M4 12l16-8-6 16-2.5-6z"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </button>
            ) : (
              <>
                <button
                  onClick={toggleVoice}
                  className={`w-11 h-11 shrink-0 rounded-full flex items-center justify-center transition-colors duration-150 ${
                    listening ? 'text-red animate-pulse' : 'text-ink-muted hover:text-primary'
                  }`}
                  aria-label={listening ? '停止语音输入' : '语音输入'}
                  title={listening ? '点击停止' : '语音输入'}
                >
                  <Icon name="mic" size={16} />
                </button>
                <button
                  onClick={() => setAddOpen((v) => !v)}
                  className={`w-11 h-11 shrink-0 rounded-full flex items-center justify-center transition-colors duration-150 ${
                    addOpen ? 'text-primary' : 'text-ink-muted hover:text-primary'
                  }`}
                  aria-label="更多上传方式"
                  title="拍照 / 相册 / 文件"
                >
                  <Icon name="plus" size={17} />
                </button>
              </>
            )}

            {/* 加号面板：底部弹出 拍照 / 相册 / 文件（豆包式） */}
            {addOpen && (
              <div
                className="absolute bottom-full right-1 mb-2 w-40 rounded-xl border border-hairline bg-elevated shadow-2xl p-1.5 animate-toast-in z-20"
                role="menu"
                aria-label="上传方式"
              >
                {[
                  { label: '拍照', icon: 'camera' as const, ref: cameraRef },
                  { label: '相册', icon: 'image' as const, ref: albumRef },
                  { label: '文件', icon: 'file' as const, ref: fileRef },
                ].map((it) => (
                  <button
                    key={it.label}
                    onClick={() => pick(it.ref)}
                    className="w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-[13px] text-ink hover:bg-surface transition-colors duration-150"
                    role="menuitem"
                  >
                    <Icon name={it.icon} size={16} className="text-primary" />
                    {it.label}
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          /* ===== 桌面布局：附件 + 输入 + 发送（拖拽也可上传） ===== */
          <>
            <button
              onClick={() => fileRef.current?.click()}
              className="w-9 h-9 shrink-0 rounded-full border border-hairline bg-surface flex items-center justify-center hover:bg-elevated hover:border-amber/40 hover:shadow-[0_0_14px_rgba(230,190,120,.15)] active:scale-95 transition-all duration-150"
              aria-label="拾入图片或文档"
              title="拾入图片/文档（也支持直接拖拽到输入区）"
            >
              <Icon name="paperclip" size={16} className="text-ink-muted" />
            </button>
            {/* 2026-08-29 语音输入（桌面）：Web Speech API，录音中红色脉冲 */}
            <button
              onClick={toggleVoice}
              className={`w-10 h-10 shrink-0 rounded-full flex items-center justify-center transition-colors duration-150 ${
                listening ? 'text-red animate-pulse' : 'text-ink-muted hover:text-primary'
              }`}
              aria-label={listening ? '停止语音输入' : '语音输入'}
              title={listening ? '点击停止' : '语音输入'}
            >
              <Icon name="mic" size={16} />
            </button>
            <textarea
              ref={textRef}
              value={text}
              onChange={(e) => {
                setText(e.target.value)
                resize()
              }}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              placeholder="输入你想学的 / 想问的…（Enter 传光，Shift+Enter 换行；文件可直接拖进来）"
              rows={1}
              aria-label="输入消息"
              className="flex-1 min-h-10 max-h-[152px] resize-none rounded-lg border border-ink/50 bg-elevated px-3 py-2.5 text-[14px] leading-[1.6] outline-none hover:border-ink/60 focus:border-primary/60 focus:ring-1 focus:ring-primary/30 focus:shadow-[0_0_18px_rgba(62,201,176,0.12)] transition-all duration-200"
            />
            <button
              onClick={(e) => { fireBeam(e); handleSend() }}
              disabled={!canSend}
              className={`w-10 h-10 shrink-0 rounded-full flex items-center justify-center transition-all duration-200 active:scale-95 send-beam ripple ${
                canSend
                  ? 'bg-primary text-primary-ink hover:opacity-90 hover:scale-105 hover:shadow-[0_0_20px_rgba(62,201,176,0.3)]'
                  : 'bg-elevated text-ink-dim/70'
              }`}
              aria-label="传光"
            >
              {streaming ? (
                <span className="w-4 h-4 border-2 border-current border-t-transparent rounded-full animate-spin" />
              ) : (
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none">
                  <path
                    d="M4 12l16-8-6 16-2.5-6z"
                    stroke="currentColor"
                    strokeWidth="1.8"
                    strokeLinejoin="round"
                  />
                </svg>
              )}
            </button>
          </>
        )}
      </div>

      {/* 语音提示（2026-08-29：支持检测失败/权限/服务错误；录音中显示状态） */}
      {voiceTip && (
        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-10 z-30 rounded-lg bg-elevated border border-hairline px-3 py-1.5 text-[12px] text-ink-muted shadow-2xl animate-toast-in whitespace-nowrap">
          {voiceTip}
        </div>
      )}
      {listening && (
        <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-10 z-30 rounded-lg bg-elevated border border-red/30 px-3 py-1.5 text-[12px] text-red shadow-2xl animate-toast-in whitespace-nowrap flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full bg-red animate-pulse" />
          正在听… 说完点一下麦克风
        </div>
      )}
    </div>
  )
}
