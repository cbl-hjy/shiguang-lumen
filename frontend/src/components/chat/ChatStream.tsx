import { useEffect, useRef } from 'react'
import type { ChatMessage } from '../../types/chat'
import MessageBubble from './MessageBubble'
import TaskProgressCard from './TaskProgressCard'
import Welcome from './Welcome'
import { useChatStore } from '../../store/chatStore'

/* 消息流：自动滚动 + 新消息淡入 + 空状态欢迎语（画像拼接）+ M7 并行任务进度卡 */
export default function ChatStream({ messages }: { messages: ChatMessage[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)

  /* 滚动容器自身（不依赖 scrollIntoView 找祖先——body overflow:hidden 下可能滚错） */
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [messages])

  const runId = useChatStore((s) => s.runId)

  if (messages.length === 0) {
    return <Welcome />
  }

  return (
    <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto p-4">
      {runId && <TaskProgressCard runId={runId} />}
      {messages.map((m) => (
        <MessageBubble key={m.id} msg={m} />
      ))}
    </div>
  )
}
