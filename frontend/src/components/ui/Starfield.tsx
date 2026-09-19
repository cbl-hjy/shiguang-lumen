import { useEffect, useRef } from 'react'

/* 星星粒子层（2026-08-28 Phase 设计·打磨）
   设计依据（已调研的获奖站点技术情报）：
   - 不用 Three.js（~150KB 对聊天应用过重）→ 自写 Canvas 粒子（~4KB）
   - 性能纪律：DPR 上限 2；rAF 仅在可见时运行（visibilitychange）；reduced-motion 降级为静态帧
   - 视觉：缓慢漂移的星尘 + 个别亮星（"拾光"语义——黑暗中闪光的点）
   挂载位置：App 背景层（aria-hidden，零交互干扰）。 */

export interface Star {
  x: number
  y: number
  r: number // 半径
  baseAlpha: number // 基础亮度
  twinkleSpeed: number // 闪烁速度
  twinklePhase: number // 闪烁相位
  driftX: number // 水平漂移速度（px/s，极慢）
  driftY: number
  bright: boolean // 亮星（带光晕）
}

/** 粒子生成（纯函数，可单测）：按可视面积分配粒子数（性能预算：每 12000px² 约 1 粒，上限 130） */
export function buildStars(width: number, height: number, rng: () => number = Math.random): Star[] {
  const area = Math.max(1, width) * Math.max(1, height)
  const count = Math.min(130, Math.max(24, Math.round(area / 12000)))
  const stars: Star[] = []
  for (let i = 0; i < count; i++) {
    const bright = rng() < 0.12 // 12% 亮星（带光晕）
    stars.push({
      x: rng() * width,
      y: rng() * height,
      r: bright ? 1.1 + rng() * 0.9 : 0.4 + rng() * 0.7,
      baseAlpha: bright ? 0.55 + rng() * 0.35 : 0.2 + rng() * 0.4,
      twinkleSpeed: 0.4 + rng() * 1.1,
      twinklePhase: rng() * Math.PI * 2,
      driftX: (rng() - 0.5) * 0.6, // px/s，几乎不可察觉
      driftY: (rng() - 0.5) * 0.4,
      bright,
    })
  }
  return stars
}

export default function Starfield({ density = 1 }: { density?: number }): React.ReactElement {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    let raf = 0
    let running = true
    let stars: Star[] = []
    let w = 0
    let h = 0
    let dpr = 1
    let lastT = performance.now()
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    const resize = (): void => {
      dpr = Math.min(2, window.devicePixelRatio || 1) // DPR 上限 2（性能纪律：高分屏不烧 GPU）
      w = canvas.clientWidth
      h = canvas.clientHeight
      canvas.width = Math.max(1, Math.round(w * dpr))
      canvas.height = Math.max(1, Math.round(h * dpr))
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      stars = buildStars(w, h).map((s) => ({ ...s }))
      if (reduced) draw(0) // reduced-motion：静态一帧，不再 rAF
    }

    const draw = (now: number): void => {
      const dt = Math.min(0.05, (now - lastT) / 1000) // 上限 50ms（切后台恢复不跳变）
      lastT = now
      ctx.clearRect(0, 0, w, h)
      for (const s of stars) {
        // 极慢漂移（transform 语义：只移动位置，无重排——Canvas 内本就是像素绘制）
        s.x += s.driftX * dt
        s.y += s.driftY * dt
        if (s.x < -4) s.x = w + 4
        if (s.x > w + 4) s.x = -4
        if (s.y < -4) s.y = h + 4
        if (s.y > h + 4) s.y = -4
        const tw = 0.5 + 0.5 * Math.sin(now / 1000 * s.twinkleSpeed + s.twinklePhase)
        const alpha = s.baseAlpha * (0.35 + 0.65 * tw)
        ctx.beginPath()
        ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2)
        ctx.fillStyle = `rgba(255, 236, 210, ${alpha.toFixed(3)})`
        ctx.fill()
        if (s.bright) {
          // 亮星光晕：两次淡弧模拟 glow（不用 shadowBlur——贵；双重 alpha 叠加）
          ctx.beginPath()
          ctx.arc(s.x, s.y, s.r * 3, 0, Math.PI * 2)
          ctx.fillStyle = `rgba(255, 200, 140, ${(alpha * 0.12).toFixed(3)})`
          ctx.fill()
        }
      }
      if (running) raf = requestAnimationFrame(draw)
    }

    const onVisibility = (): void => {
      const visible = document.visibilityState === 'visible'
      if (visible && !running) {
        running = true
        lastT = performance.now()
        raf = requestAnimationFrame(draw)
      } else if (!visible && running) {
        running = false
        cancelAnimationFrame(raf) // 性能纪律：不可见即停（省电池/GPU）
      }
    }

    resize()
    if (!reduced) {
      raf = requestAnimationFrame(draw)
      document.addEventListener('visibilitychange', onVisibility)
    }
    window.addEventListener('resize', resize)
    return () => {
      running = false
      cancelAnimationFrame(raf)
      document.removeEventListener('visibilitychange', onVisibility)
      window.removeEventListener('resize', resize)
    }
  }, [density])

  return (
    <canvas
      ref={canvasRef}
      aria-hidden
      className="pointer-events-none fixed inset-0 h-full w-full opacity-70"
    />
  )
}
