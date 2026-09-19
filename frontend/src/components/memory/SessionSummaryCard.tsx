import { useCallback, useEffect, useState } from 'react'
import { fetchSessionSummary, type SessionSummary } from '../../api/memory'
import { useChatStore } from '../../store/chatStore'

/* 历史纪要（Phase 2 C-1 UI 入口，2026-08-29）：长会话早期历史被压缩成的四字段纪要。
   —— 用户拍板：可见（"它记得我"能看到拾光把早期对话压缩成了什么）
   —— 数据：GET /api/session/{sid}/summary；当前会话无纪要 → 整卡隐藏（不打扰）
   —— 语义：早期对话没丢，只是浓缩了；细节可让拾光翻原始记录 */
export default function SessionSummaryCard(): React.ReactElement | null {
  const sessionId = useChatStore((s) => s.sessionId)
  const [summary, setSummary] = useState<SessionSummary | null>(null)
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    if (!sessionId) {
      setLoaded(true)
      return
    }
    const s = await fetchSessionSummary(sessionId)
    setSummary(s)
    setLoaded(true)
  }, [sessionId])

  useEffect(() => {
    setLoaded(false)
    load()
  }, [load])

  if (!loaded) return null
  if (!summary) return null

  return (
    <div className="rounded-xl border border-hairline bg-surface/60 p-3.5">
      <div className="flex items-center gap-2">
        <span className="text-[12px] font-medium text-amber">历史纪要</span>
        <span className="text-[10px] text-ink-dim">
          {summary.covered_rounds > 0 ? `已浓缩早期 ${summary.covered_rounds} 条对话` : ''}
        </span>
      </div>
      <p className="mt-1 text-[11px] text-ink-muted leading-relaxed">
        早期对话的浓缩要点——内容没丢，只是精简了；想翻细节直接问拾光
      </p>
      {summary.goal && (
        <div className="mt-2.5">
          <p className="text-[10px] text-ink-dim">目标</p>
          <p className="text-[12px] text-ink-strong leading-relaxed">{summary.goal}</p>
        </div>
      )}
      {summary.decisions.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-ink-dim">已决定</p>
          <ul className="mt-0.5 space-y-0.5">
            {summary.decisions.map((d, i) => (
              <li key={i} className="text-[12px] text-ink-strong leading-relaxed">
                · {d}
              </li>
            ))}
          </ul>
        </div>
      )}
      {summary.open.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-ink-dim">未完成 / 卡住</p>
          <ul className="mt-0.5 space-y-0.5">
            {summary.open.map((o, i) => (
              <li key={i} className="text-[12px] text-ink-strong leading-relaxed">
                · {o}
              </li>
            ))}
          </ul>
        </div>
      )}
      {summary.entities.length > 0 && (
        <div className="mt-2">
          <p className="text-[10px] text-ink-dim">重要对象</p>
          <p className="mt-0.5 text-[12px] text-ink-strong leading-relaxed">{summary.entities.join('、')}</p>
        </div>
      )}
    </div>
  )
}
