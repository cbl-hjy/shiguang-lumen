import React, { useState, useDeferredValue, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../../types/chat'
import { sendFeedback } from '../../api/feedback'
import { useChatStore } from '../../store/chatStore'
import ThinkingBlock from './ThinkingBlock'
import ToolCallCard from './ToolCallCard'
import MermaidRenderer from './MermaidRenderer'
import Icon from '../ui/Icon'
import DebateMessage from '../council/DebateMessage'

function Cursor() {
  /* 流式光点：teal 发光圆点（样式在 tokens.css .animate-cursor，"光在打字"） */
  return <span className="animate-cursor" aria-hidden />
}

function CopyToast() {
  return (
    <span className="fixed bottom-20 right-6 z-50 flex items-center gap-2 rounded-lg bg-elevated border border-hairline px-3 py-2 text-[12px] text-ink/90 shadow-2xl animate-toast-in">
      <span className="empty-light" />
      已复制
    </span>
  )
}

/* 从 ReactNode 提取纯文本（代码块/流程图代码内容；2026-08-27 提升为模块级：mdComponents 与 zoomComponents 共用） */
function extractText(node: React.ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(extractText).join('')
  if (React.isValidElement(node)) {
    return extractText((node.props as { children?: React.ReactNode })?.children)
  }
  return ''
}

/* 内容块右上角工具条（2026-08-28 豆包式：图片/流程图/代码 常驻 复制+放大 按钮，点击放大=全屏） */
function ContentActions({
  onCopy,
  onZoom,
  zoomLabel,
}: {
  onCopy: () => Promise<void> | void
  onZoom: () => void
  zoomLabel: string
}) {
  const [ok, setOk] = useState(false)
  const [busy, setBusy] = useState(false)
  const doCopy = async () => {
    if (busy) return
    setBusy(true)
    try {
      await onCopy()
      setOk(true)
      setTimeout(() => setOk(false), 1400)
    } catch {
      /* 复制失败静默 */
    } finally {
      setBusy(false)
    }
  }
  return (
    <div className="absolute top-1.5 right-1.5 flex items-center gap-1 z-10">
      <button
        onClick={(e) => {
          e.stopPropagation()
          doCopy()
        }}
        className="w-6 h-6 rounded-md bg-black/60 backdrop-blur flex items-center justify-center text-white/85 hover:bg-black/80 hover:text-white transition-colors duration-150"
        aria-label="复制"
        title="复制"
      >
        {ok ? (
          <Icon name="check" size={12} className="text-success" />
        ) : (
          <Icon name="copy" size={12} />
        )}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation()
          onZoom()
        }}
        className="w-6 h-6 rounded-md bg-black/60 backdrop-blur flex items-center justify-center text-white/85 hover:bg-black/80 hover:text-white transition-colors duration-150"
        aria-label={zoomLabel}
        title={zoomLabel}
      >
        <Icon name="maximize" size={12} />
      </button>
    </div>
  )
}

/* 复制图片：优先复制图片本身（剪贴板），不可用（非 secure context/浏览器限制）则降级复制 URL */
async function copyImageSrc(src: string) {
  try {
    const res = await fetch(src)
    const blob = await res.blob()
    const item = new ClipboardItem({ [blob.type]: blob })
    await navigator.clipboard.write([item])
    return
  } catch {
    /* 降级 */
  }
  try {
    await navigator.clipboard.writeText(src)
  } catch {
    /* 忽略 */
  }
}

/* Lightbox 大图：加载中提示 + 失败兜底（2026-08-27 移动端"点开只有变暗没内容"——补状态展示防空屏） */
function ZoomImage({ src }: { src: string }) {
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  return (
    <div className="relative max-w-full max-h-full" onClick={(e) => e.stopPropagation()}>
      {!loaded && !failed && (
        <div className="px-8 py-6 text-[13px] text-white/70">图片加载中…</div>
      )}
      {failed ? (
        <div className="px-8 py-6 text-[13px] text-white/80 rounded-lg bg-white/10">
          图片加载失败（{src.slice(0, 60)}）
          <div className="mt-2">
            <button
              onClick={() => window.open(src, '_blank')}
              className="text-primary underline underline-offset-2"
            >
              在新标签页打开
            </button>
          </div>
        </div>
      ) : (
        <img
          src={src}
          alt="放大预览"
          onLoad={() => setLoaded(true)}
          onError={() => setFailed(true)}
          className="max-w-full max-h-full object-contain rounded-lg cursor-zoom-out"
          style={loaded ? undefined : { visibility: 'hidden' }}
        />
      )}
    </div>
  )
}

