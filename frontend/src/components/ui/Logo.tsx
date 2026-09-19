import { useEffect, useState } from 'react'

/* 拾光 Lumen 品牌标 v3（2026-08-26）：orbit 语义（琥珀光核 + 虚线星轨 + 青绿卫星 = 光与时间）
   图形标：Lucide orbit 轨道数据（ISC）+ 光核呼吸 + hover 轨道旋转
   字标：站酷小薇（挂载时动态加载）+ LUMEN 等宽微字 */
export default function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const [fontReady, setFontReady] = useState(false)
  const zh = size === 'lg' ? 'text-3xl' : 'text-xl'
  const en = size === 'lg' ? 'text-[11px]' : 'text-[10px]'
  const mark = size === 'lg' ? 'w-12 h-12' : 'w-[30px] h-[30px]'

  useEffect(() => {
    /* 延迟加载：字标区域按需下载字体（字体体积 2.2MB，不进首屏关键路径） */
    import('@fontsource/zcool-xiaowei/chinese-simplified-400.css')
      .then(() => setFontReady(true))
      .catch(() => setFontReady(false))
  }, [])

  return (
    <div className="flex items-center gap-2.5 select-none">
      {/* 图形标：光核（琥珀）+ 双虚线轨道 + 卫星（青绿） */}
      <span className={`brand-mark ${mark} shrink-0`}>
        <svg viewBox="0 0 24 24" className="w-full h-full overflow-visible">
          <g fill="none" strokeWidth="1.3">
            <path
              className="logo-orbit"
              d="M20.34 6.48A10 10 0 0 1 10.27 21.85"
              stroke="rgba(236,233,225,.32)"
              strokeDasharray="2.4 3"
              strokeLinecap="round"
            />
            <path
              className="logo-orbit"
              d="M3.66 17.52A10 10 0 0 1 13.74 2.15"
              stroke="rgba(236,233,225,.22)"
              strokeDasharray="2.4 3"
              strokeLinecap="round"
            />
          </g>
          <circle className="logo-core" cx="12" cy="12" r="3.4" fill="#e6be78" />
          <circle className="logo-sat" cx="19.2" cy="4.8" r="1.9" fill="#3ec9b0" />
          <circle cx="4.6" cy="19.4" r="1.5" fill="rgba(230,190,120,.8)" />
        </svg>
      </span>
      {/* 字标 */}
      <span className="flex flex-col leading-none gap-0.5">
        <span
          className="animate-logo-in font-logo text-primary"
          style={{ letterSpacing: '0.14em', lineHeight: 1.05 }}
        >
          <span className={zh}>{fontReady ? '拾光' : ''}</span>
        </span>
        <span className={`${en} text-ink-dim tracking-[0.42em]`}>LUMEN</span>
      </span>
    </div>
  )
}
