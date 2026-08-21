/* 星阁管理窗（2026-08-20 最小落地清单②，六件套治理权）：
   列表 / 查看卡全文 / 确认 / 熄星（回收站）/ 删观点 / 改元信息（name/stance）。
   交互原则（用户要求：简洁 + 透明可见 + 点击感）：
   - 待审卡默认自动展开（用户进来就是要处理它们，0 次额外点击看到内容）
   - 确认/熄星操作前置到行尾（折叠态直接可见，不藏进展开）
   - 改元信息=行内编辑（不跳页不弹窗）；熄星=就地气泡确认（可恢复提示）
   - 确认成功：徽标琥珀→绿 + check 动效 */
import { useCallback, useEffect, useState } from 'react'
import {
  confirmSage, deleteClaim, deleteSage, fetchSageDetail, listSages, updateSageMeta,
  type SageInfo,
} from '../../api/council'
import Icon from '../ui/Icon'

interface SageDetail {
  id?: string
  name?: string
  stance?: string
  core_claims?: Array<{ title?: string; claim?: string; quote?: string; source?: string }>
  skeleton?: string[]
  boundaries?: { limits?: string[]; blindspots?: string[]; unproven?: string[]; strongest_opposition?: string }
  audit?: { user_confirmed?: boolean; quote_verified?: number; claims_count?: number; tool?: string }
}