/* Markdown 渲染样式：适配文楷正文 + mono 代码块 + teal 链接，安全（react-markdown 默认不渲染原始 HTML） */
const mdComponents = {
  p: (props: ComponentPropsWithoutRef<'p'>) => <p className="mb-2 last:mb-0" {...props} />,
  strong: (props: ComponentPropsWithoutRef<'strong'>) => (
    <strong className="font-medium text-[rgba(236,233,225,1)]" {...props} />
  ),
  ul: (props: ComponentPropsWithoutRef<'ul'>) => (
    <ul className="mb-2 pl-4 list-disc space-y-0.5" {...props} />
  ),
  ol: (props: ComponentPropsWithoutRef<'ol'>) => (
    <ol className="mb-2 pl-4 list-decimal space-y-0.5" {...props} />
  ),
  li: (props: ComponentPropsWithoutRef<'li'>) => <li className="leading-[1.7]" {...props} />,
  code: (props: ComponentPropsWithoutRef<'code'>) => (
    <code
      className="font-mono text-[13px] bg-elevated border border-hairline rounded px-1 py-0.5 text-primary"
      {...props}
    />
  ),
  pre: (props: ComponentPropsWithoutRef<'pre'>) => {
    /* mermaid 代码块 → 渲染成图（模型自主判断何时用，前端只负责画）
       注意：react-markdown 会把 ```mermaid 围栏解析掉——code 元素的 children 是纯代码内容，
       language 信息在 className（language-mermaid）里，所以不能 startsWith('```mermaid') */
    const child = props.children
    const codeEl = Array.isArray(child) ? child.find((c) => React.isValidElement(c)) : child
    const isMermaid =
      React.isValidElement(codeEl) &&
      String((codeEl.props as { className?: string })?.className || '').includes('language-mermaid')
    if (isMermaid) {
      const code = extractText((codeEl.props as { children?: React.ReactNode })?.children).trim()
      if (code) return <MermaidRenderer code={code} />
    }
    return (
      <pre
        className="mb-2 p-3 rounded-lg bg-[#0d0f13] border border-hairline overflow-x-auto font-mono text-[13px] leading-[1.6]"
        {...props}
      />
    )
  },
  blockquote: (props: ComponentPropsWithoutRef<'blockquote'>) => (
    <blockquote className="mb-2 pl-3 border-l-2 border-primary/50 text-ink-muted" {...props} />
  ),
  h1: (props: ComponentPropsWithoutRef<'h1'>) => (
    <h1 className="text-[18px] font-medium mb-2 mt-3 first:mt-0" {...props} />
  ),
  h2: (props: ComponentPropsWithoutRef<'h2'>) => (
    <h2 className="text-[16px] font-medium mb-2 mt-3 first:mt-0" {...props} />
  ),
  h3: (props: ComponentPropsWithoutRef<'h3'>) => (
    <h3 className="text-[15px] font-medium mb-1.5 mt-2.5 first:mt-0" {...props} />
  ),
  a: (props: ComponentPropsWithoutRef<'a'>) => (
    <a
      className="text-primary underline underline-offset-2 hover:opacity-80"
      target="_blank"
      rel="noreferrer"
      {...props}
    />
  ),
  /* 图片：点击放大预览（模型生成图可看全，2026-08-26 用户要求；容器加宽已防压缩） */
  img: (props: ComponentPropsWithoutRef<'img'>) => (
    <img
      className="max-w-full rounded-lg cursor-zoom-in my-2 border border-hairline"
      onClick={() => props.src && window.open(props.src, '_blank')}
      loading="lazy"
      alt={props.alt || ''}
      src={props.src}
    />
  ),
  table: (props: ComponentPropsWithoutRef<'table'>) => (
    <div className="mb-2 overflow-x-auto">
      <table className="text-[13px] border-collapse" {...props} />
    </div>
  ),
  th: (props: ComponentPropsWithoutRef<'th'>) => (
    <th
      className="border border-ink/30 bg-elevated px-2 py-1 font-medium text-left text-ink-strong"
      {...props}
    />
  ),
  td: (props: ComponentPropsWithoutRef<'td'>) => (
    <td className="border border-ink/30 px-2 py-1" {...props} />
  ),
}

function MarkdownBody({
  content,
  components,
}: {
  content: string
  components?: ComponentPropsWithoutRef<typeof ReactMarkdown>['components']
}) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={components ?? mdComponents}>
      {content}
    </ReactMarkdown>
  )
}

