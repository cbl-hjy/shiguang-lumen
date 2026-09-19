// 从 StarMap.tsx 纯移动切割（Phase 4 A-1，2026-08-29）——零逻辑改动，仅搬家 + import 修正
import ErrorBoundary from '../ui/ErrorBoundary'
import Icon, { type IconName } from '../ui/Icon'
import UsagePanel from '../ui/UsagePanel'
import { DebateFeature, DistillFeature, EvolveFeature, KbFeature, MemoryFeature, PathFeature, SageFeature } from './features'
import { MemoryGovernFeature } from './memory-govern'
import { ObservatoryFeature } from './observatory'
import { type Fx, FxOverlay } from './shared'
import { useEffect, useState } from 'react'

/* 星图（v3，2026-08-26）：一个世界，所有功能。
   Bento 8 卡 + 星图内功能视图（2026-08-26 重设计：每个功能全新 v3 界面 + 真实 API，
   不复用旧组件——用户批评"你设计在哪里？我看不到任何变化"后彻底重做）
   - 图标：定制图标集（2026-08-29 起——自绘 icon-set，圆润线条+星点语言与精灵同源；lucide 已全量替换）
   - hover 微动效：叠加元素实现（fx-*），不破坏图标本体
   - 入场：stagger（只动 opacity/filter，不碰 transform）
   - 状态点：青=可用 / 琥珀=待续 / 红=待建（如实标注） */
interface StarMapProps {
  open: boolean
  onClose: () => void
}

type CardState = 'ok' | 'pending' | 'off'

const DOT: Record<CardState, string> = {
  ok: '#3ec9b0',
  pending: '#e6be78',
  off: '#eb5757',
}

/* fx：叠加动效元素类型（bub=气泡上浮 / scan=检索光点 / cur=光标闪烁 / star=旋转小星 / end=终点脉冲） */
const CARDS: {
  key: string
  icon: 'history' | 'route' | 'users' | 'flask' | 'library' | 'gauge' | 'sprout' | 'shield' | 'coins'
  fx: Fx
  title: string
  desc: string
  meta: string
  state: CardState
}[] = [
  {
    key: 'time',
    icon: 'history',
    fx: 'sway',
    title: '时光机 · 记忆',
    desc: '它记得的你——目标、偏好、情绪、困惑。可见可修正。',
    meta: '足迹 · 闪光 · 可编辑',
    state: 'ok',
  },
  {
    key: 'path',
    icon: 'route',
    fx: 'end',
    title: '前方 · 学习路径',
    desc: '续接点连成的发光道路——每步向前一格。',
    meta: 'RAG → Agent 工具链',
    state: 'ok',
  },
  {
    key: 'sage',
    icon: 'users',
    fx: 'star',
    title: '先贤议会',
    desc: '几位不同风格的老师，同一问题给你多视角拆解。',
    meta: '4 本星书 · 4 模式就绪',
    state: 'ok',
  },
  {
    key: 'distill',
    icon: 'flask',
    fx: 'bub',
    title: '对话沉淀',
    desc: '聊过的困惑、灵感、好讲法自动存下来——越聊越懂你。',
    meta: '提炼钩子运行中',
    state: 'ok',
  },
  {
    key: 'kb',
    icon: 'library',
    fx: 'scan',
    title: '知识库',
    desc: '你的资料入库切块——检索、引用、不遗忘。',
    meta: '文档 → 切块 → 检索',
    state: 'ok',
  },
  {
    key: 'obs',
    icon: 'gauge',
    fx: 'ptr',
    title: '运行状况',
    desc: '它的健康、成本、响应速度——出问题能第一时间看到。',
    meta: '观测台 · 新窗口',
    state: 'ok',
  },
  {
    key: 'usage',
    icon: 'coins',
    fx: 'end',
    title: '用量账本',
    desc: '今天用了多少额度、缓存省了多少——花得明白。',
    meta: '每日汇总 · 缓存命中',
    state: 'ok',
  },
  {
    key: 'evolve',
    icon: 'sprout',
    fx: 'grow',
    title: '成长轨迹',
    desc: '它怎么一点点更懂你——技能、讲法、画像都在这里。',
    meta: '画像增量中',
    state: 'ok',
  },
  {
    key: 'govern',
    icon: 'shield',
    fx: 'cur',
    title: '记忆管理',
    desc: '查看、修正、删除它记下的你——删了也进回收站可恢复。',
    meta: '可审计 · 可恢复',
    state: 'ok',
  },
  /* 命令卡已删（2026-08-26 用户判定：冗余——⌘K 快捷键保留，卡片入口多余） */
]

const ICONS: Record<string, IconName> = {
  history: 'history',
  route: 'route',
  users: 'users',
  flask: 'distill',
  library: 'book-open',
  gauge: 'activity',
  sprout: 'sprout',
  shield: 'shield',
  coins: 'sparkles',
}

