/* 辩论事件消息渲染（M3，UI 简洁版 2026-08-19 grill-me 确认）：
   - 星宿发言：默认第一条展开，其余折叠成一行标题（点击展开）；左线轻样式不占整卡
   - 预算：一行小字（不单独占卡）
   - 综合报告：两级展示——默认只显示 actionable + 记入星尘按钮，共识/分歧/互补/未解答折叠 */
import { useState } from 'react'
import type { CouncilEvent } from '../../api/council'
import { memorizeReport } from '../../api/council'
import { useChatStore } from '../../store/chatStore'
import Icon from '../ui/Icon'

/* ---------- 星宿发言（可折叠 + 左线轻样式） ---------- */
function TurnCard({ ev, isFirst }: {
  ev: Extract<CouncilEvent, { type: 'turn' }>
  isFirst: boolean
}) {
  const [open, setOpen] = useState(isFirst) /* 第一条发言默认展开，其余折叠 */
  return (
    <div className={open ? 'border-l-2 border-[rgba(62,201,176,0.35)] pl-3' : 'border-l-2 border-transparent pl-3'}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between text-left py-1 group"
        aria-label={open ? '折叠发言' : '展开发言'}
      >
        <span className="flex items-center gap-1.5 min-w-0">
          <Icon name="users" size={12} className="text-primary/70 shrink-0" />
          <span className="text-[12px] font-medium text-primary/90 truncate">
            {ev.sage_name.replace(/《.*?》/g, '').replace(/·.*/, '').trim()}
          </span>
          <span className="text-[10px] text-ink-dim shrink-0">第{ev.round}轮 · {ev.words}字</span>
        </span>
        <Icon
          name="chevron-right"
          size={12}
          className={`text-ink-dim shrink-0 transition-transform duration-200 ${open ? 'rotate-90' : ''}`}
        />
      </button>
      {open && <p className="text-[12px] text-ink/90 leading-6 whitespace-pre-wrap">{ev.speech}</p>}
    </div>
  )
}

/* ---------- 综合报告（两级展示） ---------- */
function ReportCard({ ev }: { ev: Extract<CouncilEvent, { type: 'report' }> }) {
  const debateMeta = useChatStore((s) => s.debateMeta)
  const [state, setState] = useState<'idle' | 'busy' | 'done' | 'err'>('idle')
  const [errText, setErrText] = useState('')
  const [detail, setDetail] = useState(false)

  const memorize = async () => {
    if (!debateMeta.id) {
      setErrText('缺少会议标识（刷新后需重新发起才能记入）')
      setState('err')
      return
    }
    setState('busy')
    try {
      const r = await memorizeReport(debateMeta.id, debateMeta.question, ev.actionable)
      setState(r.memorized ? 'done' : 'err')
      if (!r.memorized) setErrText(r.result || '写入被拒')
    } catch (e) {
      setErrText((e as Error).message)
      setState('err')
    }
  }

  return (
    <div className="border-l-2 border-primary/40 pl-3">
      <div className="text-[12px] font-medium text-primary mb-1.5">📄 综合报告</div>
      <div className="text-[12px] leading-6">
        {ev.actionable.map((x, j) => <div key={j} className="text-ink">• {x}</div>)}
      </div>
      <div className="flex items-center gap-2 mt-2">
        <button
          onClick={memorize}
          disabled={state === 'busy' || state === 'done'}
          className={`px-2 py-1 rounded-md text-[11px] transition-colors duration-150 ${
            state === 'done'
              ? 'bg-[rgba(140,200,150,0.15)] text-[rgba(140,200,150,0.9)]'
              : 'bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40'
          }`}
          title="确认采纳：把可行动结论写入星尘（用户裁决，系统不自动写）"
        >
          {state === 'done' ? '✓ 已记入星尘' : state === 'busy' ? '记入中…' : '确认并记入星尘'}
        </button>
        <button
          onClick={() => setDetail((v) => !v)}
          className="text-[11px] text-ink-dim hover:text-primary transition-colors duration-150"
        >
          {detail ? '收起详情' : '展开详情'}
        </button>
      </div>
      {errText && state === 'err' && <div className="mt-1.5 text-[11px] text-[rgba(230,120,90,0.9)]">{errText}</div>}
      {detail && (
        <div className="mt-2 space-y-1 text-[12px] leading-6 text-ink-muted">
          {ev.consensus.length > 0 && <div>共：{ev.consensus.join('；')}</div>}
          {ev.divergences.length > 0 && <div>分：{ev.divergences.join('；')}</div>}
          {ev.complementarities.length > 0 && <div>互：{ev.complementarities.join('；')}</div>}
          {ev.unanswered.length > 0 && <div className="text-[rgba(230,180,120,0.7)]">未：{ev.unanswered.join('；')}</div>}
        </div>
      )}
    </div>
  )
}

export default function DebateMessage({ ev, msgId }: { ev: CouncilEvent; msgId: string }) {
  const messages = useChatStore((s) => s.messages)

  if (ev.type === 'turn') {
    /* 是否是本场辩论第一条星宿发言（默认展开） */
    const firstTurnId = messages.find((m) => m.role === 'debate' && m.debateEvent?.type === 'turn')?.id
    return <TurnCard ev={ev} isFirst={msgId === firstTurnId} />
  }
  if (ev.type === 'budget') {
    return (
      <div className="text-[11px] text-primary/70 leading-6">
        问星 · {ev.sages.map((s) => s.replace(/《.*?》/g, '').replace(/·.*/, '').trim()).join(' × ')}
        {' '}· 预算 ≈{ev.est_tokens_k}K token · {ev.est_cost} · 随时可中止
      </div>
    )
  }
  if (ev.type === 'verdict') {
    return (
      <div className="text-[11px] text-[rgba(200,215,255,0.6)] leading-6">
        ☞ 主持人 · 第{ev.round}轮：新增观点 {ev.new_claims}｜重复 {ev.repeated ? '是' : '否'}
        {ev.notes && <span className="text-ink-dim"> ｜ {ev.notes}</span>}
      </div>
    )
  }
  if (ev.type === 'report') {
    return <ReportCard ev={ev} />
  }
  if (ev.type === 'converged') {
    return (
      <div className="text-[11px] text-ink-dim">
        — {ev.reason === 'marginal_gain' ? '观点已穷尽' : '到达轮数上限'}，进入综合报告 —
      </div>
    )
  }
  if (ev.type === 'stopped') {
    return <div className="text-[11px] text-[rgba(230,180,120,0.7)]">— 已按你的要求中止研讨 —</div>
  }
  return null
}
