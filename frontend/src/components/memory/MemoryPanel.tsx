import { useCallback, useEffect, useState } from 'react'
import {
  deleteMemory,
  editMemory,
  fetchChanges,
  fetchMemory,
  type ChangeRecord,
  type MemoryData,
} from '../../api/memory'
import EvolveCard from './EvolveCard'
import MemoryCard from './MemoryCard'
import DetailModal from '../ui/DetailModal'
import Icon from '../ui/Icon'
import KbDocList from './KbDocList'

type Tab = 'memory' | 'reflection' | 'skill' | 'kb'

/* 星尘变更条目：动作徽标 + 时间 + 摘要（治理权#3：看见"谁改了什么"） */
function ChangeRow({ c }: { c: ChangeRecord }) {
  const actionColor: Record<string, string> = {
    'remember(ADD)': 'text-success',
    'forget(DELETE)': 'text-error',
    'edit_memory(UPDATE)': 'text-primary',
    'strength(S+1)': 'text-ink-dim',
  }
  const label = c.action.includes('remember') ? '新增' : c.action.includes('forget') ? '熄星' : c.action.includes('edit') ? '修正' : '增强'
  const time = (c.time || '').slice(5, 16) // MM-DD HH:MM
  return (
    <div className="flex items-start gap-2 py-1.5 border-b border-hairline/50 last:border-0">
      <span className={`shrink-0 mt-0.5 text-[10px] px-1.5 py-0.5 rounded ${actionColor[c.action] ?? 'text-ink-dim'} bg-elevated`}>
        {label}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[12px] text-ink/80 leading-relaxed break-words">{c.summary}</div>
        <div className="text-[10px] text-ink-dim/70 mt-0.5">{time} · {c.action}</div>
      </div>
    </div>
  )
}

/* 空状态统一语言：一粒光 + 虚线轨迹（与左栏路径空态一致） */
function EmptyLight({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-2.5 py-8">
      <div className="flex items-center">
        <span className="empty-light" />
        <span className="empty-trail" />
      </div>
      <div className="text-[12px] text-ink-dim/80 text-center max-w-[220px] leading-relaxed">
        {text}
      </div>
    </div>
  )
}

