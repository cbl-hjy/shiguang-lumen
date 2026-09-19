/* 用量面板（2026-08-28 UX 优化 D8）：月度/今日 token 消耗 + 缓存命中率
   数据源：/api/observability/summary（后端 token_usage.csv 聚合，只读） */
import { useEffect, useState } from 'react'

interface TokenAgg {
  by_day?: Record<string, number>
  total?: number
  cache_read?: number
  [k: string]: unknown
}

export default function UsagePanel() {
  const [data, setData] = useState<TokenAgg | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    fetch('/api/observability/summary')
      .then((r) => r.json())
      .then((d) => setData(d.token || {}))
      .catch(() => setErr('用量读取失败'))
  }, [])

  if (err) return <p className="text-[12px] text-error">{err}</p>
  if (!data) {
    return (
      <div className="py-6">
        <div className="skeleton h-3.5 w-3/4 mb-2.5" />
        <div className="skeleton h-3.5 w-1/2" />
      </div>
    )
  }

  const byDay = (data.by_day as Record<string, number>) || {}
  const days = Object.entries(byDay).sort((a, b) => (a[0] < b[0] ? 1 : -1))
  const total = days.reduce((s, [, v]) => s + v, 0)
  const today = days.find(([d]) => d === new Date().toISOString().slice(0, 10))?.[1] || 0
  const cacheRead = Number(data.cache_read || 0)
  const cacheRate = total > 0 ? ((cacheRead / total) * 100).toFixed(0) : '—'

  return (
    <div>
      <div className="grid grid-cols-3 gap-2 mb-3">
        <div className="rounded-xl border border-hairline bg-elevated p-3 text-center">
          <div className="text-[18px] font-semibold text-primary">{(total / 10000).toFixed(1)}万</div>
          <div className="text-[11px] text-ink-dim mt-0.5">累计 Token</div>
        </div>
        <div className="rounded-xl border border-hairline bg-elevated p-3 text-center">
          <div className="text-[18px] font-semibold text-amber">{(today / 10000).toFixed(1)}万</div>
          <div className="text-[11px] text-ink-dim mt-0.5">今天</div>
        </div>
        <div className="rounded-xl border border-hairline bg-elevated p-3 text-center">
          <div className="text-[18px] font-semibold text-success">{cacheRate}%</div>
          <div className="text-[11px] text-ink-dim mt-0.5">缓存命中</div>
        </div>
      </div>
      <div className="space-y-1.5">
        {days.slice(0, 14).map(([d, v]) => (
          <div key={d} className="flex items-center gap-2 text-[12px]">
            <span className="w-[80px] shrink-0 text-ink-dim">{d.slice(5)}</span>
            <div className="flex-1 h-2 rounded-full bg-elevated overflow-hidden">
              <div
                className="h-full rounded-full bg-[linear-gradient(90deg,rgba(62,201,176,.5),rgba(230,190,120,.8))]"
                style={{ width: `${Math.max(4, (v / (days[0]?.[1] || 1)) * 100)}%` }}
              />
            </div>
            <span className="w-[70px] text-right text-ink-dim">{(v / 10000).toFixed(1)}万</span>
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] text-ink-dim/70">数据来自后端 token 台账（只读，不含外部模型费用估算）</p>
    </div>
  )
}