/* hover 微动效：整体图标动画 + 叠加元素动画（group-hover 触发，前缀 stmap-） */
const ICON_FX = `
.stmap-card .stmap-ic{transition:all .3s cubic-bezier(.22,1,.36,1);position:relative}
.stmap-card:hover .stmap-ic{color:#e6be78;border-color:rgba(230,190,120,.35);background:linear-gradient(160deg,rgba(230,190,120,.08),transparent);box-shadow:0 0 18px rgba(230,190,120,.1)}
.stmap-fx{position:absolute;pointer-events:none;opacity:0}
.stmap-card:hover .stmap-fx{opacity:1}
.stmap-card:hover .fx-sway{animation:stmap-rewind .7s cubic-bezier(.22,1,.36,1);transform-origin:center}
@keyframes stmap-rewind{0%{transform:rotate(0)}35%{transform:rotate(18deg)}65%{transform:rotate(-7deg)}100%{transform:rotate(0)}}
.stmap-card:hover .fx-grow{animation:stmap-leaf .8s cubic-bezier(.22,1,.36,1);transform-origin:center 80%}
@keyframes stmap-leaf{0%{transform:scaleY(1)}45%{transform:scaleY(1.25)}100%{transform:scaleY(1)}}
.stmap-card:hover .fx-ptr{animation:stmap-ptr .7s cubic-bezier(.22,1,.36,1);transform-origin:center bottom}
@keyframes stmap-ptr{0%{transform:rotate(0)}40%{transform:rotate(-14deg)}70%{transform:rotate(8deg)}100%{transform:rotate(0)}}
.stmap-card:hover .fx-bub{animation:stmap-bub 1.3s ease-in-out infinite}
@keyframes stmap-bub{0%{transform:translateY(5px);opacity:0}35%{opacity:.9}100%{transform:translateY(-4px);opacity:0}}
.stmap-card:hover .fx-scan{animation:stmap-scan 1.5s ease-in-out infinite}
@keyframes stmap-scan{0%{transform:translateY(-7px);opacity:0}40%{opacity:1}100%{transform:translateY(6px);opacity:0}}
.stmap-card:hover .fx-cur{animation:stmap-cur .9s steps(1) infinite}
@keyframes stmap-cur{0%,60%{opacity:1}61%,100%{opacity:0}}
.stmap-card:hover .fx-star{animation:stmap-star 1.6s linear infinite}
@keyframes stmap-star{to{transform:rotate(360deg)}}
.stmap-card:hover .fx-end{animation:stmap-pulse .9s cubic-bezier(.22,1,.36,1) infinite}
@keyframes stmap-pulse{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.5);opacity:.55}}
`