/* 星尘（M5 载体 + M8 扩展）：画像卡 + tab（星尘/反思/技能）+ 修正/熄星 + 加载骨架 */
export default function MemoryPanel() {
  const [data, setData] = useState<MemoryData | null>(null)
  const [tab, setTab] = useState<Tab>('memory')
  const [sortDesc, setSortDesc] = useState(true) // 星尘排序：true=最新在上（默认），false=最早在上
  const [profileOpen, setProfileOpen] = useState(false)
  const [changes, setChanges] = useState<ChangeRecord[]>([])
  const [changesOpen, setChangesOpen] = useState(false)

  /* 星尘列表按日期排序（date 为 YYYY-MM-DD 可字符串比较） */
  const sortedEntries = [...(data?.entries ?? [])].sort((a, b) =>
    sortDesc ? b.date.localeCompare(a.date) : a.date.localeCompare(b.date),
  )

  const reload = useCallback(() => {
    fetchMemory()
      .then(setData)
      .catch(() => setData(null))
    fetchChanges()
      .then(setChanges)
      .catch(() => setChanges([]))
  }, [])

  useEffect(reload, [reload])

  const handleEdit = async (oldText: string, newText: string) => {
    if (oldText === newText) return
    await editMemory(oldText, newText)
    reload()
  }

  const handleDelete = async (content: string) => {
    await deleteMemory(content)
    reload()
  }

  const handleEvolveDelete = async (_content: string) => {
    reload()
  }

  const tabs: { key: Tab; label: string; count: number }[] = [
    { key: 'memory', label: '星尘', count: data?.entries.length ?? 0 },
    { key: 'reflection', label: '反思', count: data?.reflections.length ?? 0 },
    { key: 'skill', label: '技能', count: data?.skills.length ?? 0 },
    { key: 'kb', label: '知识库', count: 0 },
  ]

  return (
    <div className="h-full flex flex-col min-h-0">
      <h2 className="text-[13px] font-medium text-ink px-4 pt-4 pb-2">
        星尘
      </h2>
      {/* tab 切换 */}
      <div className="flex px-4 pb-2 gap-1">
        {tabs.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-2.5 py-1 rounded-lg text-[12px] transition-colors duration-150 ${
              tab === t.key
                ? 'bg-primary/15 text-primary'
                : 'text-ink-dim hover:text-ink/80 hover:bg-surface'
            }`}
            aria-pressed={tab === t.key}
          >
            {t.label}
            {t.count > 0 && <span className="ml-1 text-[10px] opacity-70">{t.count}</span>}
          </button>
        ))}
        {/* 星尘排序切换：最新在上 / 最早在上（仅星尘 tab 显示） */}
        {tab === 'memory' && data && data.entries.length > 1 && (
          <button
            onClick={() => setSortDesc((v) => !v)}
            className="ml-auto px-2 py-1 rounded-lg text-[11px] text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
            title={sortDesc ? '当前：最新在上，点击切为最早在上' : '当前：最早在上，点击切为最新在上'}
            aria-label="切换星尘排序"
          >
            {sortDesc ? '最新 ↓' : '最早 ↑'}
          </button>
        )}
      </div>
      <div className="flex-1 overflow-y-auto px-4 pb-4 flex flex-col gap-2">
        {tab === 'kb' ? (
          /* 知识库治理权（最小落地清单⑤）：文档列表 + 改名 + 熄星（回收站） */
          <KbDocList />
        ) : data === null ? (
          /* 加载骨架 */
          <>
            <div className="rounded-lg bg-elevated p-3 animate-pulse">
              <div className="h-3 w-10 bg-[rgba(255,255,255,0.1)] rounded mb-2" />
              <div className="h-3 bg-[rgba(255,255,255,0.07)] rounded" />
              <div className="h-3 bg-[rgba(255,255,255,0.07)] rounded mt-1.5" />
            </div>
            {[0, 1, 2].map((i) => (
              <div key={i} className="rounded-lg border border-hairline bg-surface p-2.5 animate-pulse">
                <div className="h-3 w-16 bg-[rgba(255,255,255,0.08)] rounded mb-2" />
                <div className="h-3 bg-[rgba(255,255,255,0.06)] rounded" />
              </div>
            ))}
          </>
        ) : (
          <>
            {tab === 'memory' && (
              <>
                <button
                  onClick={() => setProfileOpen(true)}
                  className="w-full text-left rounded-lg bg-elevated p-3 hover:bg-surface transition-colors duration-150 cursor-pointer"
                  aria-label="查看画像"
                >
                  <div className="text-[10px] uppercase tracking-wider text-primary mb-1">画像</div>
                  <p className="text-[12px] leading-relaxed text-ink-muted line-clamp-3">
                    {data.profile ?? '(暂无画像)'}
                  </p>
                </button>
                <DetailModal
                  title="画像"
                  open={profileOpen}
                  onClose={() => setProfileOpen(false)}
                >
                  {data.profile ?? '(暂无画像)'}
                </DetailModal>
                {/* 最近变更（治理权#3：看见谁改了什么星尘） */}
                {changes.length > 0 && (
                  <div className="rounded-lg border border-hairline bg-surface mb-2 overflow-hidden">
                    <button
                      onClick={() => setChangesOpen((v) => !v)}
                      className="w-full flex items-center justify-between px-3 py-2 text-[12px] text-ink-muted hover:text-ink transition-colors"
                      aria-expanded={changesOpen}
                    >
                      <span className="flex items-center gap-1.5">
                        <Icon name="history" size={13} />
                        最近变更
                      </span>
                      <span className="text-[10px] text-ink-dim/80">
                        {changesOpen ? '收起' : `${changes.length} 条`}
                      </span>
                    </button>
                    {changesOpen && (
                      <div className="px-3 pb-2 max-h-[180px] overflow-y-auto">
                        {changes.map((c, i) => (
                          <ChangeRow key={`${c.time}-${i}`} c={c} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
                {sortedEntries.map((e, i) => (
                  <MemoryCard
                    key={`${e.content}-${i}`}
                    entry={e}
                    onEdited={handleEdit}
                    onDeleted={handleDelete}
                  />
                ))}
                {data.entries.length === 0 && (
                  <EmptyLight text="还没有星尘——聊一聊，拾光会记住你在意的事。" />
                )}
              </>
            )}
            {tab === 'reflection' && (
              <>
                {data.reflections.map((r, i) => (
                  <EvolveCard key={`${r.id}-${i}`} item={r} kind="reflection" onDeleted={handleEvolveDelete} />
                ))}
                {data.reflections.length === 0 && (
                  <EmptyLight text="还没有反思——对回答点 👎 或说「讲得不好」，拾光会反思并记在这里。" />
                )}
              </>
            )}
            {tab === 'skill' && (
              <>
                {data.skills.map((s, i) => (
                  <EvolveCard key={`${s.id}-${i}`} item={s} kind="skill" onDeleted={handleEvolveDelete} />
                ))}
                {data.skills.length === 0 && (
                  <EmptyLight text="还没有技能——说「这个讲法真好」，拾光会把它存进技能库。" />
                )}
              </>
            )}
          </>
        )}
      </div>
    </div>
  )
}
