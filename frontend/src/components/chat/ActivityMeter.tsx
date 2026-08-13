import { useEffect, useRef, useState } from 'react'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'

/* 活动仪表（输入框上方）：流式期间"它在干嘛"的实时信号——
   thinking 期：思考中…；工具执行期：正在执行 X + 已跑 Ns + 已发起 N 步；
   文本流开始（delta 流出）即收起（用户读内容本身就是活着的反馈）。
   纯前端 store 派生，零后端改动。诚实边界：工具失败信号后端暂不可得，
   >30s 未完成标 ⚠️（不假装 ✗），待后端有失败事件再补。 */
const SLOW_MS = 30_000

export default function ActivityMeter() {
  const messages = useChatStore((s) => s.messages)
  const streaming = useChatStore((s) => s.streaming)
  const [, tick] = useState(0)
  const startTs = useRef<Record<string, number>>({})

  /* 最后一条未完成的 assistant 消息 */
  const bot = [...messages].reverse().find((m) => m.role === 'assistant' && !m.done)

  /* 计时器：有活跃工具（start 未 done）才跑，每秒重渲染刷新 elapsed */
  const active = bot?.toolCalls.find((t) => t.status === 'start')
  useEffect(() => {
    if (!streaming || !active) return
    if (!startTs.current[active.id ?? active.name]) {
      startTs.current[active.id ?? active.name] = Date.now()
    }
    const t = setInterval(() => tick((n) => n + 1), 1000)
    return () => clearInterval(t)
  }, [streaming, active?.id, active?.name])

  if (!streaming || !bot) return null
  /* 文本流开始 → 收起（读内容 = 活着的反馈）；但若有活跃工具（start 未 done）必须持续显示——
     模型常先输出引导语（"好的，我来…"）再调工具，若此时收起，工具执行期又回到"只有转圈" */
  if (bot.content.length > 0 && !active) return null

  const started = bot.toolCalls.filter((t) => t.status === 'start').length
  const doneCount = bot.toolCalls.filter((t) => t.status === 'done').length
  const thinking = !active && bot.thinking.length > 0
  const elapsedMs = active ? Date.now() - (startTs.current[active.id ?? active.name] ?? Date.now()) : 0
  const slow = active && elapsedMs > SLOW_MS

  return (
    <div className="mx-4 mb-1.5 px-3 py-1.5 rounded-lg bg-surface border border-hairline text-[12px] flex items-center gap-2 animate-fade-in">
      {active ? (
        <>
          <Icon name="loader" size={13} className="text-primary animate-spin shrink-0" />
          <span className="text-[rgba(236,233,225,0.75)]">
            正在执行 <span className="text-primary">{active.name}</span>
          </span>
          <span className="text-[rgba(236,233,225,0.4)] tabular-nums">已跑 {(elapsedMs / 1000).toFixed(0)}s</span>
          {slow && (
            <span className="text-[rgba(236,233,225,0.45)]">⚠️ 这一步比较慢，还在跑</span>
          )}
          <span className="ml-auto text-[rgba(236,233,225,0.35)] tabular-nums">
            已发起 {started} 步 · {doneCount > 0 ? `完成 ${doneCount}` : '进行中'}
          </span>
        </>
      ) : thinking ? (
        <>
          <Icon name="loader" size={13} className="text-[rgba(236,233,225,0.5)] animate-spin shrink-0" />
          <span className="text-[rgba(236,233,225,0.55)]">思考中…</span>
        </>
      ) : null}
    </div>
  )
}
