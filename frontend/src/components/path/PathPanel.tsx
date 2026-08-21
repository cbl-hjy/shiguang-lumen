import { useEffect, useMemo, useState } from 'react'
import { fetchProgress, type ProgressData, type Topic } from '../../api/progress'
import LearningPath from './LearningPath'
import MemoryPanel from '../memory/MemoryPanel'
import Icon from '../ui/Icon'
import { useUiStore, type PanelTab } from '../../store/uiStore'

/* 左栏（设计系统定稿 Phase 4：IA 重构——信息分层）
   结构：tab（星图/星尘）+ 路径页顶部"领航"卡片（续接点=星轨唤醒语义，对应北极星"一起学"）
   - 领航推导：有续接点的主题里，卡住 > 进行中 > 搁置，同优先级取最近活动——"现在最该继续的"
   - 今日进度（ProgressRing/StreakBadge）熄星：数字统计非核心资产，主题状态才是（定稿删减清单）
   tab 受控于全局 uiStore.panelTab（命令面板跨端生效） */
export default function PathPanel() {
  const [data, setData] = useState<ProgressData | null>(null)
  const tab = useUiStore((s) => s.panelTab)
  const setTab = useUiStore((s) => s.setPanelTab)

  const reload = () => {
    fetchProgress()
      .then(setData)
      .catch(() => setData(null))
  }

  useEffect(() => {
    reload()
  }, [])

  /* 领航卡片：续接点优先（星轨唤醒——搁置主题不主动提，卡住/进行中的续接点才是"领航"） */
  const nextTopic = useMemo<{ topic: Topic; cont: string } | null>(() => {
    const withCont = (data?.topics ?? []).filter(
      (t) => t.continuation?.text && !t.continuation.abandoned,
    )
    if (!withCont.length) return null
    const priority: Record<string, number> = { 卡住: 0, 进行中: 1, 搁置: 2, 完成: 3 }
    const best = [...withCont].sort((a, b) => {
      const pa = priority[a.status] ?? 9
      const pb = priority[b.status] ?? 9
      if (pa !== pb) return pa - pb
      return (b.last_active || '').localeCompare(a.last_active || '')
    })[0]
    return { topic: best, cont: best.continuation!.text }
  }, [data])

  return (
    <aside className="w-84 shrink-0 border-r border-hairline flex flex-col min-h-0 h-full">
      <div className="shrink-0 flex items-center gap-1 px-3 pt-3 pb-2 border-b border-hairline">
        {(
          [
            ['path', '星图'],
            ['memory', '星尘'],
          ] as [PanelTab, string][]
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`flex-1 py-1.5 rounded-lg text-[12px] transition-colors duration-150 ${
              tab === k ? 'bg-primary/10 text-primary' : 'text-ink-dim hover:text-ink/90'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto">
        {tab === 'path' ? (
          <div className="p-4 flex flex-col gap-4">
            {/* 容量横幅（治理权#4，2026-08-19）：星尘 ≥ 软阈值提示整理——用户可见，不只提示模型 */}
            {data?.stats.total != null && data?.memory_soft_limit && data.stats.total >= data.memory_soft_limit && (
              <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2">
                <div className="text-[12px] text-warning leading-relaxed">
                  星尘已达 {data.stats.total}/{data.memory_soft_limit} 条软阈值——建议整理：
                  在星尘删去过时条目或合并重复内容。
                </div>
              </div>
            )}
            {/* 领航（定稿 IA：学习仪表盘像 to-do 不像报告——最该做的事置顶，北极星图标=导航语义） */}
            {nextTopic && (
              <div className="rounded-lg border border-primary/25 bg-primary/5 px-3 py-2.5 glow-primary">
                <div className="flex items-center gap-2 mb-1">
                  <Icon name="north" size={14} className="text-primary" />
                  <span className="text-[12px] font-medium text-primary">
                    领航 · {nextTopic.topic.name}
                  </span>
                </div>
                <div className="text-[13px] text-ink/90 leading-relaxed line-clamp-2">
                  {nextTopic.cont}
                </div>
              </div>
            )}
            <h2 className="text-[13px] font-medium text-ink">星图</h2>
            <LearningPath topics={data?.topics ?? []} onChanged={reload} />
          </div>
        ) : (
          <MemoryPanel />
        )}
      </div>
    </aside>
  )
}
