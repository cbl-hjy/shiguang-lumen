// 从 StarMap.tsx 纯移动切割（Phase 4 A-1，2026-08-29）——零逻辑改动，仅搬家 + import 修正
import Icon from '../ui/Icon'
import { useEffect, useState } from 'react'

export type Fx = 'sway' | 'bub' | 'scan' | 'cur' | 'star' | 'end' | 'ptr' | 'grow' | null

export function FxOverlay({ fx }: { fx: Fx }) {
  if (!fx) return null
  switch (fx) {
    case 'bub':
      return (
        <span
          className="stmap-fx fx-bub w-[7px] h-[7px] rounded-full"
          style={{
            background: '#e6be78',
            left: '50%',
            top: '52%',
            marginLeft: -3.5,
            boxShadow: '0 0 6px rgba(230,190,120,.8)',
          }}
        />
      )
    case 'scan':
      return (
        <span
          className="stmap-fx fx-scan w-[5px] h-[5px] rounded-full"
          style={{
            background: '#3ec9b0',
            left: '22%',
            top: '50%',
            boxShadow: '0 0 6px rgba(62,201,176,.8)',
          }}
        />
      )
    case 'cur':
      return (
        <span
          className="stmap-fx fx-cur w-[5px] h-[7px] rounded-[1px]"
          style={{
            background: '#e6be78',
            right: '14%',
            bottom: '22%',
            boxShadow: '0 0 5px rgba(230,190,120,.7)',
          }}
        />
      )
    case 'star':
      return (
        <span
          className="stmap-fx fx-star absolute -top-0.5 -right-0.5"
          style={{ width: 11, height: 11 }}
        >
          <Icon name='star' size={11} className='text-amber' />
        </span>
      )
    case 'end':
      return (
        <span
          className="stmap-fx fx-end w-[6px] h-[6px] rounded-full"
          style={{
            background: '#3ec9b0',
            right: '18%',
            top: '12%',
            boxShadow: '0 0 7px rgba(62,201,176,.9)',
          }}
        />
      )
    default:
      return null
  }
}

export const fCard =
  'rounded-[14px] border border-hairline bg-[linear-gradient(160deg,rgba(30,36,54,.85),rgba(19,23,34,.9))] px-4 py-3.5'
export const fTitle = 'text-[13px] font-medium tracking-wider mb-3 flex items-center gap-2'

/* 编辑弹窗（全屏放大——2026-08-26 用户：小框里修改很难改，放大编辑） */
export function EditModal({
  title,
  value,
  onChange,
  onSave,
  onCancel,
  busy,
}: {
  title: string
  value: string
  onChange: (v: string) => void
  onSave: () => void
  onCancel: () => void
  busy?: boolean
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancel()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onCancel])
  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center animate-fade-in"
      role="dialog"
      aria-modal="true"
    >
      <div className="absolute inset-0 bg-black/60" onClick={onCancel} aria-label="关闭" />
      <div className="relative w-[min(680px,92vw)] rounded-2xl border border-hairline bg-elevated shadow-2xl p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[14px] font-medium text-amber">{title}</span>
          <button
            onClick={onCancel}
            className="p-1.5 rounded-md text-ink-dim hover:text-primary hover:bg-surface transition-colors duration-150"
            aria-label="关闭编辑"
          >
            <Icon name='x' size={15} />
          </button>
        </div>
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={10}
          autoFocus
          className="w-full rounded-xl border border-primary/40 bg-surface px-3.5 py-3 text-[13.5px] leading-relaxed text-ink outline-none focus:border-primary/60 resize-y"
          aria-label="编辑内容"
        />
        <div className="flex justify-end gap-2 mt-3">
          <button
            onClick={onCancel}
            className="px-3.5 py-1.5 rounded-lg text-[12px] text-ink-dim hover:text-ink transition-colors duration-150"
          >
            取消
          </button>
          <button
            onClick={onSave}
            disabled={busy || !value.trim()}
            className="px-4 py-1.5 rounded-lg text-[12px] bg-primary/15 border border-primary/40 text-primary hover:bg-primary/25 disabled:opacity-40 transition-colors duration-150"
          >
            {busy ? '保存中…' : '保存'}
          </button>
        </div>
      </div>
    </div>
  )
}

/* 数组兜底（2026-08-29 白屏事故修复）：后端字段缺失/为 null/非数组 → 空数组。
   `.length of undefined` 属于 render 期异常，React 18 会卸载整棵组件树 → 用户只剩背景。
   所有消费后端数组字段的地方统一走这里，杜绝同类崩溃再次发生。 */
export function arr<T>(v: T[] | null | undefined): T[] {
  return Array.isArray(v) ? v : []
}

/* 请求缓存（2026-08-28 性能整改）：星图每卡切换都要等网络（公网隧道 ~1.3s）→
   stale-while-revalidate：命中缓存立即渲染（秒开，无 loading），同时后台刷新。
   缓存 5 分钟有效；reload() 强制刷新（编辑/删除后调用）。 */
export const _fetchCache = new Map<string, { t: number; v: unknown }>()
export const CACHE_TTL = 5 * 60 * 1000

export function clearStarMapCache(key?: string) {
  if (key) _fetchCache.delete(key)
  else _fetchCache.clear()
}

export function useFetch<T>(fn: () => Promise<T>, cacheKey?: string) {
  const key = cacheKey || fn.name || 'anon'
  const hit = _fetchCache.get(key) as { t: number; v: T } | undefined
  const fresh = hit && Date.now() - hit.t < CACHE_TTL
  const [data, setData] = useState<T | null>(fresh ? hit!.v : null)
  const [err, setErr] = useState<string | null>(null)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    // 缓存够新 → 不显示 loading，且不再发请求（省一次往返）
    if (fresh && tick === 0) return
    fn()
      .then((d) => {
        if (!alive) return
        _fetchCache.set(key, { t: Date.now(), v: d })
        setData(d)
      })
      .catch((e) => alive && setErr(String(e?.message || e)))
    return () => {
      alive = false
    }
  }, [fn, tick, key])
  return { data, err, reload: () => setTick((t) => t + 1) }
}

export function Loading() {
  /* 2026-08-28 骨架屏：流光 + 内容形状占位（shimmer），比纯转圈更有"活"感 */
  return (
    <div className="py-4">
      <div className="orb-flow justify-center mb-4">
        <i />
        <i />
        <i />
      </div>
      <div className="space-y-2.5 px-1">
        <div className="skeleton h-3.5 w-3/4" />
        <div className="skeleton h-3.5 w-1/2" />
        <div className="skeleton h-3.5 w-2/3" />
        <div className="skeleton h-3.5 w-3/5" />
      </div>
    </div>
  )
}

/* 时光机 · 记忆：画像 + 记忆条目（分类/重要性光点；可查看/编辑/删除——可观测性透明化理念） */
