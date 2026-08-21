import { useEffect, useState } from 'react'

/* 拾光 Lumen 字标：站酷小薇（挂载时动态加载，首屏不阻塞）+ 进场动效 */
export default function Logo({ size = 'md' }: { size?: 'md' | 'lg' }) {
  const [fontReady, setFontReady] = useState(false)
  const zh = size === 'lg' ? 'text-3xl' : 'text-xl'
  /* 8px 太小（违反最小可读性）——提升到 10px（micro 标签下限） */
  const en = size === 'lg' ? 'text-[11px]' : 'text-[10px]'

  useEffect(() => {
    /* 延迟加载：字标区域按需下载字体（字体体积 2.2MB，不进首屏关键路径） */
    import('@fontsource/zcool-xiaowei/chinese-simplified-400.css')
      .then(() => setFontReady(true))
      .catch(() => setFontReady(false))
  }, [])

  return (
    <div className="flex items-center gap-2 select-none">
      <span className="animate-logo-in font-logo text-primary" style={{ letterSpacing: '0.08em' }}>
        <span className={zh}>{fontReady ? '拾光' : ''}</span>
      </span>
      <span className="flex flex-col leading-none gap-0.5">
        <span className={`${en} text-ink-dim tracking-[0.3em]`}>LUMEN</span>
        <span className="h-px w-full bg-primary/60" />
      </span>
    </div>
  )
}
