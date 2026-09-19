// 从 StarMap.tsx 纯移动切割（Phase 4 A-1，2026-08-29）——零逻辑改动，仅搬家 + import 修正
import { type CouncilEvent, type DebateMode, confirmSage, deleteClaim, distillBook, fetchDistillJobs, fetchModes, fetchSageDetail, listSages, startDebate, stopDebate, updateSageMeta } from '../../api/council'
import { type KbDocument, listKbDocs } from '../../api/kb'
import { deleteEvolutionItem, deleteMemory, editEvolutionItem, editMemory, fetchMemory } from '../../api/memory'
import { type Topic, fetchProgress } from '../../api/progress'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'
import { EditModal, Loading, arr, fCard, fTitle, useFetch } from './shared'
import { useEffect, useRef, useState } from 'react'

export function MemoryFeature() {
  const { data, err, reload } = useFetch(fetchMemory, "memory")
  const [editing, setEditing] = useState<{ idx: number; text: string } | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  if (err) return <p className="text-[12px] text-ink-dim">记忆读取失败（{err}）</p>
  if (!data) return <Loading />

  // 兜底：memory 根路由若缺 entries 字段（历史版本/降级响应）→ 空数组，不崩渲染
  const allEntries = arr(data.entries)
  const entries = allEntries.slice(0, 20)

  const saveEdit = async () => {
    if (!editing) return
    const old = entries[editing.idx]?.content
    if (!old || old === editing.text.trim()) {
      setEditing(null)
      return
    }
    setBusy(true)
    try {
      await editMemory(old, editing.text.trim())
      setEditing(null)
      reload()
    } catch {
      /* 保存失败保持编辑态 */
    } finally {
      setBusy(false)
    }
  }

  const remove = async (content: string) => {
    if (!window.confirm('删除这条记忆？此操作不可撤销。')) return
    setBusy(true)
    try {
      await deleteMemory(content)
      reload()
    } catch {
      /* 静默 */
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className={`${fCard} border-amber/25`}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='sparkles' size={14} /> 画像
        </div>
        <p className="text-[13px] leading-relaxed text-ink/90 whitespace-pre-wrap">
          {data.profile || '（尚未生成——积累记忆后自动沉淀）'}
        </p>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='history' size={14} /> 足迹 · {allEntries.length}
        </div>
        {entries.length === 0 && (
          <p className="text-[12px] text-ink-dim">还没有足迹——聊起来就有了</p>
        )}
        <div className="space-y-2">
          {entries.map((e, i) => (
            <div
              key={i}
              className="group flex items-start gap-2.5 border-b border-hairline/40 last:border-0 pb-2 last:pb-0"
            >
              {/* 重要性光点：importance 1-5，亮 1-2 粒 */}
              <span className="flex gap-[3px] mt-1.5 shrink-0">
                {[1, 2].map((n) => (
                  <span
                    key={n}
                    className="w-[5px] h-[5px] rounded-full"
                    style={{
                      background: e.importance >= n ? '#e6be78' : 'rgba(236,233,225,.12)',
                      boxShadow: e.importance >= n ? '0 0 5px rgba(230,190,120,.5)' : 'none',
                    }}
                  />
                ))}
              </span>
              <div className="min-w-0 flex-1">
                {
                  <>
                    {/* 默认截断，点击展开全文（2026-08-26：列表不全量显示，点击才看全） */}
                    <button
                      onClick={() => setExpanded(expanded === i ? null : i)}
                      className={`text-left text-[12.5px] leading-relaxed text-ink/90 hover:text-primary transition-colors duration-150 ${
                        expanded === i ? '' : 'line-clamp-2'
                      }`}
                      title={expanded === i ? '收起' : '点击展开全文'}
                    >
                      {e.content}
                    </button>
                    <p className="text-[10px] text-ink-dim mt-1 font-mono flex items-center gap-2">
                      <span>
                        {e.category} · {e.date?.slice(0, 10)}
                      </span>
                      {typeof e.strength === 'number' && e.strength > 0 && (
                        <span className="text-primary/70">用过 {e.strength} 次</span>
                      )}
                    </p>
                  </>
                }
              </div>
              {/* 治理操作（hover 显示）：编辑/删除——可观测性透明化 */}
              {editing?.idx !== i && (
                <span className="hidden group-hover:flex gap-1 shrink-0 mt-0.5">
                  <button
                    onClick={() => setEditing({ idx: i, text: e.content })}
                    className="p-1 rounded-md text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
                    aria-label="编辑记忆"
                    title="编辑"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                  <button
                    onClick={() => remove(e.content)}
                    disabled={busy}
                    className="p-1 rounded-md text-ink-dim hover:text-error hover:bg-elevated transition-colors duration-150"
                    aria-label="删除记忆"
                    title="删除"
                  >
                    <svg width="12" height="12" viewBox="0 0 24 24" fill="none">
                      <path
                        d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                </span>
              )}
            </div>
          ))}
        </div>
      </div>
      {editing && (
        <EditModal
          title="编辑记忆"
          value={editing.text}
          onChange={(v) => setEditing({ ...editing, text: v })}
          onSave={saveEdit}
          onCancel={() => setEditing(null)}
          busy={busy}
        />
      )}
    </div>
  )
}

/* 学习路径：stats + 主题卡（状态光点/续接点） */
export function PathFeature() {
  const { data, err } = useFetch(fetchProgress, "progress")
  if (err) return <p className="text-[12px] text-ink-dim">路径读取失败（{err}）</p>
  if (!data) return <Loading />
  const STATUS: Record<string, string> = {
    active: '#3ec9b0',
    paused: '#e6be78',
    done: '#ece9e1',
    dormant: '#4a525a',
  }
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div className={`${fCard} flex-1`}>
          <div className="text-[11px] text-ink-dim mb-1">主题</div>
          <div className="text-[20px] font-medium text-primary">{data.stats?.topic_count ?? 0}</div>
        </div>
        <div className={`${fCard} flex-1`}>
          <div className="text-[11px] text-ink-dim mb-1">记忆</div>
          <div className="text-[20px] font-medium text-primary">{data.memoryCount ?? 0}</div>
        </div>
        <div className={`${fCard} flex-1`}>
          <div className="text-[11px] text-ink-dim mb-1 flex items-center gap-1">
            <Icon name='flame' size={11} className="text-amber" /> 连续
          </div>
          <div className="text-[20px] font-medium text-amber">{data.streak ?? 0} 天</div>
        </div>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='route' size={14} /> 前方 · {data.topics.length} 条光轨
        </div>
        {data.topics.length === 0 && (
          <p className="text-[12px] text-ink-dim">还没有主题——说"我想学 X"点亮第一站</p>
        )}
        <div className="space-y-2">
          {data.topics.slice(0, 10).map((t: Topic) => (
            <div key={t.name} className="border-b border-hairline/40 last:border-0 pb-2 last:pb-0">
              <div className="flex items-center gap-2">
                <span
                  className="w-[7px] h-[7px] rounded-full shrink-0"
                  style={{
                    background: STATUS[t.status] ?? '#4a525a',
                    boxShadow: STATUS[t.status] ? `0 0 6px ${STATUS[t.status]}` : 'none',
                  }}
                />
                <span className="text-[13px] text-ink/90">{t.name}</span>
                <span className="ml-auto text-[10px] text-ink-dim font-mono">
                  {t.memory_count} 足迹 · {t.last_active?.slice(0, 10)}
                </span>
              </div>
              {t.continuation && !t.continuation.abandoned && (
                <p className="text-[11px] text-amber/80 mt-1 pl-[15px]">
                  续 · {t.continuation.text}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

/* 知识库：文档列表 */
export function KbFeature() {
  const { data, err } = useFetch(listKbDocs, "kbdocs")
  if (err) return <p className="text-[12px] text-ink-dim">知识库读取失败（{err}）</p>
  if (!data) return <Loading />
  const fmt = (n: number) =>
    n > 1024 * 1024 ? `${(n / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1024))}KB`
  return (
    <div className={fCard}>
      <div className={`${fTitle} text-primary`}>
        <Icon name='book-open' size={14} /> 知识库 · {data.length} 份文档
      </div>
      {data.length === 0 && (
        <p className="text-[12px] text-ink-dim">还没有文档——星图外拖拽文件到输入区即可入库</p>
      )}
      <div className="space-y-2">
        {data.map((d: KbDocument) => (
          <div
            key={d.id}
            className="flex items-center gap-3 border-b border-hairline/40 last:border-0 pb-2 last:pb-0"
          >
            <Icon name='book-open' size={13} className='text-ink-dim shrink-0' />
            <span className="text-[13px] text-ink/90 truncate flex-1">{d.title}</span>
            <span className="text-[10px] text-ink-dim font-mono shrink-0">
              {fmt(d.size)} · {d.vectors} 块
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* 成长 · 自进化：技能 + 反思 */
export function EvolveFeature() {
  const { data, err, reload } = useFetch(fetchMemory, "memory")
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [editing, setEditing] = useState<{
    kind: 'skill' | 'reflection'
    idx: number
    text: string
  } | null>(null)
  if (err) return <p className="text-[12px] text-ink-dim">读取失败（{err}）</p>
  if (!data) return <Loading />

  /* 兜底（2026-08-29 白屏事故根因）：/api/memory 曾只返回 profile/entries，
     缺 skills/reflections → `data.skills.length` 抛 TypeError → React 18 卸载整棵树。
     后端已补齐契约，这里再兜一层：字段缺失/为 null/非数组一律降级空数组。 */
  const skills = arr(data.skills)
  const reflections = arr(data.reflections)

  const remove = async (kind: 'skill' | 'reflection', content: string) => {
    if (!window.confirm('删除这条记录？此操作不可撤销。')) return
    setBusy(true)
    try {
      await deleteEvolutionItem(kind, content)
      reload()
    } catch {
      /* 静默 */
    } finally {
      setBusy(false)
    }
  }

  const saveEdit = async () => {
    if (!editing) return
    const list = editing.kind === 'skill' ? skills : reflections
    const old = list[editing.idx]?.content
    if (!old || old === editing.text.trim()) {
      setEditing(null)
      return
    }
    setBusy(true)
    try {
      await editEvolutionItem(editing.kind, old, editing.text.trim())
      setEditing(null)
      reload()
    } catch {
      /* 保持编辑态 */
    } finally {
      setBusy(false)
    }
  }

  /* 技能/反思统一条目渲染（光点行 + 截断展开 + hover 编辑/删除） */
  const Row = ({
    kind,
    item,
    i,
  }: {
    kind: 'skill' | 'reflection'
    item: { id: string; content: string; date?: string }
    i: number
  }) => (
    <div className="group/row flex items-start gap-2.5 border-b border-hairline/40 last:border-0 pb-2 last:pb-0">
      <span
        className="mt-1.5 shrink-0 w-[6px] h-[6px] rounded-full"
        style={{
          background: kind === 'skill' ? '#3ec9b0' : '#e6be78',
          boxShadow:
            kind === 'skill' ? '0 0 6px rgba(62,201,176,.6)' : '0 0 6px rgba(230,190,120,.6)',
        }}
      />
      <div className="min-w-0 flex-1">
        {
          <>
            {/* 默认截断，点击展开全文 */}
            <button
              onClick={() => setExpanded(expanded === i ? null : i)}
              className={`text-left text-[12.5px] leading-relaxed ${
                kind === 'skill' ? 'text-primary/90' : 'text-ink/85'
              } hover:text-primary transition-colors duration-150 ${expanded === i ? '' : 'line-clamp-2'}`}
              title={expanded === i ? '收起' : '点击展开全文'}
            >
              {item.content}
            </button>
            {item.date && (
              <p className="text-[10px] text-ink-dim mt-1 font-mono">{item.date?.slice(0, 10)}</p>
            )}
          </>
        }
      </div>
      {editing?.kind !== kind || editing.idx !== i ? (
        <span className="hidden group-hover/row:flex gap-1 shrink-0 mt-1">
          <button
            onClick={() => setEditing({ kind, idx: i, text: item.content })}
            className="p-1 rounded text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
            aria-label="编辑"
            title="编辑"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 20h9M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4z"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
          <button
            onClick={() => remove(kind, item.content)}
            disabled={busy}
            className="p-1 rounded text-ink-dim hover:text-error hover:bg-elevated transition-colors duration-150"
            aria-label="删除"
            title="删除"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
              <path
                d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        </span>
      ) : null}
    </div>
  )

  return (
    <div className="space-y-4">
      {/* 画像快照：成长的"此刻" */}
      <div className={`${fCard} border-amber/25`}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='sparkles' size={14} /> 此刻 · 画像
        </div>
        <p className="text-[13px] leading-relaxed text-ink/90 whitespace-pre-wrap">
          {data.profile || '（尚未生成——积累记忆后自动沉淀）'}
        </p>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='sprout' size={14} /> 技能 · {skills.length}
        </div>
        {skills.length === 0 && (
          <p className="text-[12px] text-ink-dim">尚无沉淀技能——拾光会把讲法沉淀成技能</p>
        )}
        <div className="space-y-2.5">
          {skills.map((sk, i) => (
            <Row key={sk.id} kind="skill" item={sk} i={i} />
          ))}
        </div>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='sparkles' size={14} /> 反思 · {reflections.length}
        </div>
        {reflections.length === 0 && (
          <p className="text-[12px] text-ink-dim">尚无反思——拾光会记录对话里的转折时刻</p>
        )}
        <div className="space-y-2.5">
          {reflections.map((r, i) => (
            <Row key={r.id} kind="reflection" item={r} i={i} />
          ))}
        </div>
      </div>
      {editing && (
        <EditModal
          title={editing.kind === 'skill' ? '编辑技能' : '编辑反思'}
          value={editing.text}
          onChange={(v) => setEditing({ ...editing, text: v })}
          onSave={saveEdit}
          onCancel={() => setEditing(null)}
          busy={busy}
        />
      )}
    </div>
  )
}

/* 星阁 · 先贤议会（2026-08-26 重设计）：专门存放已蒸馏的书籍——先贤卡 + 星笺可查看/修改/删除。
   辩论另设星图内独立界面（DebateFeature），不再弹旧 DebateView 弹窗。 */
export interface SageDetail {
  id: string
  name: string
  book: string
  author: string
  year: string
  stance: string
  confirmed: boolean
  core_claims: { title: string; quote?: string }[]
  skeleton?: string[]
  boundaries?: {
    limits?: string[]
    blindspots?: string[]
    unproven?: string[]
    strongest_opposition?: string
  }
}

export function SageFeature({ onStartDebate }: { onStartDebate: () => void }) {
  const { data, err, reload } = useFetch(listSages, "sages")
  const [detailId, setDetailId] = useState<string | null>(null)
  const [detail, setDetail] = useState<SageDetail | null>(null)
  const [detailErr, setDetailErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [stanceEdit, setStanceEdit] = useState<{ name: string; stance: string } | null>(null)

  const openDetail = async (id: string) => {
    setDetailId(id)
    setDetail(null)
    setDetailErr('')
    try {
      setDetail((await fetchSageDetail(id)) as unknown as SageDetail)
    } catch (e) {
      setDetailErr(String((e as Error).message || e))
    }
  }

  const removeClaim = async (idx: number) => {
    if (!detailId) return
    if (!window.confirm('删除这张星笺？此操作不可撤销。')) return
    setBusy(true)
    try {
      await deleteClaim(detailId, idx)
      setDetail((await fetchSageDetail(detailId)) as unknown as SageDetail)
      reload()
    } catch {
      /* 静默 */
    } finally {
      setBusy(false)
    }
  }

  const toggleConfirm = async () => {
    if (!detailId || !detail) return
    setBusy(true)
    try {
      await confirmSage(detailId, !detail.confirmed)
      setDetail((await fetchSageDetail(detailId)) as unknown as SageDetail)
      reload()
    } catch {
      /* 静默 */
    } finally {
      setBusy(false)
    }
  }

  const saveMeta = async () => {
    if (!detailId || !stanceEdit) return
    setBusy(true)
    try {
      await updateSageMeta(detailId, stanceEdit.name, stanceEdit.stance)
      setStanceEdit(null)
      setDetail((await fetchSageDetail(detailId)) as unknown as SageDetail)
      reload()
    } catch {
      /* 保持编辑态 */
    } finally {
      setBusy(false)
    }
  }

  if (err) return <p className="text-[12px] text-ink-dim">星阁读取失败（{err}）</p>
  if (!data) return <Loading />

  /* —— 星笺详情视图（一本书的蒸馏内容：可见可改可删） —— */
  if (detailId) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setDetailId(null)}
          className="flex items-center gap-1.5 text-[12px] text-ink-dim hover:text-amber transition-colors duration-150"
        >
          <Icon name='arrow-left' size={14} /> 星阁
        </button>
        {detailErr && <p className="text-[12px] text-ink-dim">读取失败（{detailErr}）</p>}
        {!detail && !detailErr && <Loading />}
        {detail && (
          <>
            <div className={`${fCard} border-amber/25`}>
              <div className="flex items-start justify-between gap-2">
                <div className={`${fTitle} text-amber`}>
                  <Icon name='users' size={14} /> {detail.name}
                </div>
                <button
                  onClick={toggleConfirm}
                  disabled={busy}
                  className={`shrink-0 px-2.5 py-1 rounded-full text-[11px] border transition-colors duration-150 ${
                    detail.confirmed
                      ? 'border-primary/40 bg-primary/10 text-primary hover:bg-primary/20'
                      : 'border-amber/40 bg-amber/10 text-amber hover:bg-amber/20'
                  }`}
                  title={detail.confirmed ? '已确认（点击取消）' : '待审计（点击确认）'}
                >
                  {detail.confirmed ? '● 已确认' : '○ 待审计'}
                </button>
              </div>
              <p className="text-[11px] text-ink-dim font-mono mt-1">
                {detail.book}
                {detail.author ? ` · ${detail.author}` : ''}
                {detail.year ? ` · ${detail.year}` : ''}
              </p>
              <p className="text-[12.5px] leading-relaxed text-ink/85 mt-2.5 whitespace-pre-wrap">
                {detail.stance}
              </p>
              <button
                onClick={() => setStanceEdit({ name: detail.name, stance: detail.stance })}
                className="mt-2.5 px-2.5 py-1 rounded-lg text-[11px] text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
              >
                ✎ 编辑立场 / 书名
              </button>
            </div>

            <div className={fCard}>
              <div className={`${fTitle} text-primary`}>
                <Icon name='sparkles' size={14} /> 星笺 · {detail.core_claims.length}
              </div>
              {detail.core_claims.length === 0 && (
                <p className="text-[12px] text-ink-dim">这本书还没有星笺——蒸馏时会沉淀核心观点</p>
              )}
              <div className="space-y-2.5">
                {detail.core_claims.map((c, i) => (
                  <div
                    key={i}
                    className="group/claim flex items-start gap-2.5 border-b border-hairline/40 last:border-0 pb-2.5 last:pb-0"
                  >
                    <span className="mt-1.5 shrink-0 w-[6px] h-[6px] rounded-full bg-amber shadow-[0_0_6px_rgba(230,190,120,.55)]" />
                    <div className="min-w-0 flex-1">
                      <p className="text-[12.5px] leading-relaxed text-ink/90">{c.title}</p>
                      {c.quote && (
                        <p className="text-[11px] text-ink-dim leading-relaxed mt-1 border-l-2 border-hairline pl-2">
                          原文：{c.quote.length > 120 ? c.quote.slice(0, 120) + '…' : c.quote}
                        </p>
                      )}
                    </div>
                    <button
                      onClick={() => removeClaim(i)}
                      disabled={busy}
                      className="opacity-0 group-hover/claim:opacity-100 mt-1 p-1 rounded text-ink-dim hover:text-error hover:bg-elevated transition-all duration-150 shrink-0"
                      aria-label="删除星笺"
                      title="删除星笺"
                    >
                      <svg width="11" height="11" viewBox="0 0 24 24" fill="none">
                        <path
                          d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2m3 0v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"
                          stroke="currentColor"
                          strokeWidth="1.8"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                        />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            </div>

            {stanceEdit && (
              <EditModal
                title="编辑星宿"
                value={stanceEdit.stance}
                onChange={(v) => setStanceEdit({ ...stanceEdit, stance: v })}
                onSave={saveMeta}
                onCancel={() => setStanceEdit(null)}
                busy={busy}
              />
            )}
          </>
        )}
      </div>
    )
  }

  /* —— 名录视图（先贤卡：已蒸馏书籍） —— */
  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='users' size={14} /> 星阁 · {data.length} 本星书
        </div>
        <p className="text-[11.5px] text-ink-dim leading-relaxed mb-3">
          星阁存放已蒸馏的书——每本是一位星宿的立场。点卡查看星笺（蒸馏内容）；要辩论，用「发起辩论」选星宿组合。
        </p>
        <button
          onClick={onStartDebate}
          className="w-full py-2 rounded-lg bg-amber/10 text-amber text-[13px] hover:bg-amber/20 transition-colors duration-150"
        >
          发起辩论（4 个默认模式 / 自定义组合）
        </button>
      </div>
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='book-open' size={14} /> 星书名录
        </div>
        {data.length === 0 && (
          <p className="text-[12px] text-ink-dim">星阁尚空——萃取一本书点亮第一位星宿</p>
        )}
        <div className="space-y-2">
          {data.map((sg) => (
            <button
              key={sg.id}
              onClick={() => openDetail(sg.id)}
              className="group w-full text-left flex items-start gap-3 rounded-xl border border-hairline/60 bg-surface/40 px-3.5 py-3 transition-all duration-200 hover:border-amber/30 hover:bg-surface/70"
            >
              <span
                className="mt-1.5 shrink-0 w-[8px] h-[8px] rounded-full"
                style={{
                  background: sg.confirmed ? '#3ec9b0' : '#e6be78',
                  boxShadow: sg.confirmed
                    ? '0 0 8px rgba(62,201,176,.7)'
                    : '0 0 8px rgba(230,190,120,.6)',
                }}
                title={sg.confirmed ? '已确认' : '待审计'}
              />
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2 flex-wrap">
                  <span className="text-[13.5px] font-medium text-ink">{sg.name}</span>
                  <span className="text-[10px] text-primary/70">{sg.domain}</span>
                </div>
                <p className="text-[11.5px] text-ink-muted leading-relaxed mt-1 line-clamp-2">
                  {sg.stance}
                </p>
                <p className="text-[10px] text-ink-dim mt-1.5 font-mono flex items-center gap-2">
                  <span className="text-amber/80">✦ {sg.claims_count} 张星笺</span>
                  <span>{sg.confirmed ? '已确认' : '待审计'}</span>
                  <span className="opacity-0 group-hover:opacity-100 text-primary transition-opacity duration-150">
                    点击查看 ›
                  </span>
                </p>
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}

export function DistillFeature() {
  const { data: jobs, err, reload } = useFetch(fetchDistillJobs, "distilljobs")
  const [title, setTitle] = useState('')
  const [sageId, setSageId] = useState('')
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [log, setLog] = useState<string[]>([])
  const fileRef = useRef<HTMLInputElement>(null)
  if (err) return <p className="text-[12px] text-ink-dim">任务读取失败（{err}）</p>
  if (!jobs) return <Loading />

  /* 按书名/文件名生成默认星宿标识（sunzi 式小写） */
  const slug = (name: string) =>
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '_')
      .replace(/^_+|_+$/g, '')
      .slice(0, 30) || 'lumen'

  const onFile = (f: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const t = String(reader.result || '')
      if (!title) {
        setTitle(f.name.replace(/\.[^.]+$/, ''))
        if (!sageId) setSageId(slug(f.name.replace(/\.[^.]+$/, '')))
      }
      setText((prev) => prev + (prev ? '\n' : '') + t.slice(0, 1_500_000))
    }
    reader.readAsText(f)
  }

  const start = async (isResume = false, jobId?: string) => {
    if (!isResume && !/^[a-z0-9_-]{2,30}$/.test(sageId.trim())) {
      setLog(['星宿标识需为 2-30 位小写字母/数字/_-（如 sunzi），或留空按书名自动生成'])
      return
    }
    if (!isResume && text.trim().length < 500) {
      setLog(['书文本过短（至少 500 字符）——粘贴完整文本或拾入 .txt/.md 文件'])
      return
    }
    setBusy(true)
    setLog([])
    try {
      await distillBook(
        isResume ? '' : text.trim(),
        sageId.trim() || slug(title || 'lumen'),
        title.trim(),
        (ev) => {
          if (ev.type === 'stage') setLog((l) => [...l, ev.detail])
          else if (ev.type === 'registered') {
            setLog((l) => [
              ...l,
              `星宿已注册（${ev.claims ?? '?'} 张星笺，引证 ${ev.quote_verified ?? '?'}）`,
            ])
            reload()
          } else if (ev.type === 'error')
            setLog((l) => [...l, `错误：${String(ev.detail).slice(0, 100)}`])
        },
        undefined,
        jobId,
      )
    } catch (e) {
      setLog((l) => [...l, `失败：${String(e).slice(0, 100)}`])
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-amber`}>
          <Icon name='distill' size={14} /> 萃取 · 提炼
        </div>
        <p className="text-[11.5px] text-ink-dim leading-relaxed mb-3">
          把一本书蒸馏成星宿——上传 .txt/.md 或粘贴书文本（≥500 字），拾光递归提炼成星笺。
        </p>
        <div className="space-y-2.5">
          <input
            value={title}
            onChange={(e) => {
              setTitle(e.target.value)
              if (!sageId) setSageId(slug(e.target.value))
            }}
            placeholder="书名（如：谈谈方法）——留空按文件名"
            className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-[12.5px] outline-none focus:border-primary/40"
            aria-label="书名"
          />
          <input
            value={sageId}
            onChange={(e) => setSageId(e.target.value)}
            placeholder="星宿标识（小写，如 sunzi；默认按书名自动生成）"
            className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-[12.5px] font-mono outline-none focus:border-primary/40"
            aria-label="星宿标识"
          />
          <div className="flex gap-2">
            <input
              ref={fileRef}
              type="file"
              accept=".txt,.md,.pdf"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
            />
            <button
              onClick={() => fileRef.current?.click()}
              className="px-3 py-2 rounded-lg border border-hairline bg-surface text-[12px] text-ink-muted hover:text-primary hover:border-primary/40 transition-colors duration-150"
            >
              拾入文件（.txt/.md/.pdf）
            </button>
            <span className="text-[10.5px] text-ink-dim self-center">{text.length} 字已载入</span>
          </div>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={6}
            placeholder="或直接粘贴书文本（≥500 字符）…"
            className="w-full rounded-lg border border-hairline bg-surface px-3 py-2 text-[12.5px] leading-relaxed outline-none focus:border-primary/40 resize-y"
            aria-label="书文本"
          />
          <button
            onClick={() => start()}
            disabled={busy}
            className="w-full py-2 rounded-lg bg-primary/15 text-primary text-[13px] hover:bg-primary/25 transition-colors duration-150 disabled:opacity-50"
          >
            {busy ? '蒸馏中…' : '开始萃取'}
          </button>
          {log.length > 0 && (
            <div className="rounded-lg bg-elevated/60 border border-hairline px-3 py-2 text-[11px] text-ink-muted font-mono space-y-0.5 max-h-32 overflow-y-auto">
              {log.map((l, i) => (
                <p key={i}>{l}</p>
              ))}
            </div>
          )}
        </div>
      </div>
      {jobs.length > 0 && (
        <div className={fCard}>
          <div className={`${fTitle} text-primary`}>
            <Icon name='distill' size={14} /> 未完成任务 · {jobs.length}
          </div>
          <div className="space-y-2">
            {jobs.map((j) => (
              <div
                key={j.job_id}
                className="flex items-center gap-2.5 border-b border-hairline/40 last:border-0 pb-2 last:pb-0"
              >
                <span className="flex-1 min-w-0">
                  <span className="block text-[12.5px] text-ink/90 truncate">
                    {j.book_title || '未命名'}
                  </span>
                  <span className="block text-[10px] text-ink-dim font-mono">
                    第 {j.chapters_done}/{j.chapters_total} 章 · {j.created_at?.slice(0, 16)}
                  </span>
                </span>
                <button
                  onClick={() => start(true, j.job_id)}
                  disabled={busy}
                  className="px-2.5 py-1 rounded-md bg-amber/10 text-amber text-[11px] hover:bg-amber/20 transition-colors duration-150 shrink-0"
                >
                  续传
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* 发起辩论（2026-08-26 星图内独立界面，替代旧 DebateView 弹窗——用户：旧框删干净）：
   4 默认模式 / 自定义组合（自选星宿+轮数）+ 问题 → startDebate SSE，
   事件进主对话流（同原 DebateView 行为），界面为星图内 fCard 风格 */
export interface SagePick {
  id: string
  name: string
  domain: string
  confirmed: boolean
}

export function DebateFeature({ onBack }: { onBack: () => void }) {
  const [modes, setModes] = useState<DebateMode[]>([])
  const [step, setStep] = useState<'modes' | 'question'>('modes')
  const [mode, setMode] = useState<DebateMode | null>(null)
  const [question, setQuestion] = useState('')
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState('')
  const abortRef = useRef<AbortController | null>(null)
  const debateIdRef = useRef<string>('')
  const appendDebateEvent = useChatStore((s) => s.appendDebateEvent)
  const sessionId = useChatStore((s) => s.sessionId)
  const setDebateMeta = useChatStore((s) => s.setDebateMeta)

  /* 自定义组合 state */
  const [customOpen, setCustomOpen] = useState(false)
  const [sages, setSages] = useState<SagePick[]>([])
  const [customSages, setCustomSages] = useState<Set<string>>(new Set())
  const [customRounds, setCustomRounds] = useState(2)

  useEffect(() => {
    fetchModes()
      .then(setModes)
      .catch((e) => setErr(`模式加载失败：${(e as Error).message}`))
    listSages()
      .then((d) =>
        setSages(
          d.map((sg) => ({ id: sg.id, name: sg.name, domain: sg.domain, confirmed: sg.confirmed })),
        ),
      )
      .catch(() => {})
  }, [])

  const begin = async (q: string, sageIds: string[], rounds: number) => {
    if (!q.trim()) {
      setErr('请输入你的问题/困境')
      return
    }
    setErr('')
    setRunning(true)
    debateIdRef.current = ''
    setDebateMeta('', q.trim())
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await startDebate(
        q.trim(),
        sageIds.length ? 'cross' : (mode?.id ?? 'cross'),
        rounds,
        (ev: CouncilEvent) => {
          if (ev.type === 'budget') {
            debateIdRef.current = ev.debate_id
            setDebateMeta(ev.debate_id, q.trim())
          } else if (ev.type === 'done' || ev.type === 'stopped') {
            setRunning(false)
          }
          appendDebateEvent(ev)
        },
        ctrl.signal,
        sessionId,
        sageIds.length ? sageIds : undefined,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        appendDebateEvent({ type: 'stopped', debate_id: '' })
        setErr(`会议异常：${(e as Error).message}`)
      }
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  const stop = async () => {
    if (debateIdRef.current) await stopDebate(debateIdRef.current).catch(() => {})
    abortRef.current?.abort()
    setRunning(false)
    appendDebateEvent({ type: 'stopped', debate_id: debateIdRef.current })
  }

  const toggleSage = (id: string) => {
    setCustomSages((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  if (running) {
    return (
      <div className={`${fCard} border-primary/30`}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='users' size={14} /> 研讨进行中…
        </div>
        <p className="text-[12px] text-ink-muted leading-relaxed mb-3">
          辩论内容正在主对话流里呈现，可随时中止。结束后回到这里发起下一次。
        </p>
        <button
          onClick={stop}
          className="w-full py-2 rounded-lg text-[12px] bg-[rgba(230,120,90,0.15)] border border-[rgba(230,120,90,0.4)] text-[#e8a58c] hover:bg-[rgba(230,120,90,0.25)] transition-colors duration-150"
        >
          ■ 中止研讨
        </button>
      </div>
    )
  }

  /* 自定义组合：星宿多选 + 轮数 + 问题 */
  if (customOpen) {
    return (
      <div className="space-y-4">
        <button
          onClick={() => setCustomOpen(false)}
          className="flex items-center gap-1.5 text-[12px] text-ink-dim hover:text-amber transition-colors duration-150"
        >
          <Icon name='arrow-left' size={14} /> 返回模式
        </button>
        <div className={fCard}>
          <div className={`${fTitle} text-amber`}>
            <Icon name='users' size={14} /> 自定义组合
          </div>
          <div className="text-[11px] text-ink-dim mb-2">参会星宿（≥2 位）</div>
          <div className="flex flex-wrap gap-1.5 mb-3">
            {sages.map((sg) => (
              <button
                key={sg.id}
                onClick={() => toggleSage(sg.id)}
                title={sg.domain}
                className={`px-2.5 py-1 rounded-lg border text-[11.5px] transition-colors duration-150 ${
                  customSages.has(sg.id)
                    ? 'border-amber/50 bg-surface text-amber'
                    : 'border-hairline text-ink-muted hover:text-primary'
                }`}
              >
                {sg.name
                  .replace(/《.*?》/g, '')
                  .replace(/·.*/, '')
                  .trim() || sg.name}
              </button>
            ))}
            {sages.length === 0 && (
              <p className="text-[12px] text-ink-dim">星阁暂无星宿——先萃取一本书</p>
            )}
          </div>
          <div className="text-[11px] text-ink-dim mb-1.5">轮数（观点穷尽即止）</div>
          <select
            value={customRounds}
            onChange={(e) => setCustomRounds(Number(e.target.value))}
            className="w-full px-2.5 py-2 rounded-lg bg-surface border border-hairline text-[12px] text-ink outline-none mb-3"
          >
            {[1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n} 轮
              </option>
            ))}
          </select>
          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="你的问题 / 困境 / 想法…"
            rows={3}
            className="w-full px-3 py-2.5 rounded-lg bg-surface border border-hairline text-[13px] text-ink placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 resize-none mb-3"
          />
          {err && <div className="mb-2 text-[11px] text-[rgba(230,120,90,0.9)]">{err}</div>}
          <button
            onClick={() => customSages.size >= 2 && begin(question, [...customSages], customRounds)}
            disabled={customSages.size < 2 || !question.trim()}
            className="w-full py-2 rounded-lg text-[12px] bg-amber/15 border border-amber/40 text-amber hover:bg-amber/25 disabled:opacity-40 transition-colors duration-150"
          >
            发起研讨（自选 {customSages.size} 位）
          </button>
          <div className="text-[10px] text-ink-dim/80 mt-2">
            辩论内容直接进主对话流，可随时中止；结果经你确认后才可记入星尘
          </div>
        </div>
      </div>
    )
  }

  /* 模式选择 / 问题输入 */
  return (
    <div className="space-y-4">
      <div className={`${fCard} border-primary/25`}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='users' size={14} /> 发起辩论
        </div>
        <p className="text-[11.5px] text-ink-dim leading-relaxed mb-3">
          选一个模式，或多位星宿自由组合——听不同视角拆解你的问题。
        </p>
        {step === 'modes' ? (
          <div className="space-y-1.5">
            {modes.map((m) => (
              <button
                key={m.id}
                onClick={() => {
                  setMode(m)
                  setQuestion('')
                  setStep('question')
                }}
                disabled={!m.available}
                title={m.desc}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl border text-[12.5px] transition-colors duration-150 ${
                  !m.available
                    ? 'border-hairline text-ink-dim/70 cursor-not-allowed'
                    : 'border-hairline text-ink/85 hover:border-primary/40 hover:text-primary'
                }`}
              >
                <span>{m.name}</span>
                <span className="text-[10px] text-ink-dim/80">
                  {m.available ? `${m.max_rounds} 轮` : '待扩充'}
                </span>
              </button>
            ))}
            <button
              onClick={() => {
                listSages()
                  .then((d) =>
                    setSages(
                      d.map((sg) => ({
                        id: sg.id,
                        name: sg.name,
                        domain: sg.domain,
                        confirmed: sg.confirmed,
                      })),
                    ),
                  )
                  .catch(() => {})
                setCustomSages(new Set())
                setCustomRounds(2)
                setCustomOpen(true)
              }}
              className="w-full flex items-center justify-between px-3 py-2.5 rounded-xl border border-dashed border-hairline text-[12.5px] text-ink/85 hover:border-amber/40 hover:text-amber transition-colors duration-150"
            >
              <span>自定义组合</span>
              <span className="text-[10px] text-ink-dim/80">自选星宿 · 轮数</span>
            </button>
            {err && <div className="text-[11px] text-[rgba(230,120,90,0.9)] pt-1">{err}</div>}
          </div>
        ) : (
          mode && (
            <div>
              <div className="text-[11.5px] text-primary/80 mb-2">
                {mode.name} · {mode.max_rounds} 轮
              </div>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="你的问题 / 困境 / 想法…"
                rows={3}
                autoFocus
                className="w-full px-3 py-2.5 rounded-lg bg-surface border border-hairline text-[13px] text-ink placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 resize-none"
              />
              {err && <div className="mt-2 text-[11px] text-[rgba(230,120,90,0.9)]">{err}</div>}
              <div className="flex gap-2 mt-3">
                <button
                  onClick={() => {
                    setStep('modes')
                    setMode(null)
                  }}
                  className="px-3 py-1.5 rounded-lg text-[12px] text-ink-dim hover:text-primary transition-colors duration-150"
                >
                  ← 换模式
                </button>
                <button
                  onClick={() => begin(question, [], mode.max_rounds)}
                  disabled={!question.trim()}
                  className="flex-1 py-2 rounded-lg text-[12.5px] bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 transition-colors duration-150"
                >
                  发起研讨
                </button>
              </div>
            </div>
          )
        )}
        <button
          onClick={onBack}
          className="mt-3 flex items-center gap-1.5 text-[12px] text-ink-dim hover:text-amber transition-colors duration-150"
        >
          <Icon name='arrow-left' size={14} /> 星阁
        </button>
      </div>
    </div>
  )
}

/* 运行观测 v2（2026-08-26 重构：分模块点进看详情——用户批评一屏堆 8 区块太长太乱）：
   概览页 = 统计卡 + 系统脉搏 + 6 模块卡；点模块卡 → 星图内详情视图，返回回概览 */