/* 单条消息：用户右侧 / 助手左侧，含思考折叠、工具卡片、复制、👎/👍 反馈（M8 进化信号）、流式光点、失败重试（#6） */
export default function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === 'user'
  const [copied, setCopied] = useState(false)
  const [feedback, setFeedback] = useState<'up' | 'down' | null>(null)
  const [feedbackBusy, setFeedbackBusy] = useState(false)
  const [speaking, setSpeaking] = useState(false) // 朗读状态（2026-08-28 消息操作栏）
  /* 放大预览（2026-08-27：页内 Lightbox 替代 window.open——移动端新标签常被拦截；三种内容都可放大：图/流程图/代码） */
  const [zoom, setZoom] = useState<
    | { kind: 'image'; src: string }
    | { kind: 'mermaid'; code: string }
    | { kind: 'code'; text: string }
    | null
  >(null)
  /* P1-5 渲染节流（2026-08-27，对齐 AI SDK throttle）：流式长内容每 chunk 全量重渲染 markdown 很重——
     useDeferredValue 让低优先级渲染延后合并，输入/滚动不卡顿（React 19 官方机制，非手写 throttle） */
  const deferredContent = useDeferredValue(msg.content)
  const retry = useChatStore((s) => s.retry)
  const allMessages = useChatStore((s) => s.messages)

  /* 放大组件覆盖：mdComponents 是模块级常量（img 用 window.open），此处覆盖 img/pre 为页内放大；
     setZoom 是稳定引用（React setState），空 deps 安全 */
  const zoomComponents = React.useMemo<ComponentPropsWithoutRef<typeof ReactMarkdown>['components']>(
    () => ({
      ...mdComponents,
      img: (props: ComponentPropsWithoutRef<'img'>) => {
        const src = props.src
        return (
          /* 豆包式：容器加深背景 + 右上角常驻 复制/放大 按钮（2026-08-28） */
          <div className="relative my-2 rounded-lg border border-hairline bg-elevated/50 overflow-hidden group">
            <ContentActions
              onCopy={async () => {
                if (src) await copyImageSrc(src)
              }}
              onZoom={() => src && setZoom({ kind: 'image', src })}
              zoomLabel="放大图片"
            />
            <img
              className="max-w-full rounded-lg cursor-zoom-in"
              onClick={() => src && setZoom({ kind: 'image', src })}
              loading="lazy"
              alt={props.alt || ''}
              src={src}
            />
          </div>
        )
      },
      /* 代码块/流程图：背景加深 + 右上角 复制/放大（小屏看不清代码、流程图的刚需；mermaid 用原始 code 重渲染大图） */
      pre: (props: ComponentPropsWithoutRef<'pre'>) => {
        const child = props.children
        const codeEl = Array.isArray(child) ? child.find((c) => React.isValidElement(c)) : child
        const isMermaid =
          React.isValidElement(codeEl) &&
          String((codeEl.props as { className?: string })?.className || '').includes(
            'language-mermaid',
          )
        if (isMermaid) {
          const code = extractText(
            (codeEl.props as { children?: React.ReactNode })?.children,
          ).trim()
          if (code) {
            return (
              <div className="relative my-2 rounded-lg overflow-hidden group">
                <ContentActions
                  onCopy={() => navigator.clipboard?.writeText(code)}
                  onZoom={() => setZoom({ kind: 'mermaid', code })}
                  zoomLabel="放大流程图"
                />
                <div
                  className="cursor-zoom-in"
                  onClick={() => setZoom({ kind: 'mermaid', code })}
                  role="button"
                  aria-label="放大流程图"
                >
                  <MermaidRenderer code={code} />
                </div>
              </div>
            )
          }
        }
        const text = extractText(props.children)
        return (
          <div className="relative my-2 rounded-lg overflow-hidden group">
            <ContentActions
              onCopy={() => navigator.clipboard?.writeText(text)}
              onZoom={() => setZoom({ kind: 'code', text })}
              zoomLabel="放大代码"
            />
            <pre
              className="p-3 rounded-lg bg-[#0d0f13] border border-hairline overflow-x-auto font-mono text-[13px] leading-[1.6] cursor-zoom-in"
              onClick={() => setZoom({ kind: 'code', text })}
              role="button"
              aria-label="放大代码"
              {...props}
            />
          </div>
        )
      },
    }),
    [],
  )

  /* 重试修复（2026-08-27）：必须重发【原始用户输入】，绝不重发 bot 内容/错误文本——
     优先 bot 记录的 userPrompt；历史会话无记录时回退找上一条 user 消息；都找不到才禁用 */
  const retryTarget = (() => {
    if (msg.userPrompt) return msg.userPrompt
    const idx = allMessages.findIndex((x) => x.id === msg.id)
    if (idx > 0) {
      const prev = [...allMessages.slice(0, idx)].reverse().find((x) => x.role === 'user')
      if (prev) return prev.content
    }
    return ''
  })()

  /* 问星（M3）：role='debate' 的辩论事件消息走专用渲染（与普通消息同流） */
  if (msg.role === 'debate') {
    return (
      <div className="flex justify-start mb-4 animate-msg-in">
        <div className="max-w-[92%] w-full">
          <DebateMessage ev={msg.debateEvent!} msgId={msg.id} />
        </div>
      </div>
    )
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(msg.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* 剪贴板不可用时静默 */
    }
  }

  const giveFeedback = async (rating: -1 | 1) => {
    if (feedbackBusy || feedback) return
    setFeedbackBusy(true)
    try {
      await sendFeedback(rating, msg.content)
      setFeedback(rating === 1 ? 'up' : 'down')
    } catch {
      /* 反馈失败不打扰 */
    } finally {
      setFeedbackBusy(false)
    }
  }

  /* 朗读全文（2026-08-28：Web Speech API 中文 TTS，无后端依赖；WebView/浏览器不支持时按钮不显示） */
  const speak = () => {
    if (!('speechSynthesis' in window)) return
    if (speaking) {
      window.speechSynthesis.cancel()
      setSpeaking(false)
      return
    }
    const clean = msg.content
      .replace(/```[\s\S]*?```/g, '代码块')
      .replace(/[#*`>|_~\[\]()!]/g, ' ')
      .replace(/\s+/g, ' ')
      .trim()
    if (!clean) return
    const u = new SpeechSynthesisUtterance(clean)
    u.lang = 'zh-CN'
    u.rate = 1
    u.onend = () => setSpeaking(false)
    u.onerror = () => setSpeaking(false)
    window.speechSynthesis.cancel()
    window.speechSynthesis.speak(u)
    setSpeaking(true)
  }

  /* 转发（2026-08-28：Web Share API → 降级复制内容） */
  const share = async () => {
    try {
      if (navigator.share) {
        await navigator.share({ title: '拾光 Lumen', text: msg.content })
        return
      }
    } catch {
      /* 用户取消等静默 */
    }
    try {
      await navigator.clipboard.writeText(msg.content)
      setCopied(true)
      setTimeout(() => setCopied(false), 1400)
    } catch {
      /* 忽略 */
    }
  }

  return (
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'} mb-4 animate-msg-in`}>
      <div
        className={`relative max-w-[98%] md:max-w-[85%] px-4 py-3 text-[14px] leading-[1.7] transition-[filter,border-color] duration-200 hover:brightness-105 ${
          isUser
            ? 'rounded-[18px_4px_18px_18px] bg-elevated border border-ink/35 text-[rgba(236,233,225,0.95)] hover:border-ink/55'
            : 'rounded-[4px_18px_18px_18px] bg-surface/85 border border-ink/50 text-ink-strong slit-light hover:border-ink/75'
        }`}
      >
        {!isUser && <ThinkingBlock text={msg.thinking} />}
        {!isUser && !msg.done && !msg.content && !msg.thinking && msg.toolCalls.length === 0 && (
          /* v3：等待首响应——三色流光（极光紫→青→琥珀，沿弧线流动） */
          <div className="orb-flow">
            <i />
            <i />
            <i />
          </div>
        )}
        {isUser && msg.done && (
          /* 用户消息"编辑"（UX 优化 D7）：内容回填输入框重新编辑/发送 */
          <button
            onClick={() =>
              window.dispatchEvent(new CustomEvent('shiguang-quote', { detail: msg.content }))
            }
            className="absolute -top-2 -right-2 w-6 h-6 rounded-full bg-elevated border border-hairline text-ink-dim opacity-0 group-hover:opacity-100 hover:text-primary transition-all duration-150 active:scale-90"
            aria-label="编辑这条消息"
            title="编辑（内容回填输入框）"
          >
            <Icon name="wrench" size={11} className="mx-auto" />
          </button>
        )}
        {!isUser && msg.toolCalls.length > 0 && (
          <div className="flex flex-wrap mb-1.5">
            {msg.toolCalls.map((t, i) => (
              <ToolCallCard key={`${t.name}-${i}`} call={t} />
            ))}
          </div>
        )}
        <div className={isUser ? 'whitespace-pre-wrap break-words' : 'break-words'}>
          {isUser ? msg.content : <MarkdownBody content={deferredContent} components={zoomComponents} />}
          {!msg.done ? (
            <Cursor />
          ) : !isUser && msg.content ? (
            <span className="done-dot" aria-hidden />
          ) : null}
        </div>
        {/* 闪光时刻（v3 仪式条）：琥珀渐变底 + 星形旋转 + 波纹环——"拾到我们没发现的闪光" */}
        {!isUser && msg.glint && (
          <div
            className="mt-2.5 flex items-center gap-2 px-3 py-1.5 rounded-full border border-amber/35 bg-[linear-gradient(135deg,rgba(230,190,120,0.12),rgba(230,190,120,0.04))] cursor-help"
            title={msg.glint}
          >
            <span className="ring-wave relative w-4 h-4 shrink-0 flex items-center justify-center">
              <svg viewBox="0 0 24 24" className="w-3.5 h-3.5">
                <path
                  d="M12 3l2.4 4.6L19 9.4l-3.6 3.6.9 5-4.3-2.3-4.3 2.3.9-5L5 9.4l4.6-1.8z"
                  fill="none"
                  stroke="#e6be78"
                  strokeWidth="1"
                  style={{ transformBox: 'fill-box', transformOrigin: 'center' }}
                  className="animate-[spin_3s_linear_infinite]"
                />
                <circle cx="12" cy="12" r="1.5" fill="#e6be78" />
              </svg>
            </span>
            <span className="text-[11px] text-amber/95 tracking-wide">✦ 拾到闪光</span>
          </div>
        )}
        {/* 截断提示（2026-08-27 根治"静默半截"）：内容有效但被单次输出上限截断——琥珀色提示可继续，非红色错误 */}
        {!isUser && msg.truncated && !msg.failed && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-amber/90">⚠️ 回复达到模型单次输出上限被截断</span>
            <span className="text-ink-dim">（内容不完整——直接说「继续」即可接着写）</span>
          </div>
        )}
        {/* 工具执行后无正文提示（2026-08-27）：工具跑完但模型没写解读——不是错误，只是让你知道"没输出" */}
        {!isUser && msg.toolOnly && !msg.failed && !msg.truncated && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-primary/70">
              ⚙️ 工具已执行{msg.toolOnlyTools?.length ? `（${msg.toolOnlyTools.join(' / ')}）` : ''}
              ，拾光未输出文字
            </span>
            <span className="text-ink-dim">（想看解读/下一步，直接问它）</span>
          </div>
        )}
        {/* 系统消息（2026-08-30 接地纠错循环 n=5 硬停止）：harness 直发、非模型内容——
            「系统」徽标 + 琥珀正文，与模型口吻明确区分 */}
        {!isUser && msg.systemNotes?.map((note, i) => (
          <div key={i} className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="px-1.5 py-0.5 rounded border border-hairline text-ink-dim text-[10px] tracking-wide">
              系统
            </span>
            <span className="text-amber/90">{note}</span>
          </div>
        ))}
        {/* #6 失败提示 + 手动重试（backend=已落库；timeout/interrupted/network=可能未落库——文案区分）
            hint=后端给的领航建议（2026-08-20 异常收尾：错误不是终点是引导） */}
        {!isUser && msg.failed && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-error/90">⚠️ {msg.failed.message}</span>
            {msg.failed.hint && <span className="text-primary/60">（{msg.failed.hint}）</span>}
            <button
              onClick={() => retryTarget && retry(retryTarget)}
              disabled={!retryTarget}
              className={`px-2.5 py-1 rounded-lg border border-hairline text-primary/80 hover:text-primary hover:border-primary/40 hover:bg-elevated transition-colors duration-150 ${
                retryTarget ? '' : 'opacity-40 cursor-not-allowed'
              }`}
              aria-label="重试这条消息"
              title="重发原始问题（不会把错误文本当问题发回）"
            >
              <Icon name="arrow-right" size={11} className="inline -rotate-90 mr-1" />
              重试
            </button>
          </div>
        )}
        {/* 模型消息底部操作栏（2026-08-28：常驻显示——原右上角 hover 区在手机上不可见）：
            复制全部 / 朗读 / 讲得好 / 讲得不好 / 转发 / 重新生成 */}
        {!isUser && msg.done && msg.content && (
          <div className="mt-2.5 pt-2 border-t border-hairline/70 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px] text-ink-dim/85">
            <button
              onClick={copy}
              className="flex items-center gap-1 hover:text-primary active:scale-95 transition-all duration-150"
              aria-label="复制全部内容"
            >
              <Icon
                name={copied ? 'check' : 'copy'}
                size={12}
                className={copied ? 'text-success' : ''}
              />
              {copied ? '已复制' : '复制'}
            </button>
            {'speechSynthesis' in window && (
              <button
                onClick={speak}
                className={`flex items-center gap-1 transition-colors duration-150 ${
                  speaking ? 'text-primary' : 'hover:text-primary'
                }`}
                aria-label={speaking ? '停止朗读' : '朗读全文'}
              >
                <Icon name="volume" size={12} />
                {speaking ? '停止' : '朗读'}
              </button>
            )}
            <button
              onClick={() => giveFeedback(1)}
              disabled={!!feedback}
              className={`flex items-center gap-1 transition-colors duration-150 ${
                feedback === 'up' ? 'text-success' : 'hover:text-success disabled:opacity-40'
              }`}
              aria-label="讲得好"
            >
              <Icon name="thumbs-up" size={12} />
              讲得好
            </button>
            <button
              onClick={() => giveFeedback(-1)}
              disabled={!!feedback}
              className={`flex items-center gap-1 transition-colors duration-150 ${
                feedback === 'down' ? 'text-error' : 'hover:text-error disabled:opacity-40'
              }`}
              aria-label="讲得不好"
            >
              <Icon name="thumbs-down" size={12} />
              讲得不好
            </button>
            <button
              onClick={share}
              className="flex items-center gap-1 hover:text-primary active:scale-95 transition-all duration-150"
              aria-label="转发"
            >
              <Icon name="share" size={12} />
              转发
            </button>
            <button
              onClick={() => {
                // 引用（UX 优化 D7）：把内容填回输入框继续追问
                window.dispatchEvent(new CustomEvent('shiguang-quote', { detail: msg.content }))
              }}
              className="flex items-center gap-1 hover:text-primary active:scale-95 transition-all duration-150"
              aria-label="引用这条内容继续追问"
            >
              <Icon name="arrow-right" size={12} className="inline -rotate-90" />
              引用
            </button>
            {retryTarget && (
              <button
                onClick={() => retry(retryTarget)}
                className="flex items-center gap-1 hover:text-primary active:scale-95 transition-all duration-150"
                aria-label="重新生成"
                title="重新生成（重发原始问题）"
              >
                <Icon name="arrow-right" size={12} className="inline -rotate-90" />
                重新生成
              </button>
            )}
            {feedback && (
              <span className="text-[10px] whitespace-nowrap text-primary/80">
                {feedback === 'up' ? '已记住这个讲法' : '已收到，我会改进'}
              </span>
            )}
          </div>
        )}
      </div>
      {copied && <CopyToast />}

      {/* 放大预览 Lightbox（2026-08-27：页内全屏预览替代 window.open——移动端新标签常被拦截；图/流程图/代码三态） */}
      {zoom && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4 animate-toast-in"
          onClick={() => setZoom(null)}
          role="dialog"
          aria-label="放大预览"
        >
          <button
            onClick={() => setZoom(null)}
            className="absolute top-4 right-4 w-9 h-9 rounded-full bg-white/10 hover:bg-white/20 flex items-center justify-center text-white/90 transition-colors duration-150"
            aria-label="关闭预览"
          >
            <Icon name="x" size={18} />
          </button>
          {zoom.kind === 'image' && (
            <ZoomImage src={zoom.src} />
          )}
          {zoom.kind === 'mermaid' && (
            <div
              className="w-full max-h-full overflow-auto bg-[#14171c] rounded-lg p-4 cursor-zoom-out"
              onClick={(e) => e.stopPropagation()}
            >
              <MermaidRenderer code={zoom.code} />
            </div>
          )}
          {zoom.kind === 'code' && (
            <pre
              className="w-full max-h-full overflow-auto bg-[#0d0f13] rounded-lg p-5 font-mono text-[15px] leading-[1.7] text-[#e9e6dd] cursor-zoom-out whitespace-pre-wrap break-all"
              onClick={(e) => e.stopPropagation()}
            >
              {zoom.text}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
