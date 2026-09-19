/* 「它记得我」抽屉（2026-08-28 前端重构）：
   取代星图 10 卡的功能枚举——用户视角只有一个问题："它记得我什么？"
   数据一次聚合加载（/api/me/overview），四个标签本地切换（零网络等待）。 */
import { useEffect, useState } from 'react'
import Icon, { type IconName } from './Icon'
import type { UserInfo } from '../../api/auth'
import MemoryHealth from '../memory/MemoryHealth'
import SessionSummaryCard from '../memory/SessionSummaryCard'

interface MemoryEntry {
  content: string
  category: string
  importance: number
  date: string
  source?: string
}
interface Topic {
  name: string
  status: string
  memory_count: number
  last_active?: string
}
interface Overview {
  profile: string
  memories: MemoryEntry[]
  memory_count: number
  categories: Record<string, number>
  topics: Topic[]
  stats: Record<string, number>
  growth: { skills: string; reflections: string }
  errors: string[]
}

const TABS: { id: 'profile' | 'memory' | 'path' | 'growth'; label: string; icon: IconName }[] = [
  { id: 'profile', label: '画像', icon: 'sparkles' },
  { id: 'memory', label: '记忆', icon: 'book-open' },
  { id: 'path', label: '路径', icon: 'route' },
  { id: 'growth', label: '成长', icon: 'sprout' },
] as const

const STATUS_COLOR: Record<string, string> = {
  active: '#3ec9b0',
  paused: '#e6be78',
  done: '#ece9e1',
  dormant: '#4a525a',
}

export default function MeDrawer({ user, onClose }: { user: UserInfo | null; onClose: () => void }) {
  const [tab, setTab] = useState<'profile' | 'memory' | 'path' | 'growth'>('profile')
  const [data, setData] = useState<Overview | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    let alive = true
    fetch('/api/me/overview')
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((d) => alive && setData(d))
      .catch((e) => alive && setErr(String(e?.message || e)))
    return () => {
      alive = false
    }
  }, [])

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-elevated/97 backdrop-blur-md animate-panel-in">
      <header
        className="flex items-center gap-3 px-4 py-3 border-b border-hairline shrink-0"
        style={{ paddingTop: 'max(env(safe-area-inset-top), 12px)' }}
      >
        <button
          onClick={onClose}
          className="p-2 -ml-2 rounded-lg text-ink-muted hover:text-ink hover:bg-surface transition-colors duration-150"
          aria-label="关闭"
        >
          <Icon name="x" size={18} />
        </button>
        <div className="flex-1 min-w-0">
          <h1 className="text-[15px] font-medium text-ink truncate">它记得我</h1>
          <p className="text-[11px] text-ink-dim truncate">
            {user?.nickname || '你'} 的档案 · {data ? `${data.memory_count} 条记忆` : '读取中…'}
          </p>
        </div>
      </header>

      {/* 标签（本地切换，零等待） */}
      <div className="flex gap-1.5 px-4 py-3 shrink-0">
        {TABS.map((t) => {
          const on = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`flex-1 flex items-center justify-center gap-1 py-2 rounded-xl text-[12px] transition-all duration-150 active:scale-95 ${
                on ? 'bg-primary/15 text-primary border border-primary/40' : 'text-ink-dim border border-hairline hover:text-ink'
              }`}
              aria-pressed={on}
            >
              <Icon name={t.icon} size={13} /> {t.label}
            </button>
          )
        })}
      </div>

      <div className="flex-1 overflow-y-auto px-4 pb-8">
        {err && <p className="text-[13px] text-error">读取失败（{err}）</p>}
        {!data && !err && (
          <div className="space-y-2.5 pt-2">
            {[0, 1, 2].map((i) => (
              <div key={i} className="skeleton h-3.5" style={{ width: `${80 - i * 15}%` }} />
            ))}
          </div>
        )}

        {data && tab === 'profile' && (
          <div className="rounded-2xl border border-amber/25 bg-surface/50 p-4">
            <p className="text-[13.5px] leading-[1.75] text-ink/90 whitespace-pre-wrap">
              {data.profile || '（还没攒够——多聊几次，它会慢慢画出你的样子）'}
            </p>
          </div>
        )}

        {data && tab === 'memory' && (
          <div className="space-y-3">
            {/* 记忆健康（Phase1 M-4 治理入口）：放在"它记得我"里——与记忆最直接相关，
                讲人话显示活跃度/休眠；冷记忆清单默认折叠不打扰 */}
            <MemoryHealth entriesCount={data.memories.length} />
            {/* 历史纪要（Phase2 C-1）：长会话早期对话压缩成的四字段纪要——可见不隐藏 */}
            <SessionSummaryCard />
            {data.memories.length === 0 && (
              <p className="text-[13px] text-ink-dim py-2">还没有记忆——聊起来就有了</p>
            )}
            {data.memories.map((m, i) => (
              <div key={i} className="flex items-start gap-2.5 py-2.5 border-b border-hairline/40 last:border-0">
                <span
                  className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-[10px] border ${
                    m.category === '闪光'
                      ? 'border-amber/40 text-amber'
                      : m.category === '困惑'
                        ? 'border-sky/40 text-sky'
                        : 'border-hairline text-ink-dim'
                  }`}
                >
                  {m.category}
                </span>
                <p className="flex-1 text-[13px] text-ink/90 leading-relaxed break-words min-w-0">{m.content}</p>
              </div>
            ))}
          </div>
        )}

        {data && tab === 'path' && (
          <div className="space-y-2">
            {data.topics.length === 0 && (
              <p className="text-[13px] text-ink-dim py-4">还没有主题——说一句"我想学 X"点亮第一站</p>
            )}
            {data.topics.map((t) => (
              <div key={t.name} className="flex items-center gap-2.5 py-2.5 border-b border-hairline/40 last:border-0">
                <span
                  className="w-[7px] h-[7px] rounded-full shrink-0"
                  style={{
                    background: STATUS_COLOR[t.status] ?? '#4a525a',
                    boxShadow: `0 0 6px ${STATUS_COLOR[t.status] ?? '#4a525a'}`,
                  }}
                />
                <span className="text-[13px] text-ink/90 flex-1 min-w-0 truncate">{t.name}</span>
                <span className="text-[10px] text-ink-dim font-mono shrink-0">
                  {t.memory_count} 足迹{t.last_active ? ` · ${t.last_active.slice(0, 10)}` : ''}
                </span>
              </div>
            ))}
          </div>
        )}

        {data && tab === 'growth' && (
          <div className="space-y-4">
            <div>
              <p className="text-[11px] text-ink-dim mb-1.5">讲法技能（它怎么调整自己）</p>
              <p className="text-[13px] text-ink/90 leading-relaxed whitespace-pre-wrap">
                {data.growth.skills || '（还没沉淀）'}
              </p>
            </div>
            <div>
              <p className="text-[11px] text-ink-dim mb-1.5">反思记录</p>
              <p className="text-[13px] text-ink/85 leading-relaxed whitespace-pre-wrap">
                {data.growth.reflections || '（还没有）'}
              </p>
            </div>
          </div>
        )}

        {data?.errors?.length ? (
          <p className="text-[11px] text-ink-dim mt-4">部分数据读取异常：{data.errors.join('；')}</p>
        ) : null}
      </div>
    </div>
  )
}
