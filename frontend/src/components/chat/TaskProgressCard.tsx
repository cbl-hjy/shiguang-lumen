import { useEffect, useState } from 'react'
import { fetchTaskProgress } from '../../api/tasks'
import Icon from '../ui/Icon'

/* M7 任务进度卡：子任务并行时逐项点亮（父流看不到子 agent 事件，靠 /api/tasks 轮询）
   状态：pending(灰) → done(teal ✓) / failed(红 !)；全部结束自动淡出 */
const STATUS_META: Record<string, { icon: 'check' | 'x' | 'chevron-right'; cls: string }> = {
  done: { icon: 'check', cls: 'text-primary' },
  failed: { icon: 'x', cls: 'text-error' },
  pending: { icon: 'chevron-right', cls: 'text-ink-dim/70' },
}

export default function TaskProgressCard({ runId }: { runId: string }) {
  const [tasks, setTasks] = useState<Record<string, string> | null>(null)

  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setInterval>
    const poll = async () => {
      try {
        const p = await fetchTaskProgress(runId)
        if (cancelled) return
        if (!p) return
        setTasks(p.tasks)
        const values = Object.values(p.tasks)
        const allDone = values.every((v) => v === 'done' || v === 'failed')
        if (allDone) clearInterval(timer)
      } catch {
        /* 轮询失败忽略 */
      }
    }
    poll()
    timer = setInterval(poll, 1000)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [runId])

  if (!tasks) return null
  const entries = Object.entries(tasks)
  if (entries.length === 0) return null
  const doneCount = entries.filter(([, v]) => v === 'done' || v === 'failed').length
  const allDone = doneCount === entries.length

  return (
    <div
      className={`mx-4 mb-2 rounded-xl border border-hairline bg-surface overflow-hidden transition-opacity duration-300 ${
        allDone ? 'opacity-40' : ''
      }`}
      aria-label="并行任务进度"
    >
      <div className="flex items-center justify-between px-3 py-2 border-b border-hairline">
        <span className="text-[12px] font-medium text-ink/90">
          并行研究中
        </span>
        <span className="text-[11px] text-ink-dim">
          {doneCount}/{entries.length}
        </span>
      </div>
      <div className="px-3 py-2 flex flex-col gap-1.5">
        {entries.map(([name, status]) => {
          const meta = STATUS_META[status] ?? STATUS_META.pending
          return (
            <div key={name} className="flex items-center gap-2 text-[12px]">
              <Icon name={meta.icon} size={13} className={`shrink-0 ${meta.cls}`} />
              <span
                className={`truncate ${
                  status === 'done' || status === 'failed'
                    ? 'text-ink/80'
                    : 'text-ink-dim'
                }`}
                title={name}
              >
                {name}
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
