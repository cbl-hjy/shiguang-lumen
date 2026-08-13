import { useEffect, useState } from 'react'
import { fetchProgress, type ProgressData } from '../../api/progress'
import LearningPath from './LearningPath'
import ProgressRing from './ProgressRing'
import StreakBadge from './StreakBadge'
import MemoryPanel from '../memory/MemoryPanel'

/* 左栏（布局重构）：tab 切换 学习路径 / 记忆（记忆面板复用，右栏腾给会话树） */
type Tab = 'path' | 'memory'

export default function PathPanel() {
  const [data, setData] = useState<ProgressData | null>(null)
  const [tab, setTab] = useState<Tab>('path')

  useEffect(() => {
    fetchProgress()
      .then(setData)
      .catch(() => setData(null))
  }, [])

  return (
    <aside className="w-80 shrink-0 border-r border-hairline flex flex-col min-h-0 h-full">
      <div className="shrink-0 flex items-center gap-1 px-3 pt-3 pb-2 border-b border-hairline">
        {(
          [
            ['path', '学习路径'],
            ['memory', '记忆'],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`flex-1 py-1.5 rounded-lg text-[12px] transition-colors duration-150 ${
              tab === k ? 'bg-primary/10 text-primary' : 'text-[rgba(236,233,225,0.5)] hover:text-[rgba(236,233,225,0.85)]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'path' ? (
          <div className="p-4 flex flex-col gap-4">
            <h2 className="text-[13px] font-medium text-[rgba(236,233,225,0.9)]">学习路径</h2>
            <LearningPath topics={data?.topics ?? []} />
            <div className="border-t border-hairline pt-4">
              <h3 className="text-[12px] font-medium text-[rgba(236,233,225,0.6)] mb-3">今日进度</h3>
              <div className="flex justify-center mb-3">
                {/* 诚实空态：进度数据需学习日志支撑（M6 接入），无数据不虚构 */}
                <ProgressRing value={null} label="本周目标（待记录）" />
              </div>
              <StreakBadge streak={data?.streak ?? null} />
            </div>
          </div>
        ) : (
          <MemoryPanel />
        )}
      </div>
    </aside>
  )
}
