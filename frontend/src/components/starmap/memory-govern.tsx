// 从 StarMap.tsx 纯移动切割（Phase 4 A-1，2026-08-29）——零逻辑改动，仅搬家 + import 修正
import { type GovData, type GovEntry, deleteMemoryEntryById, editMemoryEntryById, fetchMemoryEntries, fetchMemoryProfile, fetchMemoryTrash } from '../../api/memory'
import Icon from '../ui/Icon'
import { EditModal, fCard, fTitle, useFetch } from './shared'
import { useState } from 'react'

export const GOV_REASONS = [
  { v: 'user_request', label: '用户主动删除' },
  { v: 'stale', label: '已过时（stale）' },
  { v: 'low-signal', label: '低价值冗余（low-signal）' },
  { v: 'contradicted', label: '与记忆矛盾（contradicted）' },
  { v: 'superseded', label: '被更新取代（superseded）' },
]

export function MemoryGovernFeature() {
  const [cat, setCat] = useState('')
  const [editing, setEditing] = useState<GovEntry | null>(null)
  const [editText, setEditText] = useState('')
  const [deleting, setDeleting] = useState<GovEntry | null>(null)
  const [delReason, setDelReason] = useState('user_request')
  const [tab, setTab] = useState<'entries' | 'profile' | 'trash'>('entries')
  const [busy, setBusy] = useState(false)
  const [profile, setProfile] = useState('')
  const [trash, setTrash] = useState('')
  const [msg, setMsg] = useState('')

  const gov = useFetch<GovData>(() => fetchMemoryEntries(cat))

  const openEdit = (e: GovEntry) => {
    setEditing(e)
    setEditText(e.content)
  }
  const saveEdit = async () => {
    if (!editing) return
    setBusy(true)
    const r = await editMemoryEntryById(editing.id, editText)
    setBusy(false)
    setMsg(r.ok ? '已修正' : r.msg)
    setEditing(null)
    gov.reload()
  }
  const confirmDelete = async () => {
    if (!deleting) return
    setBusy(true)
    const r = await deleteMemoryEntryById(deleting.id, delReason)
    setBusy(false)
    setMsg(r.ok ? '已删除（进回收站，可恢复）' : r.msg)
    setDeleting(null)
    gov.reload()
  }
  const loadSide = async (t: 'profile' | 'trash') => {
    setTab(t)
    if (t === 'profile') {
      // 2026-08-28：后端返回明确文案（画像未生成/读取失败）；'' 只可能来自网络失败——不再假"加载中"
      const p = await fetchMemoryProfile()
      setProfile(p || '(画像读取失败——请检查网络后重试)')
    } else setTrash(await fetchMemoryTrash())
  }

  const d = gov.data
  const entries = d?.entries ?? []

  return (
    <div className="space-y-4">
      <div className={fCard}>
        <div className={`${fTitle} text-primary`}>
          <Icon name='shield' size={14} /> 记忆治理
        </div>
        <p className="text-[11.5px] text-ink-dim leading-relaxed mt-1">
          你对记忆的掌控权：每条记忆可查看、修正、删除（带理由，进回收站可恢复）。
          治理操作全部留痕（变更日志可见）——本地产品的信任底线。
        </p>
      </div>

      {/* 统计 + 类别过滤 */}
      <div className={`${fCard} !py-3`}>
        <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
          <button
            onClick={() => {
              setCat('')
              gov.reload()
            }}
            className={`px-2.5 py-1 rounded-full border transition-colors duration-150 ${
              cat === ''
                ? 'border-primary/40 bg-primary/10 text-primary'
                : 'border-hairline text-ink-dim hover:text-ink-muted'
            }`}
          >
            全部 {d?.count ?? 0}
          </button>
          {Object.entries(d?.categories ?? {}).map(([c, n]) => (
            <button
              key={c}
              onClick={() => {
                setCat(c === cat ? '' : c)
                gov.reload()
              }}
              className={`px-2.5 py-1 rounded-full border transition-colors duration-150 ${
                cat === c
                  ? 'border-primary/40 bg-primary/10 text-primary'
                  : 'border-hairline text-ink-dim hover:text-ink-muted'
              }`}
            >
              {c} {n}
            </button>
          ))}
          <span className="ml-auto text-[10px] text-ink-dim/60">修正/删除后画像会自动重提炼</span>
        </div>
      </div>

      {/* 标签切换：条目 / 画像 / 回收站 */}
      <div className="flex items-center gap-2 text-[12px]">
        {(
          [
            ['entries', '记忆条目'],
            ['profile', '画像'],
            ['trash', '回收站'],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => (k === 'entries' ? setTab('entries') : loadSide(k))}
            className={`px-3 py-1.5 rounded-lg border transition-colors duration-150 ${
              tab === k
                ? 'border-amber/40 bg-amber/8 text-amber'
                : 'border-hairline text-ink-dim hover:text-ink-muted'
            }`}
          >
            {label}
          </button>
        ))}
        {msg && <span className="ml-auto text-[11px] text-amber">{msg}</span>}
      </div>

      {tab === 'entries' && (
        <div className="space-y-2">
          {entries.length === 0 && (
            <p className="text-[12px] text-ink-dim">暂无记忆条目{cat ? `（${cat}）` : ''}</p>
          )}
          {entries.map((e) => (
            <div key={e.id} className={`${fCard} !py-2.5 group/row`}>
              <div className="flex items-start gap-3">
                <span
                  className={`shrink-0 mt-0.5 px-1.5 py-0.5 rounded text-[10px] border ${
                    e.category === '闪光'
                      ? 'border-amber/40 text-amber bg-amber/8'
                      : e.category === '困惑'
                        ? 'border-sky/40 text-sky bg-sky/8'
                        : 'border-hairline text-ink-dim'
                  }`}
                >
                  {e.category}
                </span>
                <p className="flex-1 text-[12.5px] text-ink leading-relaxed break-words min-w-0">
                  {e.content}
                </p>
                <div className="flex shrink-0 items-center gap-1">
                  <button
                    onClick={() => openEdit(e)}
                    className="p-1.5 rounded-md text-ink-dim opacity-0 group-hover/row:opacity-100 hover:text-amber transition-all duration-150"
                    aria-label="修正记忆"
                    title="修正这条记忆"
                  >
                    <Icon name='flame' size={13} />
                  </button>
                  <button
                    onClick={() => setDeleting(e)}
                    className="p-1.5 rounded-md text-ink-dim opacity-0 group-hover/row:opacity-100 hover:text-red-400 transition-all duration-150"
                    aria-label="删除记忆"
                    title="删除这条记忆（进回收站）"
                  >
                    <Icon name='x' size={13} />
                  </button>
                </div>
              </div>
              <div className="flex items-center gap-3 mt-1.5 text-[10px] text-ink-dim/70 font-mono">
                <span>{e.created_at}</span>
                <span>imp={e.importance}</span>
                <span>src={e.source}</span>
                <span>S={e.strength ?? 1}</span>
                {e.updated_at && <span className="text-ink-dim/50">改于 {e.updated_at}</span>}
              </div>
            </div>
          ))}
        </div>
      )}

      {tab === 'profile' && (
        <div className={`${fCard}`}>
          <div className="text-[11px] text-ink-dim mb-2">
            画像 = 跨会话综合的稳定判断（模型自动维护、含绝对化词自动拦截；改画像请直接对话里说）。
          </div>
          <pre className="whitespace-pre-wrap text-[12px] text-ink leading-relaxed font-mono">
            {profile || '(加载中…)'}
          </pre>
        </div>
      )}

      {tab === 'trash' && (
        <div className={`${fCard}`}>
          <div className="text-[11px] text-ink-dim mb-2">
            回收站（最近删除，可人工恢复——直接把内容放回对话让拾光重新记住）
          </div>
          <pre className="whitespace-pre-wrap text-[11.5px] text-ink-dim leading-relaxed font-mono max-h-72 overflow-y-auto">
            {trash || '(回收站为空)'}
          </pre>
        </div>
      )}

      {/* 修正弹窗（复用共享 EditModal） */}
      {editing && (
        <EditModal
          title="修正记忆条目"
          value={editText}
          onChange={setEditText}
          onSave={saveEdit}
          onCancel={() => setEditing(null)}
          busy={busy}
        />
      )}

      {/* 删除确认（带 reason） */}
      {deleting && (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center animate-fade-in"
          role="dialog"
          aria-modal="true"
        >
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setDeleting(null)}
            aria-label="关闭"
          />
          <div className="relative w-[min(420px,92vw)] rounded-2xl border border-hairline bg-elevated shadow-2xl p-5">
            <div className="text-[13px] font-medium text-amber mb-1">删除记忆</div>
            <p className="text-[12px] text-ink-dim leading-relaxed mb-3 line-clamp-3">
              {deleting.content}
            </p>
            <div className="text-[11px] text-ink-dim mb-1.5">
              删除理由（审计留痕，进回收站可恢复）：
            </div>
            <select
              value={delReason}
              onChange={(e) => setDelReason(e.target.value)}
              className="w-full px-2.5 py-1.5 rounded-lg border border-hairline bg-surface text-[12px] text-ink outline-none focus:border-primary/40 mb-4"
            >
              {GOV_REASONS.map((r) => (
                <option key={r.v} value={r.v}>
                  {r.label}
                </option>
              ))}
            </select>
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => setDeleting(null)}
                className="px-3 py-1.5 rounded-lg border border-hairline text-[12px] text-ink-dim hover:text-ink-muted transition-colors duration-150"
              >
                取消
              </button>
              <button
                onClick={confirmDelete}
                disabled={busy}
                className="px-3 py-1.5 rounded-lg bg-red-500/15 border border-red-500/30 text-[12px] text-red-400 hover:bg-red-500/25 transition-colors duration-150"
              >
                {busy ? '删除中…' : '确认删除'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
