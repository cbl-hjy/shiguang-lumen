/* 能力仪表盘（评估体系 v1，2026-08-30，设计 docs/2026-08-30-EVAL-SYSTEM-DESIGN.md）
   观测台内区块（功能分层：运维类进观测台，不进主导航）。
   红线：无数据指标原样灰显「没有数据」，绝不显示 0%；只呈现不判定（N=1 描述性）。 */
import { type CapRatio, type CapSkillNet, type Capabilities } from '../../api/obs'
import Icon from '../ui/Icon'
import { Loading, arr, fCard, fTitle } from './shared'

/* —— 值渲染：比率→百分比；计数→数字；字符串（「没有数据」等）→原样灰显 —— */
function isRatio(v: unknown): v is CapRatio {
  return typeof v === 'object' && v !== null && typeof (v as CapRatio).pct === 'number'
}

function MetricValue({ v, unit }: { v: unknown; unit?: string }) {
  if (isRatio(v)) {
    return (
      <span className="shrink-0 text-right">
        <span className="font-mono text-primary">{Math.round(v.pct * 100)}%</span>
        <span className="ml-1.5 text-[10px] text-ink-dim/70 font-mono">
          {v.num}/{v.den}
        </span>
      </span>
    )
  }
  if (typeof v === 'number') {
    return (
      <span className="shrink-0 font-mono text-ink/85">
        {v}
        {unit && <span className="text-[10px] text-ink-dim/70"> {unit}</span>}
      </span>
    )
  }
  /* 「没有数据」等字符串：原样灰显（红线：不许显示 0%） */
  return <span className="shrink-0 text-ink-dim/70">{String(v)}</span>
}

function MetricRow({ label, v, unit }: { label: string; v: unknown; unit?: string }) {
  return (
    <div className="flex items-center gap-2 text-[12px] border-b border-hairline/30 last:border-0 pb-1.5 last:pb-0">
      <span className="flex-1 text-ink/85">{label}</span>
      <MetricValue v={v} unit={unit} />
    </div>
  )
}

/* —— 纠错循环 —— */
function ErrorLoopCard({ s }: { s: Capabilities['sections']['error_loop'] }) {
  const metrics: [string, string?][] = [
    ['连续错误率'],
    ['自我恢复率'],
    ['循环逃脱率'],
    ['升级次数', '次'],
    ['升级准确率'],
  ]
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-primary`}>
        <Icon name='activity' size={14} /> 纠错循环
      </div>
      {s.records && (
        <div className="text-[11px] text-ink-dim mb-2 font-mono">
          样本：{s.records.seq_ends} 条错误序列 · {s.records.errors} 个错误事件
        </div>
      )}
      <div className="space-y-1.5">
        {metrics.map(([label, unit]) => (
          <MetricRow key={label} label={label} v={s[label]} unit={unit} />
        ))}
      </div>
    </div>
  )
}

/* —— 学习（校准 + 保持率文本为后端渲染原文，直接呈现不重排） —— */
function LearningCard({ s }: { s: Capabilities['sections']['learning'] }) {
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-primary`}>
        <Icon name='book-open' size={14} /> 学习（校准 + 保持率）
      </div>
      <div className="flex items-center gap-2 text-[12px] mb-2.5">
        <span className="flex-1 text-ink/85">复测覆盖率</span>
        <MetricValue v={s.retest_coverage} />
      </div>
      {isRatio(s.retest_coverage) && s.retest_coverage.口径 && (
        <p className="text-[10px] text-ink-dim/70 mb-2.5 -mt-1.5">口径：{s.retest_coverage.口径}</p>
      )}
      <p className="text-[11.5px] text-ink-dim leading-relaxed whitespace-pre-line border-t border-hairline/30 pt-2.5">
        {s.calibration}
      </p>
      <p className="text-[11.5px] text-ink-dim leading-relaxed whitespace-pre-line border-t border-hairline/30 mt-2.5 pt-2.5">
        {s.retention}
      </p>
    </div>
  )
}

/* —— ACE playbook —— */
const MATURITY_STATES: [string, string][] = [
  ['draft', 'draft'],
  ['tested', 'tested'],
  ['mature', 'mature'],
  ['deprecated', 'deprecated'],
]

