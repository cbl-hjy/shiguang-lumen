import { useEffect, useRef, useState } from 'react'
import type { ChatMessage } from '../../types/chat'
import MessageBubble from './MessageBubble'
import TaskProgressCard from './TaskProgressCard'
import Welcome from './Welcome'
import { useChatStore } from '../../store/chatStore'

/* 消息流：自动滚动 + 新消息淡入 + 空状态欢迎语（画像拼接）+ M7 并行任务进度卡
   2026-08-28 滚动修复：打开历史会话/发送消息 → 立即滚到底（auto 替代 smooth，历史长列表
   不再"从顶部慢慢滑"）；图片懒加载导致的高度变化 → 仅当接近底部时跟随（不打扰向上读历史）
   2026-08-29 拾光时刻：AI 回复完成（streaming true→false）→ 琥珀金波纹扩散（glint-ring，
   只动 transform/opacity 合成；一次性动画，key 变化重播） */
export default function ChatStream({ messages }: { messages: ChatMessage[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [glintKey, setGlintKey] = useState(0) // >0 时渲染拾光波纹

  /* AI 回复完成 → 琥珀金波纹（仪式感：一次回复=一次拾光） */
  const streaming = useChatStore((s) => s.streaming)
  const prevStreaming = useRef(streaming)
  useEffect(() => {
    const was = prevStreaming.current
    prevStreaming.current = streaming
    if (was && !streaming) {
      setGlintKey((k) => k + 1)
      const timer = setTimeout(() => setGlintKey(0), 900) // 波纹播完清掉
      return () => clearTimeout(timer)
    }
  }, [streaming])

  /* 消息变化（发送/打开会话/流式追加）→ 立即滚到底部（最新消息） */
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTop = el.scrollHeight
  }, [messages])

  /* 内容高度变化（图片/图表懒加载后撑高）→ 仅在接近底部时跟随，避免把读历史的用户拽下去 */
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const ro = new ResizeObserver(() => {
      const nearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 120
      if (nearBottom) el.scrollTop = el.scrollHeight
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const runId = useChatStore((s) => s.runId)

  if (messages.length === 0) {
    return <Welcome />
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto relative">
      {/* 拾光时刻（2026-08-29）：AI 回复完成的琥珀金波纹——从消息流底部扩散，
          一次回复=一次拾光；pointer-events-none 零交互干扰，动画结束自动卸载 */}
      {glintKey > 0 && (
        <div key={glintKey} className="glint-wrap pointer-events-none" aria-hidden>
          <span className="glint-ring" />
          <span className="glint-ring glint-ring-2" />
          <span className="glint-dot" />
        </div>
      )}
      {/* 对话列居中（720→860px：模型生成的图/图表不被压缩，2026-08-26 用户指出） */}
      <div className="max-w-[860px] mx-auto px-4 py-4 space-y-4">
        {runId && <TaskProgressCard runId={runId} />}
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} />
        ))}
      </div>
    </div>
  )
}
