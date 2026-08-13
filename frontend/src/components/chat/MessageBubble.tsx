import React, { useState, type ComponentPropsWithoutRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { ChatMessage } from '../../types/chat'
import { sendFeedback } from '../../api/feedback'
import { useChatStore } from '../../store/chatStore'
import ThinkingBlock from './ThinkingBlock'
import ToolCallCard from './ToolCallCard'
import MermaidRenderer from './MermaidRenderer'
import Icon from '../ui/Icon'

function Cursor() {
  /* 流式光点：teal 发光圆点（样式在 tokens.css .animate-cursor，"光在打字"） */
  return <span className="animate-cursor" aria-hidden />
}

function CopyToast() {
  return (
    <span className="fixed bottom-20 right-6 z-50 flex items-center gap-2 rounded-lg bg-elevated border border-hairline px-3 py-2 text-[12px] text-[rgba(236,233,225,0.85)] shadow-2xl animate-toast-in">
      <span className="empty-light" />
      已复制
    </span>
  )
}

/* Markdown 渲染样式：适配文楷正文 + mono 代码块 + teal 链接，安全（react-markdown 默认不渲染原始 HTML） */
const mdComponents = {
  p: (props: ComponentPropsWithoutRef<'p'>) => (
    <p className="mb-2 last:mb-0" {...props} />
  ),
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
      className="font-mono text-[13px] bg-elevated border border-hairline rounded px-1 py-0.5 text-[rgba(62,201,176,0.95)]"
      {...props}
    />
  ),
  pre: (props: ComponentPropsWithoutRef<'pre'>) => {
    /* mermaid 代码块 → 渲染成图（模型自主判断何时用，前端只负责画）
       注意：react-markdown 会把 ```mermaid 围栏解析掉——code 元素的 children 是纯代码内容，
       language 信息在 className（language-mermaid）里，所以不能 startsWith('```mermaid') */
    const extractText = (node: React.ReactNode): string => {
      if (typeof node === 'string' || typeof node === 'number') return String(node)
      if (Array.isArray(node)) return node.map(extractText).join('')
      if (React.isValidElement(node)) {
        return extractText((node.props as { children?: React.ReactNode })?.children)
      }
      return ''
    }
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
    <blockquote
      className="mb-2 pl-3 border-l-2 border-primary/50 text-[rgba(236,233,225,0.7)]"
      {...props}
    />
  ),
  h1: (props: ComponentPropsWithoutRef<'h1'>) => <h1 className="text-[18px] font-medium mb-2 mt-3 first:mt-0" {...props} />,
  h2: (props: ComponentPropsWithoutRef<'h2'>) => <h2 className="text-[16px] font-medium mb-2 mt-3 first:mt-0" {...props} />,
  h3: (props: ComponentPropsWithoutRef<'h3'>) => <h3 className="text-[15px] font-medium mb-1.5 mt-2.5 first:mt-0" {...props} />,
  a: (props: ComponentPropsWithoutRef<'a'>) => (
    <a className="text-primary underline underline-offset-2 hover:opacity-80" target="_blank" rel="noreferrer" {...props} />
  ),
  table: (props: ComponentPropsWithoutRef<'table'>) => (
    <div className="mb-2 overflow-x-auto">
      <table className="text-[13px] border-collapse" {...props} />
    </div>
  ),
  th: (props: ComponentPropsWithoutRef<'th'>) => (
    <th className="border border-hairline px-2 py-1 font-medium text-left" {...props} />
  ),
  td: (props: ComponentPropsWithoutRef<'td'>) => (
    <td className="border border-hairline px-2 py-1" {...props} />
  ),
}

function MarkdownBody({ content }: { content: string }) {
  return (
    <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
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
  const retry = useChatStore((s) => s.retry)

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

  return (
    <div className={`group flex ${isUser ? 'justify-end' : 'justify-start'} mb-4 animate-msg-in`}>
      <div
        className={`relative max-w-[85%] rounded-xl px-4 py-3 text-[14px] leading-[1.7] ${
          isUser
            ? 'bg-elevated text-[rgba(236,233,225,0.95)]'
            : 'bg-surface text-[rgba(236,233,225,0.92)] msg-glow-strip'
        }`}
      >
        {!isUser && <ThinkingBlock text={msg.thinking} />}
        {!isUser && msg.toolCalls.length > 0 && (
          <div className="flex flex-wrap mb-1.5">
            {msg.toolCalls.map((t, i) => (
              <ToolCallCard key={`${t.name}-${i}`} call={t} />
            ))}
          </div>
        )}
        <div className={isUser ? 'whitespace-pre-wrap break-words' : 'break-words'}>
          {isUser ? msg.content : <MarkdownBody content={msg.content} />}
          {!msg.done ? <Cursor /> : !isUser && msg.content ? <span className="done-dot" aria-hidden /> : null}
        </div>
        {/* #6 失败提示 + 手动重试（backend=已落库；timeout/interrupted/network=可能未落库——文案区分） */}
        {!isUser && msg.failed && (
          <div className="mt-2 flex flex-wrap items-center gap-2 text-[12px]">
            <span className="text-error/90">⚠️ {msg.failed.message}</span>
            <button
              onClick={() => retry(msg.content || (msg.failed as { message: string }).message)}
              className="px-2.5 py-1 rounded-lg border border-hairline text-primary/80 hover:text-primary hover:border-primary/40 hover:bg-elevated transition-colors duration-150"
              aria-label="重试这条消息"
              title="手动重试（不会自动重发）"
            >
              <Icon name="arrow-right" size={11} className="inline -rotate-90 mr-1" />
              重试
            </button>
          </div>
        )}
        {!isUser && msg.done && msg.content && (
          <div
            className={`absolute -right-8 top-2 flex flex-col gap-1 transition-opacity duration-150 ${
              feedback ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'
            }`}
          >
            <button
              onClick={copy}
              className="text-[rgba(236,233,225,0.4)] hover:text-primary"
              aria-label="复制回答"
            >
              <Icon name={copied ? 'check' : 'copy'} size={14} className={copied ? 'text-success' : ''} />
            </button>
            <button
              onClick={() => giveFeedback(1)}
              disabled={!!feedback}
              className={`text-[rgba(236,233,225,0.4)] hover:text-success ${
                feedback === 'up' ? '!text-success' : ''
              }`}
              aria-label="讲得好"
              title="讲得好"
            >
              <Icon name="thumbs-up" size={14} />
            </button>
            <button
              onClick={() => giveFeedback(-1)}
              disabled={!!feedback}
              className={`text-[rgba(236,233,225,0.4)] hover:text-error ${
                feedback === 'down' ? '!text-error' : ''
              }`}
              aria-label="没听懂"
              title="没听懂/讲得不好"
            >
              <Icon name="thumbs-down" size={14} />
            </button>
            {feedback && (
              <span className="text-[10px] whitespace-nowrap text-primary/80">
                {feedback === 'up' ? '已记住这个讲法' : '已收到，我会改进'}
              </span>
            )}
          </div>
        )}
      </div>
      {copied && <CopyToast />}
    </div>
  )
}