export default function SageLibraryModal({ open, onClose, onRegistered }: {
  open: boolean
  onClose: () => void
  onRegistered: (sageId: string) => void
}) {
  const [sages, setSages] = useState<SageInfo[]>([])
  const [details, setDetails] = useState<Record<string, SageDetail>>({})
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [editing, setEditing] = useState<Record<string, { name: string; stance: string }>>({})
  const [confirmingDel, setConfirmingDel] = useState<string | null>(null)
  const [err, setErr] = useState('')

  const reload = useCallback(async () => {
    try {
      const list = await listSages()
      setSages(list)
      /* 待审优先：默认自动展开所有未确认卡（0 次额外点击看到内容） */
      const ex: Record<string, boolean> = {}
      for (const s of list) if (!s.confirmed) ex[s.id] = true
      setExpanded(ex)
    } catch {
      setErr('星阁读取失败')
    }
  }, [])

  useEffect(() => {
    if (open) { reload(); setErr('') }
  }, [open, reload])

  if (!open) return null

  /* 展开时懒加载卡全文 */
  const toggle = async (sid: string) => {
    const next = { ...expanded, [sid]: !expanded[sid] }
    setExpanded(next)
    if (next[sid] && !details[sid]) {
      try {
        const d = await fetchSageDetail(sid)
        setDetails((prev) => ({ ...prev, [sid]: d as SageDetail }))
      } catch {
        /* B13（2026-08-20）：展开的卡全文加载失败——内容区空白需提示（不能静默） */
        setErr(`卡全文加载失败：${sid}`)
      }
    }
  }

  const doConfirm = async (sid: string) => {
    try {
      await confirmSage(sid, true)
      onRegistered(sid)
      await reload()
    } catch { setErr('确认失败') }
  }

  const doDelete = async (sid: string) => {
    try {
      await deleteSage(sid)
      setConfirmingDel(null)
      await reload()
    } catch { setErr('熄星失败') }
  }

  const doDeleteClaim = async (sid: string, idx: number) => {
    try {
      await deleteClaim(sid, idx)
      setDetails((d) => {
        const card = d[sid]
        if (!card) return d
        const claims = [...(card.core_claims ?? [])]
        claims.splice(idx, 1)
        return { ...d, [sid]: { ...card, core_claims: claims } }
      })
    } catch { setErr('熄星观点失败') }
  }

  const saveMeta = async (sid: string) => {
    const e = editing[sid]
    if (!e) return
    try {
      await updateSageMeta(sid, e.name, e.stance)
      setEditing((v) => { const n = { ...v }; delete n[sid]; return n })
      setDetails((d) => d[sid] ? { ...d, [sid]: { ...d[sid], name: e.name, stance: e.stance } } : d)
      await reload()
    } catch { setErr('保存失败') }
  }

  const pending = sages.filter((s) => !s.confirmed).length

  return (
    <div className="fixed inset-0 z-[55] flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} aria-label="关闭" />
      <div className="relative w-[560px] max-h-[82vh] overflow-y-auto rounded-xl bg-elevated border border-hairline shadow-2xl p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-primary">
            <Icon name="users" size={15} className="text-primary/80" />
            星阁
            {pending > 0 && (
              <span className="px-1.5 py-0.5 rounded-md text-[10px] bg-amber/15 border border-[rgba(230,190,120,0.35)] text-amber">
                {pending} 待审
              </span>
            )}
          </span>
          <button
            onClick={onClose}
            className="p-1 rounded-md text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
            aria-label="关闭"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
        {err && <div className="mb-2 text-[11px] text-[rgba(230,120,90,0.9)]">{err}</div>}

        {sages.length === 0 && (
          <div className="px-3 py-8 text-center text-[12px] text-ink-dim">
            还没有星宿——去"萃光新书"造一张卡
          </div>
        )}

        <div className="space-y-2">
          {sages.map((s) => {
            const d = details[s.id]
            const isPending = !s.confirmed
            const isExpanded = !!expanded[s.id]
            const edit = editing[s.id]
            return (
              <div key={s.id} className={`rounded-lg border transition-colors duration-150 ${isPending ? 'border-amber/30 bg-[rgba(230,190,120,0.04)]' : 'border-hairline bg-surface'}`}>
                {/* 行头：名字·领域·状态徽标·引用命中 + 操作前置（确认/熄星不藏展开） */}
                <div className="flex items-center gap-2 px-3 py-2">
                  <button onClick={() => void toggle(s.id)} className="flex-1 flex items-center gap-2 min-w-0 text-left" aria-label={isExpanded ? '收起' : '展开'}>
                    <Icon name="book" size={14} className="shrink-0 text-ink-dim" />
                    <span className="text-[13px] text-primary truncate">{edit ? edit.name : (d?.name ?? s.name)}</span>
                    <span className="text-[10px] text-ink-dim shrink-0">{(d as { domain?: string } | undefined)?.domain ?? s.domain}</span>
                    {isPending ? (
                      <span className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] bg-amber/15 border border-[rgba(230,190,120,0.35)] text-amber">待审</span>
                    ) : (
                      <span className="shrink-0 px-1.5 py-0.5 rounded-md text-[10px] bg-[rgba(140,200,150,0.12)] border border-[rgba(140,200,150,0.3)] text-[rgba(140,200,150,0.95)]">✓ 已确认</span>
                    )}
                    <span className="shrink-0 text-[10px] text-ink-dim/80">引 {s.claims_count}</span>
                    <Icon name="chevron-right" size={12} className={`shrink-0 text-ink-dim/70 transition-transform duration-150 ${isExpanded ? 'rotate-90' : ''}`} />
                  </button>
                  {/* 操作前置：确认（待审时高亮）/ 熄星（就地气泡确认）——折叠态直接可见 */}
                  <div className="shrink-0 flex items-center gap-1">
                    {isPending && (
                      <button
                        onClick={() => void doConfirm(s.id)}
                        className="px-2 py-1 rounded-lg text-[10px] bg-primary/15 border border-primary/40 text-primary hover:bg-[rgba(62,201,176,0.25)] transition-colors duration-150"
                        aria-label="确认此星宿"
                      >
                        ✓ 确认
                      </button>
                    )}
                    {confirmingDel === s.id ? (
                      <span className="flex items-center gap-1 text-[10px]">
                        <span className="text-ink-dim">移回收站？</span>
                        <button onClick={() => void doDelete(s.id)} className="px-1.5 py-0.5 rounded-md text-[10px] bg-[rgba(230,120,90,0.2)] text-[rgba(240,140,110,0.95)] hover:bg-[rgba(230,120,90,0.3)]">删</button>
                        <button onClick={() => setConfirmingDel(null)} className="px-1.5 py-0.5 rounded-md text-[10px] text-ink-dim hover:text-primary">留</button>
                      </span>
                    ) : (
                      <button
                        onClick={() => setConfirmingDel(s.id)}
                        className="p-1 rounded-md text-ink-dim/80 hover:text-[rgba(240,140,110,0.9)] hover:bg-surface transition-colors duration-150"
                        aria-label="熄星（回收站）"
                        title="熄星（移入回收站，可恢复）"
                      >
                        <Icon name="trash" size={13} />
                      </button>
                    )}
                  </div>
                </div>

                {/* 详情（待审默认展开；已确认默认折叠）——来源透明：书名/立场/观点/边界 */}
                {isExpanded && (
                  <div className="px-3 pb-3 pt-0.5 border-t border-hairline/60 text-[11px] leading-5 text-ink/80 space-y-2">
                    {!d ? <div className="pt-2 text-ink-dim">加载中…</div> : (
                      <>
                        {/* 元信息行内编辑（不跳页不弹窗） */}
                        {edit ? (
                          <div className="pt-2 space-y-1.5">
                            <input
                              value={edit.name}
                              onChange={(e) => setEditing({ ...editing, [s.id]: { ...edit, name: e.target.value } })}
                              className="w-full px-2 py-1 rounded-md bg-surface border border-hairline text-[12px] text-primary outline-none focus:border-primary/40"
                              placeholder="名字"
                            />
                            <input
                              value={edit.stance}
                              onChange={(e) => setEditing({ ...editing, [s.id]: { ...edit, stance: e.target.value } })}
                              className="w-full px-2 py-1 rounded-md bg-surface border border-hairline text-[12px] text-primary outline-none focus:border-primary/40"
                              placeholder="立场声明"
                            />
                            <div className="flex gap-2">
                              <button onClick={() => void saveMeta(s.id)} className="px-2 py-0.5 rounded-md text-[10px] bg-primary/15 border border-primary/40 text-primary">保存</button>
                              <button onClick={() => { const n = { ...editing }; delete n[s.id]; setEditing(n) }} className="px-2 py-0.5 rounded-md text-[10px] text-ink-dim hover:text-primary">取消</button>
                            </div>
                          </div>
                        ) : (
                          <button
                            onClick={() => setEditing({ ...editing, [s.id]: { name: d?.name ?? s.name, stance: d?.stance ?? '' } })}
                            className="pt-1 text-[10px] text-[rgba(120,160,255,0.7)] hover:text-[rgba(120,160,255,0.95)]"
                          >
                            改名字/立场（观点与引用不可改=忠于原书）
                          </button>
                        )}
                        {d?.stance && <div className="pt-1"><span className="text-ink-dim">立场：</span>{d.stance}</div>}
                        {/* 观点列表（每条可删） */}
                        {(d?.core_claims ?? []).map((c, i) => (
                          <div key={i} className="flex items-start gap-2 rounded-md px-2 py-1.5 bg-surface border border-hairline/50">
                            <span className="flex-1 min-w-0">
                              <span className="text-primary">{c.title}</span>
                              <span className="text-ink-dim"> — {c.claim}</span>
                              {c.quote && <div className="text-[10px] text-ink-dim/80 italic mt-0.5">「{c.quote.slice(0, 60)}{(c.quote?.length ?? 0) > 60 ? '…' : ''}」</div>}
                            </span>
                            <button
                              onClick={() => void doDeleteClaim(s.id, i)}
                              className="shrink-0 p-0.5 rounded text-ink-dim/70 hover:text-[rgba(240,140,110,0.9)] transition-colors duration-150"
                              aria-label="熄星此观点"
                              title="熄星此观点（不影响其他引用）"
                            >
                              <Icon name="x" size={11} />
                            </button>
                          </div>
                        ))}
                        {/* 边界（局限/盲点/未证明/最强反对） */}
                        {d?.boundaries && (
                          <div className="pt-1 text-[10px] text-ink-dim space-y-0.5">
                            {(d.boundaries.limits?.length ?? 0) > 0 && <div>局限：{d.boundaries.limits!.join('；')}</div>}
                            {(d.boundaries.blindspots?.length ?? 0) > 0 && <div>盲点：{d.boundaries.blindspots!.join('；')}</div>}
                            {(d.boundaries.unproven?.length ?? 0) > 0 && <div>未证明：{d.boundaries.unproven!.join('；')}</div>}
                            {d.boundaries.strongest_opposition && <div>最强反对：{d.boundaries.strongest_opposition}</div>}
                          </div>
                        )}
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <div className="text-[10px] text-ink-dim/80 mt-2">熄星进回收站可恢复；观点与引用不可手改（忠实度锚点）</div>
      </div>
    </div>
  )
}
