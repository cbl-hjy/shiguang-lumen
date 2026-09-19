import { useCallback, useEffect, useState } from 'react'
import { demoteMemory, fetchMemoryStats, type MemoryStats } from '../../api/memory'

/* 记忆健康（Phase1 M-4 治理入口，2026-08-29）
   设计原则：讲人话（不堆术语）——用户关心的是"拾光记得准不准、哪些快忘了"，
   不是"半衰期/τ"这些内部参数（参数只在冷记忆详情里以hint形式出现）。
   数据：/api/memory/stats（访问统计 + 冷记忆预览，后端 Phase1 M-1/M-3 已就绪）。 */
export default function MemoryHealth({ entriesCount }: { entriesCount: number }) {
  const [stats, setStats] = useState<MemoryStats | null>(null)
  const [coldOpen, setColdOpen] = useState(false)

  const reload = useCallback(() => {
    fetchMemoryStats()
      .then(setStats)
      .catch(() => setStats(null))
  }, [])

  useEffect(reload, [reload])

  const usedCount = stats ? Object.keys(stats.stats || {}).filter((k) => k).length : 0
  const totalHits = stats
    ? Object.values(stats.stats || {}).reduce((a, v) => a + (v?.count || 0), 0)
    : 0
  const cold = stats?.cold_preview || []
  const rate = entriesCount > 0 ? Math.round((usedCount / entriesCount) * 100) : 0

  return (
    <div className="px-4 pb-6 space-y-3">
      {/* 三个指标卡：总数 / 被想起过 / 将要休眠 */}
      <div className="grid grid-cols-3 gap-2">
        <Metric label="星尘总数" value={entriesCount} hint="我记得的片段" />
        <Metric
          label="被想起过"
          value={usedCount}
          hint={totalHits > 0 ? `累计命中 ${totalHits} 次` : '还没有被检索到'}
        />
        <Metric
          label="将要休眠"
          value={cold.length}
          hint={cold.length > 0 ? '久未被想起' : '暂无'}
          tone={cold.length > 0 ? 'warn' : 'ok'}
        />
      </div>

      {/* 命中率条（讲人话：多少记忆是真的在用） */}
      <div className="rounded-xl border border-hairline bg-surface/60 p-3">
        <div className="flex items-baseline justify-between">
          <span className="text-[12px] text-ink">活跃度</span>
          <span className="text-[12px] text-ink-muted tabular-nums">{rate}%</span>
        </div>
        <div className="mt-2 h-1.5 rounded-full bg-white/5 overflow-hidden">
          <div
            className="h-full rounded-full bg-primary/70 transition-all duration-500"
            style={{ width: `${Math.max(2, Math.min(100, rate))}%` }}
          />
        </div>
        <p className="mt-2 text-[11px] text-ink-dim leading-relaxed">
          {rate >= 50
            ? '大部分记忆都还在被用到——说明我记的是对你有用的事。'
            : rate > 0
              ? '有一部分记忆很久没被想起来了，它们会慢慢休眠。'
              : '还没有积累到检索记录，聊得多了这里会有数据。'}
        </p>
      </div>

      {/* 冷记忆清单（折叠） */}
      {cold.length > 0 && (
        <div className="rounded-xl border border-hairline bg-surface/60 overflow-hidden">
          <button
            onClick={() => setColdOpen((v) => !v)}
            className="w-full flex items-center justify-between px-3 py-2.5 text-[12px] text-ink hover:bg-white/5 transition-colors"
          >
            <span>将要休眠的记忆（{cold.length}）</span>
            <span className="text-ink-dim text-[11px]">{coldOpen ? '收起' : '展开'}</span>
          </button>
          {coldOpen && (
            <ul className="border-t border-hairline divide-y divide-white/5">
              {cold.map((c) => (
                <li key={c.id} className="px-3 py-2.5 flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-[12px] text-ink-muted leading-snug">{c.content}</p>
                    <p className="mt-1 text-[10px] text-ink-dim">
                      {c.category} · {c.age_days} 天未被想起
                    </p>
                  </div>
                  <button
                    onClick={async () => {
                      const ok = await demoteMemory(c.content)
                      if (ok) reload()
                    }}
                    className="shrink-0 px-2 py-1 rounded-md border border-hairline text-[10px] text-ink-dim hover:text-amber hover:border-amber/40 hover:bg-amber/5 transition-colors duration-150 active:scale-95"
                    title="让它休眠：不再主动浮现，文件保留可找回"
                  >
                    休眠
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="px-3 py-2 text-[10px] text-ink-dim leading-relaxed border-t border-hairline">
            休眠 = 不再主动浮现在对话里（不是删除）。哪天你重新提起，它会立刻醒来。
          </p>
        </div>
      )}

      {stats?.error && (
        <p className="text-[11px] text-ink-dim">统计暂不可用：{stats.error}</p>
      )}
    </div>
  )
}

function Metric({
  label,
  value,
  hint,
  tone = 'ok',
}: {
  label: string
  value: number
  hint: string
  tone?: 'ok' | 'warn'
}) {
  return (
    <div className="rounded-xl border border-hairline bg-surface/60 p-3">
      <div
        className={`text-[18px] font-medium tabular-nums ${
          tone === 'warn' ? 'text-amber-300/90' : 'text-ink'
        }`}
      >
        {value}
      </div>
      <div className="mt-0.5 text-[10px] text-ink-muted">{label}</div>
      <div className="mt-1 text-[10px] text-ink-dim leading-tight">{hint}</div>
    </div>
  )
}