function NetRow({ n }: { n: CapSkillNet }) {
  return (
    <div className="flex items-center gap-2 text-[11.5px] border-b border-hairline/30 last:border-0 pb-1 last:pb-0">
      <span className="w-12 shrink-0 text-[10px] text-ink-dim/70 font-mono">{n.state}</span>
      <span className="flex-1 truncate text-ink/85" title={n.sid}>
        {n.desc || n.sid}
      </span>
      <span className="shrink-0 text-[10px] text-ink-dim/70 font-mono">
        +{n.helpful}/-{n.harmful}
      </span>
      <span className={`shrink-0 font-mono ${n.net >= 0 ? 'text-primary' : 'text-amber'}`}>
        {n.net >= 0 ? `+${n.net}` : n.net}
      </span>
    </div>
  )
}

function PlaybookCard({ s }: { s: Capabilities['sections']['playbook'] }) {
  const dist = s.maturity_distribution
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-amber`}>
        <Icon name='sprout' size={14} /> ACE playbook
      </div>
      <div className="flex items-center gap-2 text-[12px] mb-2.5">
        <span className="flex-1 text-ink/85">delta 采纳率</span>
        {typeof s.delta_adoption === 'object' && s.delta_adoption !== null ? (
          <span className="shrink-0 text-right">
            <span className="font-mono text-primary">
              {Math.round(s.delta_adoption.pct * 100)}%
            </span>
            <span className="ml-1.5 text-[10px] text-ink-dim/70 font-mono">
              采纳 {s.delta_adoption.applied} / 弃 {s.delta_adoption.rejected}
            </span>
          </span>
        ) : (
          <span className="shrink-0 text-ink-dim/70">{String(s.delta_adoption)}</span>
        )}
      </div>
      <div className="text-[11px] text-ink-dim mb-1.5">技能四态分布</div>
      {typeof dist === 'string' ? (
        <p className="text-[12px] text-ink-dim/70 mb-2.5">{dist}</p>
      ) : (
        <div className="flex flex-wrap gap-1.5 mb-3">
          {MATURITY_STATES.map(([key, label]) => (
            <span
              key={key}
              className={`px-2 py-0.5 rounded-full border text-[11px] font-mono ${
                key === 'deprecated'
                  ? 'border-hairline/60 text-ink-dim/70'
                  : dist[key as keyof typeof dist] > 0
                    ? 'border-primary/25 bg-primary/8 text-primary/90'
                    : 'border-hairline/60 text-ink-dim'
              }`}
            >
              {label} ×{dist[key as keyof typeof dist]}
            </span>
          ))}
        </div>
      )}
      {typeof s.net_top3 !== 'string' && arr(s.net_top3).length > 0 && (
        <>
          <div className="text-[11px] text-ink-dim mb-1.5">净值 top（helpful−harmful）</div>
          <div className="space-y-1 mb-2.5">
            {arr(s.net_top3).map((n) => (
              <NetRow key={n.sid} n={n} />
            ))}
          </div>
        </>
      )}
      {typeof s.net_top3 === 'string' && (
        <p className="text-[12px] text-ink-dim/70 mb-2.5">{s.net_top3}</p>
      )}
      {typeof s.net_bottom3 !== 'string' && arr(s.net_bottom3).length > 0 && (
        <>
          <div className="text-[11px] text-ink-dim mb-1.5">净值末位</div>
          <div className="space-y-1">
            {arr(s.net_bottom3).map((n) => (
              <NetRow key={n.sid} n={n} />
            ))}
          </div>
        </>
      )}
    </div>
  )
}

/* —— 计划 —— */
function PlanCard({ s }: { s: Capabilities['sections']['plan'] }) {
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-primary`}>
        <Icon name='route' size={14} /> 计划
      </div>
      {s.goal && <div className="text-[12px] text-ink/85 mb-2 truncate">目标：{s.goal}</div>}
      {s.note && !s.goal && <p className="text-[12px] text-ink-dim">{s.note}</p>}
      {s.completion !== undefined && (
        <div className="flex items-center gap-2 text-[12px] mb-2.5">
          <span className="flex-1 text-ink/85">完成度</span>
          <MetricValue v={s.completion} />
        </div>
      )}
      <div className="text-[11px] text-ink-dim mb-1.5">证据档位构成（只呈现不判定）</div>
      {typeof s.evidence_tiers === 'string' || !s.evidence_tiers ? (
        <p className="text-[12px] text-ink-dim/70">
          {typeof s.evidence_tiers === 'string' ? s.evidence_tiers : '没有数据'}
        </p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {Object.entries(s.evidence_tiers).map(([t, x]) => (
            <span
              key={t}
              className="px-2 py-0.5 rounded-full border border-hairline/60 text-ink-muted text-[11px] font-mono"
            >
              {t} {Math.round(x.pct * 100)}%
              <span className="text-ink-dim/70"> ×{x.count}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

/* —— 预算（注入占比，沿用观测台注入审计的展示语言） —— */
function BudgetCard({ s }: { s: Capabilities['sections']['budget'] }) {
  const daily = typeof s.daily === 'string' ? [] : arr(s.daily)
  const max = Math.max(1, ...daily.map((x) => x.avg_total_chars))
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-amber`}>
        <Icon name='trending-up' size={14} /> 预算（注入占比 · 近 {s.window_days} 天）
      </div>
      <div className="space-y-1.5">
        <MetricRow label="平均注入量" v={s.avg_total_chars} unit="字符" />
        <div className="flex items-center gap-2 text-[12px] border-b border-hairline/30 last:border-0 pb-1.5 last:pb-0">
          <span className="flex-1 text-ink/85">占窗口估算比</span>
          {typeof s.avg_window_ratio === 'number' ? (
            <span className="shrink-0 font-mono text-primary">
              {(s.avg_window_ratio * 100).toFixed(1)}%
            </span>
          ) : (
            <span className="shrink-0 text-ink-dim/70">{String(s.avg_window_ratio)}</span>
          )}
        </div>
      </div>
      {typeof s.samples === 'number' && (
        <div className="text-[10px] text-ink-dim/70 font-mono mt-2">样本 {s.samples} 轮</div>
      )}
      {daily.length > 0 && (
        <div className="flex items-end gap-1 h-10 mt-2">
          {daily.map((bd) => (
            <div
              key={bd.date}
              className="flex-1 rounded-t bg-amber/40 hover:bg-amber/70 transition-colors duration-150"
              style={{ height: `${Math.max(3, (bd.avg_total_chars / max) * 32)}px` }}
              title={`${bd.date}: ${bd.avg_total_chars} 字符（${(bd.avg_window_ratio * 100).toFixed(1)}%）`}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/* —— 盲区 + 台账新鲜度（诚实标注：防"看不见=不存在"） —— */
function GapsCard({ d }: { d: Capabilities }) {
  const fresh = Object.entries(d.sections.freshness ?? {})
  return (
    <div className={`${fCard} border-amber/30`}>
      <div className={`${fTitle} text-amber`}>
        <Icon name='alert' size={14} /> 盲区（应该有但还没有的指标）
      </div>
      {arr(d.meta.gaps).length === 0 && <p className="text-[12px] text-ink-dim">暂无盲区标注</p>}
      <div className="flex flex-wrap gap-1.5">
        {arr(d.meta.gaps).map((g) => (
          <span
            key={g}
            className="px-2.5 py-1 rounded-full border border-amber/25 bg-amber/8 text-amber/90 text-[11.5px]"
          >
            {g}
          </span>
        ))}
      </div>
      {fresh.length > 0 && (
        <>
          <div className="text-[11px] text-ink-dim mt-3 mb-1.5">
            台账最后写入（数据停了 = 机制可能没被用起来）
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {fresh.map(([name, ts]) => (
              <span key={name} className="text-[10.5px] font-mono text-ink-dim/80">
                {name}{' '}
                <span className={ts === '没有数据' ? 'text-ink-dim/50' : 'text-ink-dim'}>
                  {ts}
                </span>
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  )
}

export function ObsCapabilitiesBoard({
  cap,
}: {
  cap: { data: Capabilities | null; err: string | null }
}) {
  if (cap.err) return <p className="text-[12px] text-ink-dim">读取失败（{cap.err}）</p>
  if (!cap.data) return <Loading />
  const d = cap.data
  const s = d.sections
  return (
    <div className="space-y-4">
      {/* meta.note 置顶一行小字：描述性声明必须可见 */}
      <p className="text-[11px] text-ink-dim/90 leading-relaxed px-1">{d.meta.note}</p>

      <ErrorLoopCard s={s.error_loop} />
      <LearningCard s={s.learning} />
      <PlaybookCard s={s.playbook} />
      <PlanCard s={s.plan} />
      <BudgetCard s={s.budget} />
      <GapsCard d={d} />

      <p className="text-[10px] text-ink-dim/60 font-mono">
        生成于 {d.generated_at} · 视角 {d.uid}
      </p>
    </div>
  )
}
