import { useCallback, useEffect, useState } from 'react'
import { deleteKbDoc, listKbDocs, renameKbDoc, type KbDocument } from '../../api/kb'
import Icon from '../ui/Icon'

/* 知识库文档治理权（最小落地清单⑤，2026-08-20）：
   可见（文档列表：标题/大小/日期/向量数）+ 可改名（行内输入）+ 可熄星（就地气泡确认，移回收站可恢复） */
function fmtSize(n: number): string {
  if (n < 1024) return `${n}B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}KB`
  return `${(n / 1024 / 1024).toFixed(1)}MB`
}

export default function KbDocList() {
  const [docs, setDocs] = useState<KbDocument[] | null>(null)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [confirmDel, setConfirmDel] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  const reload = useCallback(() => {
    listKbDocs()
      .then(setDocs)
      .catch(() => setDocs([]))
  }, [])
  useEffect(reload, [reload])

  const doRename = async () => {
    if (!renaming) return
    const t = draft.trim()
    if (!t) return
    const r = await renameKbDoc(renaming, t)
    setMsg(r.msg ?? (r.ok ? '已改名' : '失败'))
    setRenaming(null)
    reload()
    setTimeout(() => setMsg(null), 2000)
  }

  const doDelete = async () => {
    if (!confirmDel) return
    const r = await deleteKbDoc(confirmDel)
    setMsg(r.msg ?? (r.ok ? '已移入回收站' : '失败'))
    setConfirmDel(null)
    reload()
    setTimeout(() => setMsg(null), 2000)
  }

  if (docs === null) {
    return (
      <div className="rounded-lg bg-elevated p-3 animate-pulse">
        <div className="h-3 w-20 bg-white/10 rounded" />
      </div>
    )
  }
  if (docs.length === 0) {
    return (
      <div className="flex items-center gap-2 py-3">
        <span className="empty-light shrink-0" />
        <span className="text-[12px] text-ink-dim leading-relaxed">
          知识库还没有文档——上传笔记/资料后，拾光会为它们建星图检索。
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-2">
      {docs.map((d) => (
        <div key={d.id} className="rounded-lg border border-hairline bg-surface p-2.5">
          <div className="flex items-center gap-2">
            <Icon name="file" size={13} className="text-primary/70 shrink-0" />
            {renaming === d.id ? (
              <input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && doRename()}
                autoFocus
                className="flex-1 min-w-0 text-[12px] px-1.5 py-0.5 rounded bg-elevated border border-hairline text-ink outline-none focus:border-primary"
              />
            ) : (
              <span className="flex-1 min-w-0 text-[12px] text-ink truncate" title={d.title}>
                {d.title}
              </span>
            )}
            {confirmDel === d.id ? (
              <span className="flex items-center gap-1 shrink-0">
                <button
                  onClick={doDelete}
                  className="text-[11px] px-1.5 py-0.5 rounded bg-error/15 text-error"
                >
                  移入回收站
                </button>
                <button
                  onClick={() => setConfirmDel(null)}
                  className="text-[11px] px-1 py-0.5 text-ink-dim"
                >
                  取消
                </button>
              </span>
            ) : (
              <span className="flex items-center gap-1 shrink-0">
                <button
                  onClick={() => {
                    setRenaming(d.id)
                    setDraft(d.title)
                  }}
                  className="p-1 rounded text-ink-dim hover:text-primary hover:bg-elevated transition-colors duration-150"
                  title="改名"
                  aria-label={`改名 ${d.title}`}
                >
                  <Icon name="wrench" size={12} />
                </button>
                <button
                  onClick={() => setConfirmDel(d.id)}
                  className="p-1 rounded text-ink-dim hover:text-error hover:bg-elevated transition-colors duration-150"
                  title="移入回收站（可恢复）"
                  aria-label={`熄星 ${d.title}`}
                >
                  <Icon name="trash" size={12} />
                </button>
              </span>
            )}
          </div>
          <div className="mt-1 text-[10px] text-ink-dim flex gap-2">
            <span>{fmtSize(d.size)}</span>
            <span>{d.vectors > 0 ? `${d.vectors} 个切片` : '未索引'}</span>
            <span className="ml-auto">{new Date(d.mtime * 1000).toLocaleDateString()}</span>
          </div>
        </div>
      ))}
      {msg && <div className="text-[11px] text-ink-muted text-center">{msg}</div>}
    </div>
  )
}
