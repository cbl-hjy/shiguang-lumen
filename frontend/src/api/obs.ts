/* 运行观测（Observability）API 客户端——星图内观测视图的数据源
   后端：app/routers/observability.py（/api/observability/*），原 /obs 独立页同源 */

export interface ObsToolStat {
  name: string
  calls: number
  success: number
  fail: number
  success_rate: number
  avg_ms: number
}

export interface ObsLlmStat {
  tag: string
  calls: number
  success: number
  fail: number
  unfinished: number
  success_rate: number
  avg_ms: number
}

export interface ObsSummary {
  trace: {
    runs: number
    runs_started: number
    runs_ended: number
    tool_calls: number
    tool_stats: ObsToolStat[]
    llm_stats: ObsLlmStat[]
    errors: Record<string, number>
    avg_delay_ms: number
    p95_delay_ms: number
  }
  tier?: {
    tier: string
    why: string
    signals: Record<string, number | null>
  }
  verify?: {
    total: number
    ok: number
    grades: Record<string, number>
    last: string
  }
  token: {
    total: number
    by_role: Record<string, number>
    by_day: { date: string; tokens: number }[]
    cache?: {
      read: number
      write: number
      hit_ratio: number | null
      by_day: { date: string; read: number }[]
    }
  }
  council_errors: number
  prompt_version: string
  integrity: {
    events: number
    corrupt_lines: number
    write_fails: number
    runs_started: number
    runs_ended: number
  }
  generated_at: string
}

export interface ObsMemory {
  entries: number
  categories: Record<string, number>
  profile_chars: number
  last_updated: string
}

export interface InjectionRecord {
  time: string
  total: number
  state: number
  write_rules: number
}

export interface ObsSession {
  id: string
  created_at: string
  title: string
  summary: string
  traces: number
}

export interface ObsRun {
  run_id: string
  ts: string
  text: string
}

export interface ObsTraceEvent {
  type: string
  ts: string
  name: string
  status: string
  detail: string
  dur_ms?: number
}

export async function fetchSummary(): Promise<ObsSummary> {
  const r = await fetch('/api/observability/summary')
  return r.json()
}

export async function fetchObsMemory(): Promise<ObsMemory> {
  const r = await fetch('/api/observability/memory')
  return r.json()
}

export async function fetchInjection(): Promise<{ records: InjectionRecord[]; count: number }> {
  const r = await fetch('/api/observability/injection')
  return r.json()
}

/* B1 掌握台账（2026-08-27）：深度学习工具面（练习/批改/间隔信号）的台账展示 */
export interface MasteryItem {
  topic: string
  total: number
  ok: number
  rate: number
  last_ts: string
  trend: string
}

export interface MasterySummary {
  total_records: number
  topics: number
  items: MasteryItem[]
  judge_dist: Record<string, number>
}

export async function fetchMastery(): Promise<MasterySummary> {
  const r = await fetch('/api/learning/mastery')
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return r.json()
}

/* 能力仪表盘（评估体系 v1，2026-08-30，设计 docs/2026-08-30-EVAL-SYSTEM-DESIGN.md）
   后端：app/capability_metrics.py scoreboard() → GET /api/observability/capabilities。
   红线同后端：无数据指标是字符串「没有数据」，前端原样呈现，绝不换算 0%。 */
export interface CapRatio {
  pct: number
  num: number
  den: number
  口径?: string
}

export interface CapSkillNet {
  sid: string
  desc: string
  helpful: number
  harmful: number
  net: number
  state: string
}

export interface Capabilities {
  generated_at: string
  uid: string
  sections: {
    /* 指标名是中文键（后端口径原文）；值 = CapRatio | 计数 number | 「没有数据」字符串 */
    error_loop: { records?: { errors: number; seq_ends: number } } & Record<
      string,
      CapRatio | number | string | { errors: number; seq_ends: number } | undefined
    >
    learning: {
      calibration: string
      retention: string
      retest_coverage: CapRatio | string
    }
    playbook: {
      delta_adoption: { pct: number; applied: number; rejected: number; deltas: number } | string
      maturity_distribution:
        | { draft: number; tested: number; mature: number; deprecated: number }
        | string
      net_top3: CapSkillNet[] | string
      net_bottom3: CapSkillNet[] | string
    }
    plan: {
      goal?: string
      completion?: CapRatio | string
      evidence_tiers?: Record<string, { count: number; pct: number }> | string
      note?: string
    }
    budget: {
      window_days: number
      samples?: number
      avg_total_chars: number | string
      avg_window_ratio: number | string
      daily: { date: string; avg_total_chars: number; avg_window_ratio: number }[] | string
    }
    freshness: Record<string, string>
  }
  meta: {
    descriptive_only: boolean
    note: string
    gaps: string[]
  }
}

export async function fetchCapabilities(): Promise<Capabilities> {
  const r = await fetch('/api/observability/capabilities')
  if (!r.ok) throw new Error('HTTP ' + r.status)
  return r.json()
}

export async function fetchObsSessions(): Promise<{ sessions: ObsSession[] }> {
  const r = await fetch('/api/observability/sessions?limit=12')
  return r.json()
}

export async function fetchSessionRuns(sid: string): Promise<{ sid: string; runs: ObsRun[] }> {
  const r = await fetch(`/api/observability/session/${sid}/runs`)
  return r.json()
}

export async function fetchTrace(
  runId: string,
): Promise<{ run_id: string; events: ObsTraceEvent[] }> {
  const r = await fetch(`/api/observability/trace/${runId}`)
  return r.json()
}
