// 从 StarMap.tsx 纯移动切割（Phase 4 A-1，2026-08-29）——零逻辑改动，仅搬家 + import 修正
import { type InjectionRecord, type ObsMemory, type ObsRun, type ObsSession, type ObsSummary, type ObsTraceEvent, fetchCapabilities, fetchInjection, fetchMastery, fetchObsMemory, fetchObsSessions, fetchSessionRuns, fetchSummary, fetchTrace } from '../../api/obs'
import Icon from '../ui/Icon'
import { ObsCapabilitiesBoard } from './capabilities'
import { Loading, arr, fCard, fTitle, useFetch } from './shared'
import { type ReactNode, useEffect, useState } from 'react'

export type ObsModule = null | 'calls' | 'token' | 'errors' | 'memory' | 'injection' | 'replay' | 'mastery' | 'capabilities'

export const fmtMs = (ms: number) => (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`)
export const fmtN = (n: number) => (n >= 10000 ? `${(n / 10000).toFixed(1)}w` : n.toLocaleString())

export function ObsBack({
  label,
  onBack,
  children,
}: {
  label: string
  onBack: () => void
  children: ReactNode
}) {
  return (
    <div className="space-y-4">
      <button
        onClick={onBack}
        className="flex items-center gap-1.5 text-[12px] text-ink-dim hover:text-amber transition-colors duration-150"
      >
        <Icon name='arrow-left' size={14} /> {label}
      </button>
      {children}
    </div>
  )
}

/* —— 模块：调用分析（LLM + 工具） —— */
export function ObsCalls({ d }: { d: ObsSummary }) {
  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='activity' size={14} /> LLM 调用（tag · 次数 · 成功率 · 平均耗时）
        </div>
        {d.trace.llm_stats.length === 0 && (
          <p className="text-[12px] text-ink-dim">暂无 LLM trace</p>
        )}
        <div className="space-y-1.5">
          {d.trace.llm_stats.map((l) => (
            <div
              key={l.tag}
              className="flex items-center gap-3 text-[12px] border-b border-hairline/30 last:border-0 pb-1.5 last:pb-0"
            >
              <span className="w-20 shrink-0 font-mono text-ink/85">{l.tag}</span>
              <span className="text-ink-dim">{l.calls} 次</span>
              <span className={l.success_rate >= 90 ? 'text-primary' : 'text-amber'}>
                {l.success_rate}%
              </span>
              <span className="text-ink-dim/70 font-mono">{fmtMs(l.avg_ms)}</span>
              {l.unfinished > 0 && (
                <span className="text-[10px] text-ink-dim/60">未配对 {l.unfinished}</span>
              )}
            </div>
          ))}
        </div>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='activity' size={14} /> 工具调用 Top（次数 · 成功率 · 平均耗时）
        </div>
        {d.trace.tool_stats.length === 0 && (
          <p className="text-[12px] text-ink-dim">暂无工具调用</p>
        )}
        <div className="space-y-1.5">
          {d.trace.tool_stats.slice(0, 12).map((t) => (
            <div
              key={t.name}
              className="flex items-center gap-3 text-[12px] border-b border-hairline/30 last:border-0 pb-1.5 last:pb-0"
            >
              <span className="w-32 shrink-0 truncate text-ink/85">{t.name}</span>
              <span className="text-ink-dim">{t.calls} 次</span>
              <span className={t.success_rate >= 90 ? 'text-primary' : 'text-amber'}>
                {t.success_rate}%
              </span>
              <span className="text-ink-dim/70 font-mono">{fmtMs(t.avg_ms)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* —— 模块：Token 趋势（含缓存命中率——2026-08-26 P0-2 观测，用户点名"下午做的命中率呢"） —— */
export function ObsToken({ d }: { d: ObsSummary }) {
  const days = d.token.by_day
  const max = Math.max(1, ...days.map((x) => x.tokens))
  const cache = d.token.cache
  const hit = cache?.hit_ratio ?? null
  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='trending-up' size={14} /> Token 消耗趋势（近 14 天）
        </div>
        <div className="text-[12px] text-ink-dim mb-1">
          合计 <span className="text-primary font-mono">{fmtN(d.token.total)}</span>
          <span className="text-ink-dim/60"> · 单位：字符 · 柱子越高当日消耗越多</span>
        </div>
        {days.length === 0 && (
          <p className="text-[12px] text-ink-dim">暂无 token 记录（对话会产生）</p>
        )}
        <div className="flex items-end gap-1.5 h-28 mt-2">
          {days.map((bd) => (
            <div
              key={bd.date}
              className="flex-1 flex flex-col items-center gap-1"
              title={`${bd.date}: ${bd.tokens}`}
            >
              <div
                className="w-full rounded-t bg-gradient-to-t from-primary/30 to-primary/70 hover:to-primary transition-colors duration-150"
                style={{ height: `${Math.max(4, (bd.tokens / max) * 84)}px` }}
              />
              <span className="text-[8px] text-ink-dim/60 font-mono">{bd.date.slice(5)}</span>
            </div>
          ))}
        </div>
        {Object.keys(d.token.by_role).length > 0 && (
          <div className="flex flex-wrap gap-2 mt-3">
            {Object.entries(d.token.by_role).map(([role, n]) => (
              <span
                key={role}
                className="px-2 py-1 rounded-full border border-primary/25 bg-primary/8 text-[11px] text-primary/90 font-mono"
              >
                {role} {fmtN(n)}
              </span>
            ))}
          </div>
        )}
      </div>

      {/* 缓存命中率（下午 P0-2 观测的展示落地） */}
      <div className={`${fCard} border-primary/25`}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <div className={`${fTitle} text-primary`}>
              <Icon name='activity' size={14} /> 前缀缓存命中率
            </div>
            <p className="text-[11.5px] text-ink-dim leading-relaxed mt-1">
              DeepSeek 上下文缓存：多轮对话时历史前缀直接命中，命中部分按 ~3% 计费（省 ~97%
              输入成本）。
              {hit === null && ' 当前台账暂无缓存记录（新格式从 08-26 起积累）。'}
            </p>
          </div>
          <div className="shrink-0 text-right">
            <div
              className={`text-[26px] font-mono leading-none ${hit !== null && hit >= 80 ? 'text-primary' : 'text-amber'}`}
            >
              {hit !== null ? `${hit}%` : '—'}
            </div>
            <div className="text-[10px] text-ink-dim mt-1">命中 / 输入</div>
          </div>
        </div>
        {cache && (cache.read > 0 || cache.write > 0) && (
          <div className="flex flex-wrap gap-2 mt-3 text-[12px]">
            <span className="px-2.5 py-1 rounded-full border border-primary/25 bg-primary/8 text-primary/90 font-mono">
              命中 {fmtN(cache.read)}
            </span>
            <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
              写入 {fmtN(cache.write)}
            </span>
            <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-dim">
              按 DeepSeek 缓存折扣估算省约{' '}
              <span className="text-primary font-mono">{(cache.read * 0.97).toLocaleString()}</span>{' '}
              字符输入成本
            </span>
          </div>
        )}
        {cache && cache.by_day.some((x) => x.read > 0) && (
          <>
            <div className="text-[11px] text-ink-dim mt-3 mb-1">每日命中 token</div>
            <div className="flex items-end gap-1 h-12">
              {cache.by_day.map((bd, i) => (
                <div
                  key={i}
                  className="flex-1 rounded-t bg-amber/40 hover:bg-amber/70 transition-colors duration-150"
                  style={{
                    height: `${Math.max(3, (bd.read / Math.max(1, ...cache.by_day.map((x) => x.read))) * 36)}px`,
                  }}
                  title={`${bd.date}: ${bd.read}`}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* —— 模块：错误 —— */
export function ObsErrors({ d }: { d: ObsSummary }) {
  const total = Object.values(d.trace.errors).reduce((a, b) => a + b, 0)
  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-[#e8a58c]`}>
          <Icon name='alert' size={14} /> 错误分布 · {total}
        </div>
        {Object.keys(d.trace.errors).length === 0 && (
          <p className="text-[12px] text-ink-dim">暂无错误</p>
        )}
        <div className="space-y-1.5">
          {Object.entries(d.trace.errors)
            .slice(0, 12)
            .map(([where, n]) => (
              <div
                key={where}
                className="flex items-center gap-2 text-[12px] border-b border-hairline/30 last:border-0 pb-1.5 last:pb-0"
              >
                <span className="flex-1 truncate text-ink/85">{where}</span>
                <span className="text-[#e8a58c] font-mono">{n}</span>
              </div>
            ))}
        </div>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-ink-muted`}>
          <Icon name='activity' size={14} /> 完整性
        </div>
        <div className="flex flex-wrap gap-2 text-[12px]">
          <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
            {d.integrity.events} 事件
          </span>
          <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
            {d.integrity.corrupt_lines} 损坏行
          </span>
          <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
            {d.integrity.write_fails} 写失败
          </span>
          <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
            {d.integrity.runs_started}→{d.integrity.runs_ended} runs
          </span>
        </div>
      </div>
    </div>
  )
}

/* —— 模块：记忆健康 —— */
export function ObsMemoryM({ mem }: { mem: { data: ObsMemory | null; err: string | null } }) {
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-amber`}>
        <Icon name='sparkles' size={14} /> 记忆健康
      </div>
      {mem.err && <p className="text-[12px] text-ink-dim">读取失败（{mem.err}）</p>}
      {!mem.data && !mem.err && <Loading />}
      {mem.data && (
        <>
          <div className="flex flex-wrap gap-2 text-[12px] mb-3">
            <span className="px-2.5 py-1 rounded-full border border-primary/25 bg-primary/8 text-primary/90">
              条目 {mem.data.entries}
            </span>
            <span className="px-2.5 py-1 rounded-full border border-amber/25 bg-amber/8 text-amber/90">
              画像 {fmtN(mem.data.profile_chars)} 字
            </span>
            {mem.data.last_updated && (
              <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-dim font-mono">
                {mem.data.last_updated}
              </span>
            )}
          </div>
          <div className="text-[11px] text-ink-dim mb-1.5">类别分布</div>
          {Object.keys(mem.data.categories).length === 0 && (
            <p className="text-[12px] text-ink-dim">暂无类别</p>
          )}
          <div className="flex flex-wrap gap-2">
            {Object.entries(mem.data.categories).map(([c, n]) => (
              <span
                key={c}
                className="px-2.5 py-1 rounded-full border border-hairline/60 text-ink-muted text-[11.5px]"
              >
                {c} <span className="text-ink-dim font-mono">{n}</span>
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* —— 模块：注入审计（表格视图——用户批评柱状图看不懂，改为可读表格+横向条+解释） —— */
export function ObsInjection({
  inj,
}: {
  inj: { data: { records: InjectionRecord[]; count: number } | null; err: string | null }
}) {
  const records = inj.data?.records ?? []
  const max = Math.max(1, ...records.map((r) => r.total))
  const latest = records.length ? records[records.length - 1] : null
  const prev = records.length > 1 ? records[records.length - 2] : null
  const trend =
    latest && prev
      ? latest.total > prev.total
        ? 'up'
        : latest.total < prev.total
          ? 'down'
          : 'flat'
      : null
  const show = records.slice(-15).reverse() /* 最新在上 */
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-primary`}>
        <Icon name='activity' size={14} /> 注入审计
      </div>
      <p className="text-[11.5px] text-ink-dim leading-relaxed mb-3">
        每轮对话时注入给模型的上下文预算（字符）。total = 当轮注入总量，越小越省 token。
        <span className="text-ink-muted">
          {' '}
          注：此为本环节注入量，与「Token 趋势」的 API 实际消耗是两本账。
        </span>
        {latest && (
          <span className="text-ink-muted">
            {' '}
            最新 total <span className="text-primary font-mono">{latest.total}</span>
            {trend === 'up' && <span className="text-amber"> ↑（较上轮增）</span>}
            {trend === 'down' && <span className="text-primary"> ↓（较上轮减）</span>}
            {trend === 'flat' && <span> →（持平）</span>}
          </span>
        )}
      </p>
      {inj.err && <p className="text-[12px] text-ink-dim">读取失败（{inj.err}）</p>}
      {!inj.data && !inj.err && <Loading />}
      {inj.data && (
        <>
          {records.length === 0 && (
            <p className="text-[12px] text-ink-dim">暂无注入记录——对话时会自动记录</p>
          )}
          <div className="space-y-2">
            {show.map((r, i) => (
              <div key={i} className="flex items-center gap-3 text-[11.5px]">
                <span className="w-20 shrink-0 font-mono text-ink-dim/70">
                  {r.time?.slice(11, 19)}
                </span>
                <div className="flex-1 h-[9px] rounded-full bg-surface border border-hairline/50 overflow-hidden">
                  <div
                    className="h-full rounded-full bg-gradient-to-r from-primary/40 to-primary/80"
                    style={{ width: `${(r.total / max) * 100}%` }}
                  />
                </div>
                <span className="w-16 shrink-0 text-right font-mono text-ink/85">{r.total}</span>
                <span className="w-14 shrink-0 text-right text-[10px] text-ink-dim/70 font-mono">
                  state {r.state}
                </span>
              </div>
            ))}
          </div>
          {records.length > 15 && (
            <p className="text-[10px] text-ink-dim/60 mt-2">
              近 15 条 · 共 {records.length} 条记录
            </p>
          )}
        </>
      )}
    </div>
  )
}

/* —— 模块：会话重放 —— */
export function ObsReplay({
  sessions,
}: {
  sessions: { data: { sessions: ObsSession[] } | null; err: string | null; reload?: () => void }
}) {
  useEffect(() => {
    sessions.reload?.()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  const [sid, setSid] = useState<string | null>(null)
  const [runs, setRuns] = useState<ObsRun[] | null>(null)
  const [runId, setRunId] = useState<string | null>(null)
  const [trace, setTrace] = useState<ObsTraceEvent[] | null>(null)
  const [busy, setBusy] = useState(false)

  const openSession = async (s: string) => {
    setSid(s)
    setRuns(null)
    setRunId(null)
    setTrace(null)
    setBusy(true)
    try {
      setRuns((await fetchSessionRuns(s)).runs)
    } finally {
      setBusy(false)
    }
  }

  const openTrace = async (rid: string) => {
    setRunId(rid)
    setTrace(null)
    setBusy(true)
    try {
      setTrace((await fetchTrace(rid)).events)
    } finally {
      setBusy(false)
    }
  }

  if (sid) {
    return (
      <ObsBack label="会话重放" onBack={() => setSid(null)}>
        <div className={fCard}>
          <div className={`${fTitle} text-amber`}>
            <Icon name='history' size={14} /> run 列表 · {runs ? runs.length : '…'}
          </div>
          {busy && !runs && <Loading />}
          {runs && runs.length === 0 && (
            <p className="text-[12px] text-ink-dim">该会话无 trace 记录</p>
          )}
          <div className="space-y-1.5">
            {runs?.map((r) => (
              <div key={r.run_id}>
                <button
                  onClick={() => openTrace(r.run_id)}
                  className={`w-full text-left px-3 py-2 rounded-lg border text-[12px] transition-colors duration-150 ${
                    runId === r.run_id
                      ? 'border-amber/40 bg-surface/60 text-amber'
                      : 'border-hairline/60 text-ink/80 hover:border-primary/40'
                  }`}
                >
                  <span className="font-mono text-[11px] text-ink-dim">{r.run_id.slice(0, 8)}</span>
                  <span className="ml-2">{r.text || '(无摘要)'}</span>
                  <span className="float-right text-[10px] text-ink-dim/70 font-mono">
                    {r.ts?.slice(11, 19)}
                  </span>
                </button>
                {runId === r.run_id && (
                  <div className="mt-1.5 rounded-lg border border-hairline/50 bg-surface/30 overflow-hidden">
                    {busy && !trace && <Loading />}
                    {trace && trace.length === 0 && (
                      <p className="text-[11px] text-ink-dim p-2.5">无事件</p>
                    )}
                    {trace?.map((t, i) => (
                      <div
                        key={i}
                        className="flex flex-wrap items-center gap-2 px-3 py-1.5 text-[11px] border-b border-hairline/30 last:border-0"
                      >
                        <span className="font-mono text-ink-dim/60">{t.ts?.slice(11, 19)}</span>
                        <span className="text-primary/80">{t.type}</span>
                        {t.name && <span className="text-ink/80">{t.name}</span>}
                        {t.status && (
                          <span
                            className={
                              t.status === 'ok'
                                ? 'text-primary'
                                : t.status === 'err' || t.status === 'error'
                                  ? 'text-[#e8a58c]'
                                  : 'text-ink-dim'
                            }
                          >
                            {t.status}
                          </span>
                        )}
                        {typeof t.dur_ms === 'number' && (
                          <span className="text-ink-dim/70 font-mono">{fmtMs(t.dur_ms)}</span>
                        )}
                        {t.detail && (
                          <span className="text-ink-dim truncate max-w-[320px]">{t.detail}</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </ObsBack>
    )
  }

  return (
    <div className={fCard}>
      <div className={`${fTitle} text-amber`}>
        <Icon name='history' size={14} /> 会话列表（trace-driven debugging · 点会话看 run）
      </div>
      {sessions.err && <p className="text-[12px] text-ink-dim">读取失败（{sessions.err}）</p>}
      {!sessions.data && !sessions.err && <Loading />}
      <div className="space-y-1.5">
        {sessions.data?.sessions.map((sess) => (
          <button
            key={sess.id}
            onClick={() => openSession(sess.id)}
            className="w-full text-left px-3 py-2 rounded-lg border border-hairline/50 hover:border-amber/30 transition-colors duration-150"
          >
            <div className="flex items-center gap-2 text-[12.5px]">
              <span className="flex-1 truncate text-ink/85">{sess.title || '(无标题)'}</span>
              {sess.traces > 0 && (
                <span className="px-1.5 py-0.5 rounded-md bg-primary/10 text-primary text-[10px]">
                  {sess.traces} runs
                </span>
              )}
              <span className="text-[10px] text-ink-dim/70 font-mono">
                {sess.created_at?.slice(0, 16)}
              </span>
            </div>
            {sess.summary && (
              <div className="text-[11px] text-ink-dim truncate mt-0.5">{sess.summary}</div>
            )}
          </button>
        ))}
      </div>
    </div>
  )
}

/* —— 观测台主体：概览页 —— */
export function ObservatoryFeature() {
  const [module, setModule] = useState<ObsModule>(null)
  const sum = useFetch(fetchSummary, "obssum")
  const mem = useFetch(fetchObsMemory, "obsmem")
  const inj = useFetch(fetchInjection, "obsinj")
  const sessions = useFetch(fetchObsSessions, "obssessions")
  const mastery = useFetch(fetchMastery, "mastery") // B1 掌握台账（懒加载：进模块才拉）
  const cap = useFetch(fetchCapabilities, "obscap") // 评估体系 v1 能力仪表盘（2026-08-31）

  /* 进模块自动刷新对应数据（2026-08-26：保证看的是最新） */
  useEffect(() => {
    if (module === 'memory') mem.reload()
    if (module === 'injection') inj.reload()
    if (module === 'replay') sessions.reload()
    if (module === 'mastery') mastery.reload()
    if (module === 'capabilities') cap.reload()
    if (module === 'calls' || module === 'token' || module === 'errors') sum.reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [module])

  if (module === 'calls') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        {sum.data ? (
          <ObsCalls d={sum.data} />
        ) : sum.err ? (
          <p className="text-[12px] text-ink-dim">读取失败（{sum.err}）</p>
        ) : (
          <Loading />
        )}
      </ObsBack>
    )
  }
  if (module === 'token') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        {sum.data ? (
          <ObsToken d={sum.data} />
        ) : sum.err ? (
          <p className="text-[12px] text-ink-dim">读取失败（{sum.err}）</p>
        ) : (
          <Loading />
        )}
      </ObsBack>
    )
  }
  if (module === 'errors') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        {sum.data ? (
          <ObsErrors d={sum.data} />
        ) : sum.err ? (
          <p className="text-[12px] text-ink-dim">读取失败（{sum.err}）</p>
        ) : (
          <Loading />
        )}
      </ObsBack>
    )
  }
  if (module === 'memory') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        <ObsMemoryM mem={mem} />
      </ObsBack>
    )
  }
  if (module === 'injection') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        <ObsInjection inj={inj} />
      </ObsBack>
    )
  }
  if (module === 'mastery') {
    /* B1 掌握台账（2026-08-27）：深度学习工具面的记录可视化——主题正答率 + 近因趋势，非门控参考 */
    const md = mastery.data
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        <div className={`${fCard} border-primary/25`}>
          <div className={`${fTitle} text-primary`}>
            <Icon name='book-open' size={14} /> 掌握台账
          </div>
          <p className="text-[11.5px] text-ink-dim leading-relaxed mt-1">
            练习/批改/间隔信号的记录——主题正答率 + 近因趋势。这是参考信号不是门槛：
            是否加练、学什么，由你和模型共同判断。
          </p>
          {md && md.total_records > 0 && (
            <div className="flex flex-wrap gap-2 mt-3 text-[12px]">
              <span className="px-2.5 py-1 rounded-full border border-primary/25 bg-primary/8 text-primary/90 font-mono">
                共 {md.total_records} 次练习
              </span>
              <span className="px-2.5 py-1 rounded-full border border-hairline text-ink-muted font-mono">
                {md.topics} 个主题
              </span>
              {Object.entries(md.judge_dist).map(([j, n]) => (
                <span key={j} className="px-2.5 py-1 rounded-full border border-hairline text-ink-dim">
                  {j} ×{n}
                </span>
              ))}
            </div>
          )}
          {mastery.err && <p className="text-[12px] text-ink-dim mt-2">台账读取失败（{mastery.err}）</p>}
          {!md && !mastery.err && <p className="text-[12px] text-ink-dim mt-3">读取中…</p>}
        </div>

        {md && md.items.length === 0 && (
          <div className={`${fCard}`}>
            <p className="text-[12.5px] text-ink-dim leading-relaxed">
              还没有掌握记录——在对话里说「给我出道题练练」或「批改一下」，练习和批改会自动记进台账。
            </p>
          </div>
        )}

        {md && md.items.length > 0 && (
          <div className="space-y-2">
            {md.items.map((it) => (
              <div key={it.topic} className={`${fCard} !p-3.5 flex items-center gap-3`}>
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] text-ink font-medium truncate">{it.topic}</div>
                  <div className="text-[11px] text-ink-dim mt-0.5">
                    共 {it.total} 次 · 最近 {it.last_ts} · {it.trend}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div
                    className={`text-[20px] font-mono leading-none ${it.rate >= 0.7 ? 'text-primary' : 'text-amber'}`}
                  >
                    {Math.round(it.rate * 100)}%
                  </div>
                  <div className="text-[10px] text-ink-dim mt-1">正答率</div>
                </div>
                <div className="w-24 h-1.5 rounded-full bg-hairline/60 overflow-hidden shrink-0">
                  <div
                    className={`h-full rounded-full ${it.rate >= 0.7 ? 'bg-gradient-to-r from-primary/50 to-primary' : 'bg-amber/70'}`}
                    style={{ width: `${it.rate * 100}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </ObsBack>
    )
  }
  if (module === 'capabilities') {
    /* 能力仪表盘（评估体系 v1，2026-08-31）：scoreboard 五 section + meta（note/gaps/新鲜度） */
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        <ObsCapabilitiesBoard cap={cap} />
      </ObsBack>
    )
  }
  if (module === 'replay') {
    return (
      <ObsBack label="观测台" onBack={() => setModule(null)}>
        <ObsReplay sessions={sessions} />
      </ObsBack>
    )
  }

  const d = sum.data
  const errTotal = d ? Object.values(d.trace.errors).reduce((a, b) => a + b, 0) : 0
  const llmCalls = d ? d.trace.llm_stats.reduce((a, l) => a + l.calls, 0) : 0
  const toolCalls = d?.trace.tool_calls ?? 0

  const mods: {
    key: ObsModule
    icon: 'gauge' | 'trend' | 'alert' | 'memory' | 'inject' | 'replay' | 'mastery' | 'cap'
    title: string
    desc: string
    badge?: string
    badgeColor: string
  }[] = [
    {
      key: 'calls',
      icon: 'gauge',
      title: '调用分析',
      desc: 'LLM 与工具调用明细 · 成功率 · 耗时',
      badge: d ? `${llmCalls + toolCalls} 次` : '—',
      badgeColor: 'text-primary',
    },
    {
      key: 'token',
      icon: 'trend',
      title: 'Token 趋势',
      desc: '近 14 天消耗 · 按角色分布',
      badge: d ? fmtN(d.token.total) : '—',
      badgeColor: 'text-primary',
    },
    {
      key: 'errors',
      icon: 'alert',
      title: '错误分布',
      desc: '错误来源 · 完整性检查',
      badge: d ? `${errTotal}` : '—',
      badgeColor: errTotal > 0 ? 'text-[#e8a58c]' : 'text-ink-dim',
    },
    {
      key: 'memory',
      icon: 'memory',
      title: '记忆健康',
      desc: '条目 · 类别 · 画像',
      badge: mem.data ? `${mem.data.entries} 条` : '…',
      badgeColor: 'text-amber',
    },
    {
      key: 'injection',
      icon: 'inject',
      title: '注入审计',
      desc: '每轮上下文预算趋势',
      badge: inj.data?.records.length ? `${inj.data.records.length} 条` : '…',
      badgeColor: 'text-primary',
    },
    {
      key: 'replay',
      icon: 'replay',
      title: '会话重放',
      desc: 'trace-driven debugging · 点会话看 run',
      badge: sessions.data ? `${sessions.data.sessions.length} 会话` : '…',
      badgeColor: 'text-amber',
    },
    {
      key: 'mastery',
      icon: 'mastery',
      title: '掌握台账',
      desc: '练习批改记录 · 主题正答率 · 近因趋势',
      badge: mastery.data ? `${mastery.data.topics} 主题` : '…',
      badgeColor: 'text-primary',
    },
    {
      key: 'capabilities',
      icon: 'cap',
      title: '能力仪表盘',
      desc: '评估体系 v1 · 纠错/学习/playbook/计划/预算 · 盲区',
      badge: cap.data ? `${arr(cap.data.meta.gaps).length} 盲区` : '…',
      badgeColor: 'text-amber',
    },
  ]

  const MOD_ICONS: Record<string, ReactNode> = {
    gauge: <Icon name='activity' size={17} />,
    trend: <Icon name='trending-up' size={17} />,
    alert: <Icon name='alert' size={17} />,
    memory: <Icon name='sparkles' size={17} />,
    inject: <Icon name='activity' size={17} />,
    replay: <Icon name='history' size={17} />,
    mastery: <Icon name='book-open' size={17} />,
    cap: <Icon name='sprout' size={17} />,
  }

  return (
    <div className="space-y-4">
      {/* 统计卡 4 */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { k: 'Token 消耗（近 14 天）', v: d ? fmtN(d.token.total) : '—', c: 'text-primary' },
          { k: '工具调用（累计）', v: d ? String(d.trace.tool_calls) : '—', c: 'text-ink' },
          {
            k: '错误事件',
            v: d ? String(errTotal) : '—',
            c: errTotal > 0 ? 'text-[#e8a58c]' : 'text-ink',
          },
          { k: '对话平均延迟', v: d ? fmtMs(d.trace.avg_delay_ms) : '—', c: 'text-amber' },
        ].map((c, i) => (
          <div key={i} className={`${fCard} !p-3.5`}>
            <div className="text-[10px] tracking-wide text-ink-dim">{c.k}</div>
            <div className={`text-[19px] font-medium mt-1 font-mono ${c.c}`}>{c.v}</div>
          </div>
        ))}
      </div>

      {/* 系统脉搏：一眼看健康 + 刷新 */}
      <div className={`${fCard} !py-2.5 !px-3.5 border-hairline/60`}>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
          <span className="flex items-center gap-1.5 text-ink-muted">
            <Icon name='activity' size={12} className="text-primary" /> 脉搏
          </span>
          <button
            onClick={() => {
              sum.reload()
              mem.reload()
              inj.reload()
              sessions.reload()
              cap.reload()
            }}
            className="ml-auto flex items-center gap-1 px-2 py-0.5 rounded-md border border-hairline text-ink-muted hover:text-primary hover:border-primary/40 transition-colors duration-150"
            title="重新拉取所有观测数据"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
              <path
                d="M21 12a9 9 0 1 1-2.64-6.36M21 3v6h-6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
            刷新
          </button>
          {d ? (
            <>
              <span className="text-ink-dim">LLM {llmCalls} 次</span>
              <span className="text-ink-dim">工具 {toolCalls} 次</span>
              <span className="text-ink-dim">错误 {errTotal}</span>
              <span className="text-ink-dim font-mono">p95 {fmtMs(d.trace.p95_delay_ms)}</span>
              {d.tier && (
                <span
                  className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-primary/30 bg-primary/8 text-primary font-mono"
                  title={`渐进能力档位（harness 自动调整可及性，不约束模型）：${d.tier.why}`}
                >
                  <Icon name='shield' size={10} /> 档位 {d.tier.tier}
                </span>
              )}
              <span className="text-ink-dim font-mono">prompt v{d.prompt_version}</span>
              <span className="text-ink-dim/70 font-mono">事件 {d.integrity.events}</span>
              {d.verify && (
                <span
                  className="flex items-center gap-1 px-2 py-0.5 rounded-full border border-primary/25 bg-primary/5 text-primary/80 font-mono"
                  title={`验证器工作（自进化把关轴，2026-08-27）：${d.verify.last || '暂无记录'}`}
                >
                  <Icon name='shield' size={10} /> 验证 {d.verify.total}
                </span>
              )}
            </>
          ) : (
            <span className="text-ink-dim/70">读取中…</span>
          )}
        </div>
      </div>

      {!d && !sum.err && <Loading />}
      {sum.err && <p className="text-[12px] text-ink-dim">观测读取失败（{sum.err}）</p>}

      {/* 模块卡 6：点进看详情 */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {mods.map((m) => (
          <button
            key={m.key}
            onClick={() => setModule(m.key)}
            className={`${fCard} !p-4 text-left group transition-all duration-200 hover:-translate-y-0.5 hover:border-amber/30`}
          >
            <div className="flex items-start justify-between">
              <span className="text-amber/90">{MOD_ICONS[m.icon]}</span>
              <span className={`text-[11px] font-mono ${m.badgeColor}`}>{m.badge}</span>
            </div>
            <div className="mt-2.5 text-[13.5px] font-medium text-ink">{m.title}</div>
            <div className="text-[11px] text-ink-dim mt-0.5 leading-relaxed">{m.desc}</div>
            <div className="flex items-center gap-1 mt-2 text-[11px] text-ink-dim/70 group-hover:text-primary transition-colors duration-150">
              查看详情 <Icon name='chevron-right' size={12} />
            </div>
          </button>
        ))}
      </div>

      {d && <p className="text-[10px] text-ink-dim/60 font-mono">生成于 {d.generated_at}</p>}
    </div>
  )
}

/* ============ 记忆治理（2026-08-27 HARNESS-V2 星图第 8 张卡） ============
用户对记忆的知情与掌控=本地产品信任底线（Zep 治理 / Anthropic namespace 启示）。
id 级操作（稳定定位）+ 删除带 reason（contradicted/superseded/stale/low-signal/user_request）
+ 回收站可恢复 + 类别过滤 + 画像/回收站查看。全部走 /api/memory/*。 */
