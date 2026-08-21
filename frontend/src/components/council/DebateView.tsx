/* 问星触发面板（M3 定稿 v3——2026-08-19 用户纠偏：不做顶部常驻条，按钮上方 popover）。
   交互：点聊天框"会议"按钮 → 按钮上方弹出 popover：4 个默认模式 + 自定义组合。
   - 默认模式：两步（选模式 → 就地输问题 → 发起），零配置
   - 自定义组合：弹独立配置小窗（星宿多选 + 轮数 + 问题）——自由定义的入口
   发起后事件进主消息流；popover 转"研讨中 + 中止"态，结束自动关闭。 */
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchModes, listSages, startDebate, stopDebate,
  type CouncilEvent, type DebateMode, type SageInfo,
} from '../../api/council'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'
import DistillModal from './DistillModal'

interface SageView {
  id: string
  name: string
  domain: string
  confirmed: boolean
}

export default function DebateView({ onClose, onOpenLibrary }: { onClose: () => void; onOpenLibrary: () => void }) {
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

  /* 自定义小窗 state */
  const [customOpen, setCustomOpen] = useState(false)
  const [sages, setSages] = useState<SageView[]>([])
  /* 待审计数（入口徽标——透明可见：有活一眼看到，2026-08-20） */
  const pendingCount = sages.filter((s) => !s.confirmed).length
  const [customSages, setCustomSages] = useState<Set<string>>(new Set())
  const [customRounds, setCustomRounds] = useState(2)

  /* 萃光小窗 state */
  const [distillOpen, setDistillOpen] = useState(false)

  const loadModes = useCallback(async () => {
    try {
      setModes(await fetchModes())
    } catch (e) {
      setErr(`模式加载失败：${(e as Error).message}`)
    }
  }, [])

  const loadSageList = useCallback(async () => {
    try {
      const data = await listSages()
      setSages(data.map((s: SageInfo) => ({ id: s.id, name: s.name, domain: s.domain, confirmed: s.confirmed })))
    } catch (e) {
      /* B13（2026-08-20）：列表加载失败必须可见——空列表≠没卡，用户分不清 */
      setErr(`星阁读取失败：${(e as Error).message}`)
    }
  }, [])

  useEffect(() => {
    loadModes()
  }, [loadModes])

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
        sageIds.length ? 'cross' : mode?.id ?? 'cross', /* 自定义用跨领域圆桌规则 + 自选星宿 */
        rounds,
        (ev: CouncilEvent) => {
          if (ev.type === 'budget') {
            debateIdRef.current = ev.debate_id
            setDebateMeta(ev.debate_id, q.trim())
          } else if (ev.type === 'done' || ev.type === 'stopped') {
            onClose() /* 结束自动关闭 popover */
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

  const pickMode = (m: DebateMode) => {
    setMode(m)
    setQuestion('')
    setStep('question')
  }

  const openCustom = () => {
    loadSageList()
    setCustomSages(new Set())
    setCustomRounds(2)
    setCustomOpen(true)
  }

  const toggleSage = (id: string) => {
    setCustomSages((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  return (
    <>
      {/* 按钮上方 popover（默认路径：模式 → 问题 → 发起） */}
      {!customOpen && (
        <div className="fixed bottom-[92px] right-4 z-50 w-[330px] rounded-xl bg-elevated border border-hairline shadow-2xl animate-msg-in">
          <div className="flex items-center justify-between px-3.5 pt-3 pb-2">
            <span className="flex items-center gap-1.5 text-[12px] font-medium text-primary">
              <Icon name="users" size={14} className="text-primary/80" />
              问星
            </span>
            <button
              onClick={onClose}
              className="p-1 rounded-md text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
              aria-label="关闭"
            >
              <Icon name="x" size={14} />
            </button>
          </div>

          {err && <div className="mx-3.5 mb-2 px-2.5 py-1.5 rounded-lg bg-[rgba(230,120,90,0.1)] text-[11px] text-[#e8a58c]">{err}</div>}

          {step === 'modes' && !running && (
            <div className="px-3.5 pb-3.5 space-y-1">
              {modes.map((m) => (
                <button
                  key={m.id}
                  onClick={() => m.available && pickMode(m)}
                  disabled={!m.available}
                  title={m.desc}
                  className={`w-full flex items-center justify-between px-2.5 py-2 rounded-lg border text-[12px] transition-colors duration-150 ${
                    !m.available
                      ? 'border-hairline text-ink-dim/70 cursor-not-allowed'
                      : 'border-hairline text-ink/80 hover:border-primary/40 hover:text-primary'
                  }`}
                >
                  <span>{m.name}</span>
                  <span className="text-[10px] text-ink-dim/80">{m.available ? `${m.max_rounds} 轮` : '待扩充'}</span>
                </button>
              ))}
              <button
                onClick={openCustom}
                className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg border border-dashed border-hairline text-[12px] text-ink/80 hover:border-primary/40 hover:text-primary transition-colors duration-150"
              >
                <span>自定义组合</span>
                <span className="text-[10px] text-ink-dim/80">自选星宿</span>
              </button>
              <button
                onClick={() => setDistillOpen(true)}
                className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg border border-dashed border-hairline text-[12px] text-ink/80 hover:border-primary/40 hover:text-primary/90 transition-colors duration-150"
              >
                <span className="flex items-center gap-1.5">
                  <Icon name="distill" size={13} />
                  萃光新书
                </span>
                <span className="text-[10px] text-ink-dim/80">拾入书 → 生成星宿</span>
              </button>
              {/* 星阁入口（带待审计数徽标——2026-08-20 治理权六件套） */}
              <button
                onClick={onOpenLibrary}
                className="w-full flex items-center justify-between px-2.5 py-2 rounded-lg border border-dashed border-hairline text-[12px] text-ink/80 hover:border-primary/40 hover:text-primary/90 transition-colors duration-150"
              >
                <span className="flex items-center gap-1.5">
                  <Icon name="pavilion" size={13} />
                  星阁
                  {pendingCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded-md text-[10px] bg-amber/15 border border-[rgba(230,190,120,0.35)] text-amber">
                      {pendingCount} 待审
                    </span>
                  )}
                </span>
                <span className="text-[10px] text-ink-dim/80">管理 / 确认 / 熄星</span>
              </button>
            </div>
          )}

          {step === 'question' && mode && !running && (
            <div className="px-3.5 pb-3.5">
              <div className="text-[11px] text-primary/80 mb-2">{mode.name} · {mode.max_rounds} 轮</div>
              <textarea
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="你的问题 / 困境 / 想法…"
                rows={2}
                autoFocus
                className="w-full px-2.5 py-2 rounded-lg bg-surface border border-hairline text-[12px] text-primary placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 resize-none"
              />
              <div className="flex gap-2 mt-2">
                <button
                  onClick={() => {
                    setStep('modes')
                    setMode(null)
                  }}
                  className="px-2.5 py-1.5 rounded-lg text-[11px] text-ink-dim hover:text-primary transition-colors duration-150"
                >
                  ← 换模式
                </button>
                <button
                  onClick={() => begin(question, [], mode.max_rounds)}
                  disabled={!question.trim()}
                  className="flex-1 py-1.5 rounded-lg text-[12px] bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 transition-colors duration-150"
                >
                  发起研讨
                </button>
              </div>
            </div>
          )}

          {running && (
            <div className="px-3.5 pb-3.5">
              <div className="text-[12px] text-primary mb-2">研讨进行中…（内容在主对话流里）</div>
              <button
                onClick={stop}
                className="w-full py-1.5 rounded-lg text-[12px] bg-[rgba(230,120,90,0.15)] border border-[rgba(230,120,90,0.4)] text-[#e8a58c] hover:bg-[rgba(230,120,90,0.25)] transition-colors duration-150"
              >
                ■ 中止研讨
              </button>
            </div>
          )}
        </div>
      )}

      {/* 自定义组合小窗（自由定义入口：星宿多选 + 轮数 + 问题） */}
      {customOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-black/50" onClick={() => setCustomOpen(false)} aria-label="关闭" />
          <div className="relative w-[360px] max-h-[70vh] overflow-y-auto rounded-xl bg-elevated border border-hairline shadow-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <span className="text-[13px] font-medium text-primary">自定义组合</span>
              <button
                onClick={() => setCustomOpen(false)}
                className="p-1 rounded-md text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
                aria-label="关闭"
              >
                <Icon name="x" size={14} />
              </button>
            </div>
            <div className="text-[11px] text-ink-dim mb-1.5">参会星宿（≥2 位）</div>
            <div className="flex flex-wrap gap-1.5 mb-3">
              {sages.map((s) => (
                <button
                  key={s.id}
                  onClick={() => toggleSage(s.id)}
                  title={s.domain}
                  className={`px-2 py-1 rounded-lg border text-[11px] transition-colors duration-150 ${
                    customSages.has(s.id)
                      ? 'border-[rgba(120,160,255,0.5)] bg-surface text-primary'
                      : 'border-hairline text-ink-muted hover:text-primary'
                  }`}
                >
                  {s.name.replace(/《.*?》/g, '').replace(/·.*/, '').trim() || s.name}
                </button>
              ))}
            </div>
            <div className="text-[11px] text-ink-dim mb-1.5">轮数（观点穷尽即止）</div>
            <select
              value={customRounds}
              onChange={(e) => setCustomRounds(Number(e.target.value))}
              className="w-full px-2 py-1.5 rounded-lg bg-surface border border-hairline text-[12px] text-primary outline-none mb-3"
            >
              <option value={1}>1 轮</option>
              <option value={2}>2 轮</option>
              <option value={3}>3 轮</option>
              <option value={4}>4 轮</option>
            </select>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="你的问题 / 困境 / 想法…"
              rows={2}
              className="w-full px-2.5 py-2 rounded-lg bg-surface border border-hairline text-[12px] text-primary placeholder-[rgba(236,233,225,0.35)] outline-none focus:border-primary/40 resize-none mb-3"
            />
            {err && <div className="mb-2 text-[11px] text-[rgba(230,120,90,0.9)]">{err}</div>}
            <button
              onClick={() => customSages.size >= 2 && begin(question, [...customSages], customRounds)}
              disabled={customSages.size < 2 || !question.trim()}
              className="w-full py-2 rounded-lg text-[12px] bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 transition-colors duration-150"
            >
              发起研讨（自选 {customSages.size} 位）
            </button>
            <div className="text-[10px] text-ink-dim/80 mt-2">
              辩论内容直接进主对话流，可随时中止；结果经你确认后才可记入星尘
            </div>
          </div>
        </div>
      )}
      {/* 萃光新书小窗 */}
      {distillOpen && (
        <DistillModal
          onClose={() => setDistillOpen(false)}
          onRegistered={() => {
            /* 新星宿入库：刷新自定义列表，提示用户去自定义组合里选它 */
            loadSageList()
            setDistillOpen(false)
            openCustom()
          }}
        />
      )}
    </>
  )
}
