import { useState } from 'react'
import { mergeTopics, renameTopic, splitTopic, type Topic } from '../../api/progress'

/* 星图（Memory Hub 主题视图，2026-08-19）：主题卡片 + 状态徽标 + 联动数 + 展开明细 + 树状缩进 + 纠错。
   树状（P3）：parent 非空的主题缩进显示（层级来自模型演化输出，harness 不定义——判断无墙）；
   纠错（P3）：改名/合并/拆分改索引零迁移（星尘文件不动）——拆分从源 aliases 移交 B 的词防抢归拢。 */

/* 状态徽标配色（定稿光色语义 v3：青=进行/琥珀=卡住(非红=不焦虑)/绿=完成/灰=搁置）
   dot 用 lumen-dot 光点系列——一粒光=一个状态（光点系统，hover 由文字徽标补偿明确性） */
const STATUS_STYLE: Record<string, { text: string; dot: string }> = {
  搁置: { text: 'text-ink-dim', dot: 'lumen-dot-dormant' },
  卡住: { text: 'text-amber', dot: 'lumen-dot-attention' },
  完成: { text: 'text-success', dot: 'lumen-dot-done' },
  进行中: { text: 'text-primary', dot: 'lumen-dot-active' },
}

function fmtDate(d: string): string {
  if (!d) return '未知'
  const s = d.slice(0, 10)
  return s.replace(/-/g, '.')
}

