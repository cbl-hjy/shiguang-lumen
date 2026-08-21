/* 萃光新书小窗（2026-08-19）：拾入书文本 → 后端萃光管线 → 新星宿入库。
   SSE 流式显示阶段进度（拆解/萃光/验证/完成）；长书需几分钟。
   断点续传（2026-08-20）：发起时生成 job_id 存 localStorage；断开后显示"继续萃光"
   （只 POST job_id，后端读存盘 raw 免重传）；"未完成任务"列表可恢复任意中断任务。 */
import { useEffect, useRef, useState } from 'react'
import { distillBook, fetchDistillJobs, type DistillEvent } from '../../api/council'
import Icon from '../ui/Icon'

const LS_KEY = 'lumen_distill_jobs'

export default function DistillModal({ onClose, onRegistered }: {
  onClose: () => void
  onRegistered: (sageId: string) => void
}) {
  const [title, setTitle] = useState('')
  const [sageId, setSageId] = useState('')
  const [text, setText] = useState('')
  const [running, setRunning] = useState(false)
  const [stages, setStages] = useState<DistillEvent[]>([])
  const [err, setErr] = useState('')
  const [interrupted, setInterrupted] = useState(false) // 断点：可续传
  const [jobs, setJobs] = useState<Array<{ job_id: string; sage_id: string; book_title: string; chapters_done: number; chapters_total: number; created_at: string }>>([])
  const [showJobs, setShowJobs] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const jobIdRef = useRef<string | null>(null) // 当前任务的断点 id（localStorage 持久）

  /* 加载未完成任务列表 */
  const loadJobs = async () => {
    try {
      setJobs(await fetchDistillJobs())
    } catch (e) {
      /* B13（2026-08-20）：任务列表加载失败必须可见——续传入口依赖它（列表空=看不到可续传任务） */
      setJobs([])
      setErr(`续传任务读取失败：${(e as Error).message}`)
    }
  }
  useEffect(() => { loadJobs() }, [])

  const onFile = (f: File) => {
    const reader = new FileReader()
    reader.onload = () => {
      const t = String(reader.result || '')
      if (!title) setTitle(f.name.replace(/\.[^.]+$/, ''))
      setText((prev) => prev + (prev ? '\n' : '') + t.slice(0, 1_500_000))
    }
    reader.readAsText(f)
  }

  /* 开始萃光（isResume=true 时用已有 job_id 续传，text 可不填） */
  const begin = async (isResume = false) => {
    if (!isResume && !/^[a-z0-9_-]{2,30}$/.test(sageId.trim())) {
      setErr('星宿标识需为 2-30 位小写字母/数字/_-（如 sunzi）')
      return
    }
    if (!isResume && text.trim().length < 500) {
      setErr('书文本过短（至少 500 字符），请粘贴完整文本或拾入 .txt/.md 文件')
      return
    }
    setErr('')
    setInterrupted(false)
    setStages([])
    setRunning(true)
    const ctrl = new AbortController()
    abortRef.current = ctrl
    try {
      await distillBook(
        isResume ? '' : text.trim(),
        sageId.trim() || 'resume-sage',
        title.trim(),
        (ev) => {
          setStages((prev) => [...prev, ev])
          if (ev.type === 'registered') onRegistered(ev.sage_id)
        },
        ctrl.signal,
        jobIdRef.current ?? undefined,
      )
    } catch (e) {
      if ((e as Error).name !== 'AbortError') {
        setErr(`萃光中断（进度已保存，可点「继续萃光」恢复）`)
        setInterrupted(true)
      }
    } finally {
      setRunning(false)
      abortRef.current = null
    }
  }

  /* 发起新任务：生成 job_id 存 localStorage（断点凭据） */
  const startNew = () => {
    const jid = `j-${Math.random().toString(36).slice(2, 12)}`
    jobIdRef.current = jid
    try {
      const list = JSON.parse(localStorage.getItem(LS_KEY) || '[]') as string[]
      if (!list.includes(jid)) localStorage.setItem(LS_KEY, JSON.stringify([...list, jid]))
    } catch { /* localStorage 不可用不影响萃光 */ }
    void begin(false)
  }

  /* 从任务列表恢复：填入任务信息 + job_id */
  const resumeFromList = (job: { job_id: string; book_title: string }) => {
    jobIdRef.current = job.job_id
    setTitle(job.book_title)
    setShowJobs(false)
    void begin(true)
  }

  const done = stages.find((s) => s.type === 'registered') as DistillEvent & { type: 'registered' } | undefined

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
      <div className="absolute inset-0 bg-black/50" onClick={() => !running && onClose()} aria-label="关闭" />
      <div className="relative w-[420px] max-h-[80vh] overflow-y-auto rounded-xl bg-elevated border border-hairline shadow-2xl p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="flex items-center gap-1.5 text-[13px] font-medium text-primary">
            <Icon name="book" size={15} className="text-primary/80" />
            萃光新书
          </span>
          <button
            onClick={() => !running && onClose()}
            className="p-1 rounded-md text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
            aria-label="关闭"
            disabled={running}
          >
            <Icon name="x" size={14} />
          </button>
        </div>

        {/* 未完成任务列表（断点续传入口） */}
        {jobs.length > 0 && !running && (
          <button
            onClick={() => { setShowJobs((v) => !v); if (!showJobs) loadJobs() }}
            className="w-full mb-2.5 px-2.5 py-1.5 rounded-lg bg-surface border border-hairline text-[11px] text-ink-muted hover:text-primary transition-colors duration-150 text-left"
          >
            ⏸ 未完成任务 {jobs.length} 个{showJobs ? '（收起）' : '（点击续传）'}
          </button>
        )}
        {showJobs && (
          <div className="mb-2.5 px-2.5 py-1.5 rounded-lg bg-surface border border-hairline text-[11px] space-y-1">
            {jobs.length === 0 && <div className="text-ink-dim">没有可续传的任务</div>}
            {jobs.map((j) => (
              <div key={j.job_id} className="flex items-center justify-between gap-2">
                <span className="text-ink/80 truncate">
                  {j.book_title || j.sage_id} · {j.chapters_done}/{j.chapters_total} 章
                </span>
                <button
                  onClick={() => resumeFromList(j)}
                  className="shrink-0 px-2 py-0.5 rounded-md text-[10px] bg-primary/10 border border-primary/30 text-primary/90 hover:bg-primary/20 transition-colors duration-150"
                >
                  继续
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="text-[11px] text-ink-dim mb-1.5">书名</div>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="如：孙子兵法"
          className="w-full px-2.5 py-1.5 rounded-lg bg-surface border border-hairline text-[12px] text-primary placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 mb-2.5"
        />
        <div className="text-[11px] text-ink-dim mb-1.5">星宿标识（小写英文，用作唯一 id）</div>
        <input
          value={sageId}
          onChange={(e) => setSageId(e.target.value)}
          placeholder="如：sunzi"
          className="w-full px-2.5 py-1.5 rounded-lg bg-surface border border-hairline text-[12px] text-primary placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 mb-2.5"
        />

        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[11px] text-ink-dim">书文本（粘贴或拾入；续传可空）</span>
          <label className="px-2 py-1 rounded-md text-[11px] bg-surface border border-hairline text-ink-muted hover:text-primary cursor-pointer transition-colors duration-150">
            拾入文件
            <input
              type="file"
              accept=".txt,.md,.markdown"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && onFile(e.target.files[0])}
            />
          </label>
        </div>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder={`粘贴书的完整文本（≥500 字符）。\n\n长书萃光约需 3-8 分钟，断开后可从断点继续（免重传文本）。`}
          rows={6}
          className="w-full px-2.5 py-2 rounded-lg bg-surface border border-hairline text-[12px] text-primary placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 resize-none mb-2"
        />
        {err && <div className="mb-2 text-[11px] text-[rgba(230,120,90,0.9)]">{err}</div>}

        {/* 阶段进度（SSE 流式） */}
        {stages.length > 0 && (
          <div className="mb-2 px-2.5 py-2 rounded-lg bg-surface border border-hairline text-[11px] text-ink-muted leading-5">
            {stages.map((s, i) => (
              <div key={i}>
                {s.type === 'stage' ? `· ${s.stage}：${s.detail}` : ''}
              </div>
            ))}
            {running && <div className="text-primary/80 mt-1">⏳ 萃光中…</div>}
            {done && (
              <div className="text-[rgba(140,200,150,0.9)] mt-1">
                ✓ 新星宿已入库：{done.claims} 条观点，{done.quote_verified} 条引用逐字命中原文
              </div>
            )}
            {interrupted && !running && (
              <div className="text-amber/90 mt-1">⏸ 进度已保存（已完成章节不重跑）</div>
            )}
          </div>
        )}

        <div className="flex gap-2">
          <button
            onClick={() => !running && onClose()}
            disabled={running}
            className="px-2.5 py-1.5 rounded-lg text-[11px] text-ink-dim hover:text-primary transition-colors duration-150 disabled:opacity-40"
          >
            取消
          </button>
          {interrupted && !running ? (
            <button
              onClick={() => void begin(true)}
              className="flex-1 py-2 rounded-lg text-[12px] bg-primary/15 border border-primary/40 text-primary hover:bg-[rgba(62,201,176,0.25)] transition-colors duration-150"
            >
              继续萃光（从断点）
            </button>
          ) : (
            <button
              onClick={startNew}
              disabled={running || text.trim().length < 500 || !!done}
              className="flex-1 py-2 rounded-lg text-[12px] bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 transition-colors duration-150"
            >
              {running ? '萃光中…' : done ? '已完成' : '开始萃光'}
            </button>
          )}
        </div>
        <div className="text-[10px] text-ink-dim/80 mt-2">
          萃光管线：分章 → 块摘要 → 章摘要 → 星笺 → 忠实度自检（引用逐字命中）+ 三重验证（V1/V2/V3）；支持断点续传
        </div>
      </div>
    </div>
  )
}