/* 叠加动效元素的渲染（fx → 元素） */
export default function StarMap(props: StarMapProps) {
  const { open, onClose } = props
  /* 星图内功能视图（2026-08-26：每个功能全新 v3 界面，就地呈现） */
  const [view, setView] = useState<
    null | 'memory' | 'path' | 'kb' | 'evolve' | 'sage' | 'distill' | 'debate' | 'obs' | 'govern' | 'usage'
  >(null)

  /* Esc 关闭（二级视图时先返回） */
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (view) setView(null)
        else onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose, view])

  /* 关闭时重置二级视图 */
  useEffect(() => {
    if (!open) setView(null)
  }, [open])

  if (!open) return null

  const act = (key: string) => {
    switch (key) {
      case 'time': // 时光机·记忆 → 功能视图
        setView('memory')
        break
      case 'path': // 学习路径 → 功能视图
        setView('path')
        break
      case 'sage':
        setView('sage') // 星阁专属视图
        break
      case 'distill':
        setView('distill') // 萃取专属视图（星图内，替代旧弹窗）
        break
      case 'kb': // 知识库 → 功能视图
        setView('kb')
        break
      case 'obs':
        setView('obs') // 运行观测专属视图（星图内，替代旧 /obs 独立页）
        break
      case 'govern':
        setView('govern') // 记忆治理专属视图（星图第 8 张卡，2026-08-27）
        break
      case 'evolve': // 成长 → 功能视图
        setView('evolve')
        break
      case 'usage': // 账本 → 用量视图
        setView('usage')
        break
    }
  }

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center panel-in"
      style={{
        /* 2026-08-26：去 backdrop-filter 依赖——全屏 blur 在部分引擎渲染异常（headless/WebView），
           用近不透明深色兜底，blur 作为渐进增强 */
        background: 'rgba(7, 9, 14, 0.96)',
        backdropFilter: 'blur(22px)',
        WebkitBackdropFilter: 'blur(22px)',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
      role="dialog"
      aria-modal="true"
      aria-label="星图"
    >
      <style>{ICON_FX}</style>
      <div className="w-[min(920px,94vw)] max-h-[92vh] overflow-y-auto px-2 pb-2 pt-10 relative">
        {/* 面板滚动时关闭钮不跟着走 */}
        <div className="sticky top-0 z-10 h-0 -mt-10 mb-10 pointer-events-none">
          <button
            onClick={onClose}
            className="pointer-events-auto absolute -top-2 right-0 w-9 h-9 rounded-full bg-elevated border border-hairline text-ink-muted hover:text-amber hover:border-amber/60 hover:rotate-90 transition-all duration-300"
            aria-label="关闭星图"
          >
            <Icon name='x' size={15} className='mx-auto' />
          </button>
        </div>

        {/* 功能视图：每个功能全新 v3 界面（真实 API，不复用旧组件） */}
        {view ? (
          <div className="animate-fade-in">
            <button
              onClick={() => setView(null)}
              className="flex items-center gap-1.5 text-[12px] text-ink-dim hover:text-amber transition-colors duration-150 mb-3"
            >
              <Icon name='arrow-left' size={14} />
              星图
            </button>
            {/* 每张卡独立边界（2026-08-29）：单个视图 render 崩溃只影响这一张卡，
                星图外壳 + 其余卡片照常可用，不再整页"只剩背景" */}
            {view === 'memory' && (
              <ErrorBoundary label="时光机 · 记忆">
                <MemoryFeature />
              </ErrorBoundary>
            )}
            {view === 'path' && (
              <ErrorBoundary label="学习路径">
                <PathFeature />
              </ErrorBoundary>
            )}
            {view === 'kb' && (
              <ErrorBoundary label="知识库">
                <KbFeature />
              </ErrorBoundary>
            )}
            {view === 'evolve' && (
              <ErrorBoundary label="成长轨迹">
                <EvolveFeature />
              </ErrorBoundary>
            )}
            {view === 'sage' && (
              <ErrorBoundary label="星阁 · 先贤议会">
                <SageFeature onStartDebate={() => setView('debate')} />
              </ErrorBoundary>
            )}
            {view === 'distill' && (
              <ErrorBoundary label="蒸馏">
                <DistillFeature />
              </ErrorBoundary>
            )}
            {view === 'debate' && (
              <ErrorBoundary label="辩论">
                <DebateFeature onBack={() => setView('sage')} />
              </ErrorBoundary>
            )}
            {view === 'obs' && (
              <ErrorBoundary label="观星台">
                <ObservatoryFeature />
              </ErrorBoundary>
            )}
            {view === 'govern' && (
              <ErrorBoundary label="记忆治理">
                <MemoryGovernFeature />
              </ErrorBoundary>
            )}
            {view === 'usage' && (
              <ErrorBoundary label="用量">
                <UsagePanel />
              </ErrorBoundary>
            )}
          </div>
        ) : (
          <>
            <h2 className="font-logo text-[24px] tracking-[0.12em] mb-1">星 图</h2>
            <p className="text-[12px] text-ink-dim mb-7">
              回望 · 前行 · 远方 —— 一个世界，所有功能
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {CARDS.map((c, i) => {
                const iconName = ICONS[c.icon]
                return (
                  <button
                    key={c.key}
                    onClick={() => act(c.key)}
                    className={`stmap-card group relative text-left rounded-[18px] p-6 overflow-hidden cursor-pointer bg-[linear-gradient(160deg,rgba(30,36,54,.9),rgba(19,23,34,.92))] border border-hairline transition-all duration-300 hover:-translate-y-1 hover:border-amber/40 hover:shadow-[0_16px_44px_rgba(0,0,0,.5),0_0_0_1px_rgba(230,190,120,.12)] ripple ${
                      c.state === 'off' ? 'opacity-80' : ''
                    } animate-card-in`}
                    style={{ animationDelay: `${0.04 + i * 0.05}s` }}
                  >
                    {/* hover 聚光 */}
                    <span className="absolute inset-0 bg-[radial-gradient(80%_60%_at_50%_0%,rgba(230,190,120,.1),transparent)] opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
                    <span
                      className={`stmap-ic w-[38px] h-[38px] mb-3.5 flex items-center justify-center rounded-[10px] bg-elevated border border-hairline text-ink-muted ${
                        c.state === 'off' ? 'opacity-60' : ''
                      }`}
                    >
                      <Icon name={iconName} className="w-[21px] h-[21px]" strokeWidth={1.8} />
                      <FxOverlay fx={c.fx} />
                    </span>
                    <span className="relative block text-[15px] font-medium tracking-wide mb-1.5">
                      {c.title}
                    </span>
                    <span className="relative block text-[12px] text-ink-dim leading-relaxed">
                      {c.desc}
                    </span>
                    <span className="relative mt-3.5 flex items-center gap-1.5 text-[10.5px] text-ink-dim font-mono">
                      <span
                        className="inline-block w-[5px] h-[5px] rounded-full shrink-0"
                        style={{ background: DOT[c.state] }}
                      />
                      {c.meta}
                    </span>
                  </button>
                )
              })}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* ============ 功能视图（v3 全新界面，真实 API，2026-08-26 重设计） ============ */

/* 通用：功能视图外壳卡片 */