export default function LearningPath({ topics, onChanged }: { topics: Topic[]; onChanged?: () => void }) {
  const [open, setOpen] = useState<string | null>(null)
  // 纠错表单态：{mode:'rename'|'merge'|'split', topic, value(新名/目标), aliases(仅 split)} | null
  const [edit, setEdit] = useState<{ mode: 'rename' | 'merge' | 'split'; topic: string; value: string; aliases: string } | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  /* 树状分组：有 parent 的归到父下缩进；parent 不存在的当作顶级 */
  const topLevel = topics.filter((t) => !t.parent || !topics.some((x) => x.name === t.parent))
  const childrenOf = (p: string) => topics.filter((t) => t.parent === p)

  const doEdit = async () => {
    if (!edit) return
    const target = edit.value.trim()
    if (!target) return
    let r: { ok: boolean; msg?: string }
    if (edit.mode === 'rename') {
      r = await renameTopic(edit.topic, target)
    } else if (edit.mode === 'merge') {
      r = await mergeTopics(edit.topic, target)
    } else {
      const aliases = edit.aliases.split(/[,，]/).map((s) => s.trim()).filter(Boolean)
      r = await splitTopic(edit.topic, target, aliases)
    }
    setMsg(r.msg ?? (r.ok ? '完成' : '失败'))
    setEdit(null)
    onChanged?.()
    setTimeout(() => setMsg(null), 2500)
  }

  const renderTopic = (t: Topic, depth: number) => {
    const st = STATUS_STYLE[t.status] ?? STATUS_STYLE['进行中']
    const expanded = open === t.name
    return (
      <div key={t.name} className={depth > 0 ? 'ml-5' : ''}>
        <div className="rounded-lg border border-hairline bg-surface overflow-hidden">
          <button
            onClick={() => setOpen(expanded ? null : t.name)}
            className="w-full flex items-start gap-2.5 px-3 py-2.5 text-left transition-colors duration-150 hover:bg-elevated cursor-pointer"
            aria-expanded={expanded}
          >
            {/* 光点挂载即点亮（L1 点亮动画：状态再生语义——主题出现=光点亮起） */}
            <span className={`lumen-dot lumen-dot-ignite ${st.dot} mt-1.5`} />
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                {depth > 0 && <span className="text-[10px] text-ink-dim/70">└</span>}
                <span className="text-[13px] text-ink">{t.name}</span>
                {/* 状态=关键信息：10px→12px 提级（定稿 Phase 3；光点化在 Phase 4） */}
                <span className={`text-sm px-1.5 py-0.5 rounded bg-elevated ${st.text}`}>{t.status}</span>
              </div>
              <div className="mt-0.5 text-[11px] text-ink-dim">
                {t.memory_count} 条星尘 · 最后活动 {fmtDate(t.last_active)}
              </div>
            </div>
            <span className="text-[11px] text-ink-dim/70 mt-1">{expanded ? '收起' : '展开'}</span>
          </button>
          {expanded && (
            <div className="px-3 pb-2.5 border-t border-hairline">
              {/* 续接点（状态再生：从星尘推导；搁置主题不主动推荐） */}
              {t.continuation?.text && !t.continuation.abandoned && (
                <div className="py-2 border-b border-hairline/50">
                  <div className="text-[10px] uppercase tracking-wider text-primary mb-1">续接点</div>
                  <div className="text-[12px] text-ink/85 leading-relaxed">{t.continuation.text}</div>
                </div>
              )}
              {/* 反思（为什么卡住） */}
              {t.reflections && t.reflections.length > 0 && (
                <div className="py-2 border-b border-hairline/50">
                  <div className="text-[10px] uppercase tracking-wider text-warning mb-1">反思 · {t.reflections.length}</div>
                  <div className="text-[12px] text-ink/80 leading-relaxed line-clamp-2">{t.reflections[0]}</div>
                </div>
              )}
              {/* 技能（怎么讲才懂） */}
              {t.skills && t.skills.length > 0 && (
                <div className="py-2 border-b border-hairline/50">
                  <div className="text-[10px] uppercase tracking-wider text-success mb-1">技能 · {t.skills.length}</div>
                  <div className="text-[12px] text-ink/80 leading-relaxed line-clamp-2">{t.skills[0]}</div>
                </div>
              )}
              {/* 关联星尘明细 */}
              {t.memories.length === 0 ? (
                <div className="text-[12px] text-ink-dim py-2">暂无关联星尘</div>
              ) : (
                t.memories.slice(0, 5).map((m, i) => (
                  <div key={i} className="py-1.5 border-b border-hairline/50 last:border-0">
                    <div className="text-[12px] text-ink/80 leading-relaxed line-clamp-2">{m.content}</div>
                    <div className="text-[10px] text-ink-dim/70 mt-0.5">
                      {m.category} · {fmtDate(m.date)}
                      {m.content_date && m.content_date !== m.date.slice(0, 10) && (
                        <span className="text-warning/80"> · 内容 {m.content_date.replace(/-/g, '.')}</span>
                      )}
                    </div>
                  </div>
                ))
              )}
              {t.memories.length > 5 && (
                <div className="text-[11px] text-ink-dim/80 pt-1.5">+ {t.memories.length - 5} 条星尘（在星尘查看全部）</div>
              )}
              {/* 纠错（P3：改名/合并——判断无墙的用户侧操作） */}
              <div className="flex items-center gap-2 pt-2 border-t border-hairline mt-2">
                <button
                  onClick={() => setEdit({ mode: 'rename', topic: t.name, value: '', aliases: '' })}
                  className="text-[11px] px-2 py-1 rounded bg-elevated text-ink-muted hover:text-ink"
                >
                  改名
                </button>
                <button
                  onClick={() => setEdit({ mode: 'merge', topic: t.name, value: '', aliases: '' })}
                  className="text-[11px] px-2 py-1 rounded bg-elevated text-ink-muted hover:text-ink"
                >
                  合并到…
                </button>
                <button
                  onClick={() => setEdit({ mode: 'split', topic: t.name, value: '', aliases: '' })}
                  className="text-[11px] px-2 py-1 rounded bg-elevated text-ink-muted hover:text-ink"
                >
                  拆分出…
                </button>
                {msg && <span className="text-[11px] text-ink-dim">{msg}</span>}
              </div>
              {edit && edit.topic === t.name && (
                <div className="flex flex-col gap-1.5 pt-2">
                  <div className="flex items-center gap-2">
                    <input
                      value={edit.value}
                      onChange={(e) => setEdit({ ...edit, value: e.target.value })}
                      placeholder={edit.mode === 'rename' ? '新名字' : edit.mode === 'merge' ? '合并到哪个主题' : '拆出的新主题名'}
                      onKeyDown={(e) => e.key === 'Enter' && doEdit()}
                      className="flex-1 text-[12px] px-2 py-1 rounded bg-elevated border border-hairline text-ink/90 outline-none focus:border-primary"
                    />
                    <button onClick={doEdit} className="text-[11px] px-2 py-1 rounded bg-primary/20 text-primary">
                      确认
                    </button>
                    <button onClick={() => setEdit(null)} className="text-[11px] px-2 py-1 rounded text-ink-dim">
                      取消
                    </button>
                  </div>
                  {edit.mode === 'split' && (
                    <input
                      value={edit.aliases}
                      onChange={(e) => setEdit({ ...edit, aliases: e.target.value })}
                      placeholder="别名关键词（逗号分隔，如：注意力机制, L1编码器）——该词星尘将归新主题"
                      onKeyDown={(e) => e.key === 'Enter' && doEdit()}
                      className="text-[11px] px-2 py-1 rounded bg-elevated border border-hairline text-ink-muted outline-none focus:border-primary"
                    />
                  )}
                </div>
              )}
            </div>
          )}
        </div>
        {/* 子主题（树状缩进） */}
        {childrenOf(t.name).map((c) => renderTopic(c, depth + 1))}
      </div>
    )
  }

  if (topics.length === 0) {
    return (
      <div className="flex items-center gap-2.5 py-2">
        <span className="empty-light shrink-0" />
        <span className="empty-trail shrink-0" />
        <span className="text-[12px] text-ink-dim leading-relaxed">
          告诉我"我想学 XX"，拾光会为你点亮第一站。
        </span>
      </div>
    )
  }
  return <div className="flex flex-col gap-2">{topLevel.map((t) => renderTopic(t, 0))}</div>
}
