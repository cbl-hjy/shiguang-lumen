import type { ReactElement } from 'react'

/* 定制图标集（2026-08-29 Phase 设计·打磨）：替换 lucide——与星尘精灵同设计语言。
   设计规范（统一）：
   - viewBox 24x24 · stroke 1.5 · round cap/join（圆润连续线条=精灵的圆润感）
   - 星点语言：特定图标带 fill 小圆点（星尘=光点），呼应精灵的星尘粒子
   - 色：currentColor（语义色由使用处控制：teal=进行/amber=拾光时刻）
   全部手绘 SVG，零依赖。 */

const S = {
  stroke: 'currentColor',
  strokeWidth: 1.5,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  fill: 'none',
} as const

type P = { size?: number; strokeWidth?: number; className?: string }

function W({ size = 16, className = '', children }: P & { children: ReactElement[] | ReactElement }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      className={className}
      aria-hidden
      {...S}
    >
      {children}
    </svg>
  )
}

/* ===== 基础操作（高频，圆润线条） ===== */

export function XIcon(p: P) {
  return (
    <W {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </W>
  )
}

export function CheckIcon(p: P) {
  return (
    <W {...p}>
      <path d="M4.5 12.5l5 5L19.5 6.5" />
    </W>
  )
}

export function PlusIcon(p: P) {
  return (
    <W {...p}>
      <path d="M12 5v14M5 12h14" />
    </W>
  )
}

export function ArrowLeftIcon(p: P) {
  return (
    <W {...p}>
      <path d="M19 12H5M11 6l-6 6 6 6" />
    </W>
  )
}

export function ArrowRightIcon(p: P) {
  return (
    <W {...p}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </W>
  )
}

export function ChevronRightIcon(p: P) {
  return (
    <W {...p}>
      <path d="M9 6l6 6-6 6" />
    </W>
  )
}

export function SearchIcon(p: P) {
  return (
    <W {...p}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M16 16l4.5 4.5" />
    </W>
  )
}

export function AlertTriangleIcon(p: P) {
  return (
    <W {...p}>
      {/* 圆角警告三角（与精灵的圆润一致，不用尖角） */}
      <path d="M12 3.5L21.5 20h-19L12 3.5z" />
      <path d="M12 9.5V14" />
      <circle cx="12" cy="17.2" r="0.9" fill="currentColor" stroke="none" />
    </W>
  )
}

export function RefreshIcon(p: P) {
  return (
    <W {...p}>
      <path d="M20 12a8 8 0 1 1-2.4-5.7" />
      <path d="M20 3.5V8h-4.5" />
    </W>
  )
}

export function LoaderIcon(p: P) {
  return (
    <W {...p}>
      <path d="M12 3.5a8.5 8.5 0 0 1 8.5 8.5" />
    </W>
  )
}

export function FlameIcon(p: P) {
  return (
    <W {...p}>
      {/* 火焰=精灵头顶元素：上尖下圆的烛火形 */}
      <path d="M12 3c2.5 3.2 5 5.6 5 9a5 5 0 0 1-10 0c0-1.6.6-3 1.6-4.2C9.3 9.5 10 11 10 11s1-2 2-4.6c0 0 0 0 0 0z" />
      <path d="M9.8 14.5a2.4 2.4 0 0 0 2.2 2.9" />
    </W>
  )
}

/* ===== 品牌图标（星点 + 连线语言，与星尘语义呼应） ===== */

export function BookIcon(p: P) {
  return (
    <W {...p}>
      {/* 翻开的书：两页 + 中缝，页缘一颗星点（拾光的记录） */}
      <path d="M12 6.5C10.5 5 8 4.5 4.5 5v13.5c3.5-.5 6 0 7.5 1.5 1.5-1.5 4-2 7.5-1.5V5c-3.5-.5-6 0-7.5 1.5z" />
      <path d="M12 6.5V20" />
      <circle cx="17.8" cy="10" r="1" fill="currentColor" stroke="none" />
    </W>
  )
}

export function RouteIcon(p: P) {
  return (
    <W {...p}>
      {/* 路径=学习路径：起点星点 → 蜿蜒曲线 → 终点星点 */}
      <circle cx="5" cy="18" r="2.2" />
      <circle cx="19" cy="6" r="2.2" />
      <path d="M7 16.5C11 15 12 10 17 8" />
      <circle cx="11" cy="12.5" r="0.8" fill="currentColor" stroke="none" />
    </W>
  )
}

export function SparklesIcon(p: P) {
  return (
    <W {...p}>
      {/* 闪光=拾光时刻（amber 语义）：主星 + 小光芒 */}
      <path d="M12 4l1.8 4.7L18.5 10l-4.7 1.8L12 16.5l-1.8-4.7L5.5 10l4.7-1.3L12 4z" />
      <path d="M18.5 15.5l.7 1.8 1.8.7-1.8.7-.7 1.8-.7-1.8-1.8-.7 1.8-.7.7-1.8z" />
    </W>
  )
}

export function SproutIcon(p: P) {
  return (
    <W {...p}>
      {/* 成长=嫩芽：茎 + 两叶 + 土点 */}
      <path d="M12 21V10.5" />
      <path d="M12 13C12 9.5 9.5 7.5 6 7.5c0 3.5 2.5 5.5 6 5.5z" />
      <path d="M12 11c0-3 2-5 5.5-5.5 0 3.2-2 5-5.5 5z" />
      <circle cx="12" cy="21" r="0.9" fill="currentColor" stroke="none" />
    </W>
  )
}

export function UserIcon(p: P) {
  return (
    <W {...p}>
      {/* 用户=圆头 + 圆肩（全圆润，无直角） */}
      <circle cx="12" cy="8" r="3.8" />
      <path d="M4.8 20c1.6-3.4 4.2-5 7.2-5s5.6 1.6 7.2 5" />
    </W>
  )
}

export function UsersIcon(p: P) {
  return (
    <W {...p}>
      <circle cx="9" cy="8.5" r="3.3" />
      <circle cx="17.5" cy="9.5" r="2.5" />
      <path d="M3 19.5c1.3-2.9 3.4-4.3 6-4.3s4.7 1.4 6 4.3" />
      <path d="M15 15.6c2.4.2 4.2 1.5 5.4 3.9" />
    </W>
  )
}

export function ActivityIcon(p: P) {
  return (
    <W {...p}>
      {/* 活跃度=心跳线 */}
      <path d="M3 12h4l2.5-6 4 12 2.5-6H21" />
    </W>
  )
}

export function TrendingUpIcon(p: P) {
  return (
    <W {...p}>
      <path d="M3.5 17l6-6 4 4 7-7.5" />
      <path d="M15.5 7.5H21V13" />
    </W>
  )
}

export function DatabaseIcon(p: P) {
  return (
    <W {...p}>
      <ellipse cx="12" cy="6" rx="7.5" ry="3" />
      <path d="M4.5 6v12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3V6" />
      <path d="M4.5 12c0 1.7 3.4 3 7.5 3s7.5-1.3 7.5-3" />
    </W>
  )
}

export function InfoIcon(p: P) {
  return (
    <W {...p}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5" />
      <circle cx="12" cy="7.8" r="0.9" fill="currentColor" stroke="none" />
    </W>
  )
}

export function GridIcon(p: P) {
  return (
    <W {...p}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.8" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" />
    </W>
  )
}

export function LogoutIcon(p: P) {
  return (
    <W {...p}>
      <path d="M14 4h-8a1.5 1.5 0 0 0-1.5 1.5v13A1.5 1.5 0 0 0 6 20h8" />
      <path d="M10 12h10.5M16.5 8l4 4-4 4" />
    </W>
  )
}

export function PaletteIcon(p: P) {
  return (
    <W {...p}>
      <path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.6 0 2.4-1.2 1.8-2.4-.5-1-.1-1.9 1.1-1.9H17a3.8 3.8 0 0 0 3.8-3.8C20.8 6.9 16.9 3.5 12 3.5z" />
      <circle cx="7.8" cy="10.5" r="1" fill="currentColor" stroke="none" />
      <circle cx="10.5" cy="7.3" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="7.3" r="1" fill="currentColor" stroke="none" />
    </W>
  )
}

export function SettingsIcon(p: P) {
  return (
    <W {...p}>
      {/* 设置=调光轮：圆 + 8 根辐条（光=状态） */}
      <circle cx="12" cy="12" r="3.2" />
      <path d="M12 3.5v3M12 17.5v3M3.5 12h3M17.5 12h3M6 6l2.1 2.1M15.9 15.9L18 18M18 6l-2.1 2.1M8.1 15.9L6 18" />
    </W>
  )
}

export function BellIcon(p: P) {
  return (
    <W {...p}>
      <path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15l1.5-2z" />
      <path d="M10 20.5a2.2 2.2 0 0 0 4 0" />
    </W>
  )
}

export function CameraIcon(p: P) {
  return (
    <W {...p}>
      <rect x="3.5" y="7" width="17" height="12.5" rx="2.5" />
      <path d="M8.5 7L10 4.5h4L15.5 7" />
      <circle cx="12" cy="13.2" r="3.2" />
    </W>
  )
}

export function CodeIcon(p: P) {
  return (
    <W {...p}>
      <path d="M8.5 7L4 12l4.5 5M15.5 7L20 12l-4.5 5" />
      <path d="M13.5 5.5l-3 13" />
    </W>
  )
}

export function CopyIcon(p: P) {
  return (
    <W {...p}>
      <rect x="8.5" y="8.5" width="11" height="11" rx="2" />
      <path d="M5.5 15.5h-1a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </W>
  )
}

export function DownloadIcon(p: P) {
  return (
    <W {...p}>
      <path d="M12 3.5V14.5M7.5 10l4.5 4.5L16.5 10" />
      <path d="M4.5 20h15" />
    </W>
  )
}

export function FileIcon(p: P) {
  return (
    <W {...p}>
      <path d="M14 3.5H7A1.5 1.5 0 0 0 5.5 5v14A1.5 1.5 0 0 0 7 20.5h10a1.5 1.5 0 0 0 1.5-1.5V8L14 3.5z" />
      <path d="M14 3.5V8h4.5M9 12.5h6M9 16h4" />
    </W>
  )
}

export function TrashIcon(p: P) {
  return (
    <W {...p}>
      <path d="M4.5 6.5h15M9.5 6V4.5h5V6M6.5 6.5l1 13h9l1-13" />
      <path d="M10 10v6M14 10v6" />
    </W>
  )
}

export function VolumeIcon(p: P) {
  return (
    <W {...p}>
      <path d="M4 9.5v5h3.5L12 18.5v-13L7.5 9.5H4z" />
      <path d="M15.5 9a4.5 4.5 0 0 1 0 6M17.8 6.8a8 8 0 0 1 0 10.4" />
    </W>
  )
}

export function MicIcon(p: P) {
  return (
    <W {...p}>
      <rect x="9" y="3.5" width="6" height="11" rx="3" />
      <path d="M5.5 11.5a6.5 6.5 0 0 0 13 0M12 18v3.5" />
    </W>
  )
}

export function MaximizeIcon(p: P) {
  return (
    <W {...p}>
      <path d="M9 4.5H4.5V9M15 4.5h4.5V9M9 19.5H4.5V15M15 19.5h4.5V15" />
    </W>
  )
}

export function PanelsIcon(p: P) {
  return (
    <W {...p}>
      <rect x="3.5" y="4" width="17" height="16" rx="2" />
      <path d="M3.5 9.5h17M9 9.5V20" />
    </W>
  )
}

export function ServerIcon(p: P) {
  return (
    <W {...p}>
      <rect x="3.5" y="4.5" width="17" height="6" rx="1.8" />
      <rect x="3.5" y="13.5" width="17" height="6" rx="1.8" />
      <circle cx="7" cy="7.5" r="0.8" fill="currentColor" stroke="none" />
      <circle cx="7" cy="16.5" r="0.8" fill="currentColor" stroke="none" />
    </W>
  )
}

export function ShareIcon(p: P) {
  return (
    <W {...p}>
      <circle cx="6" cy="12" r="2.2" />
      <circle cx="18" cy="6" r="2.2" />
      <circle cx="18" cy="18" r="2.2" />
      <path d="M8 11l7.5-4M8 13l7.5 4" />
    </W>
  )
}

export function ThumbsUpIcon(p: P) {
  return (
    <W {...p}>
      <path d="M7.5 11.5V20H5a1.5 1.5 0 0 1-1.5-1.5v-5A1.5 1.5 0 0 1 5 12h2.5z" />
      <path d="M7.5 12L11 4.5c.8 0 1.5.5 1.7 1.3l1 3.7h4.3a2 2 0 0 1 2 2.4l-1.2 6.5a2 2 0 0 1-2 1.6H7.5" />
    </W>
  )
}

export function ThumbsDownIcon(p: P) {
  return (
    <W {...p}>
      <path d="M16.5 12.5V4H19a1.5 1.5 0 0 1 1.5 1.5v5a1.5 1.5 0 0 1-1.5 1.5h-2.5z" />
      <path d="M16.5 12L13 19.5c-.8 0-1.5-.5-1.7-1.3l-1-3.7H6a2 2 0 0 1-2-2.4l1.2-6.5A2 2 0 0 1 7.2 4.5h9.3" />
    </W>
  )
}

export function ImageIcon(p: P) {
  return (
    <W {...p}>
      <rect x="3.5" y="4.5" width="17" height="15" rx="2" />
      <circle cx="9" cy="9.5" r="1.6" />
      <path d="M3.5 17l5-4.5 4 3.5 3-2.5 5 4" />
    </W>
  )
}

export function ShieldIcon(p: P) {
  return (
    <W {...p}>
      {/* 守护=盾牌 + 中央星点（拾光护着你） */}
      <path d="M12 3l7 2.5v6c0 4.5-3 7.5-7 9.5-4-2-7-5-7-9.5v-6L12 3z" />
      <circle cx="12" cy="11.5" r="1.6" />
    </W>
  )
}

export function StarIcon(p: P) {
  return (
    <W {...p}>
      {/* 星星=星点语言（fill 用法：拾光时刻/标记） */}
      <path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 17l-5.2 2.6 1-5.8-4.3-4.1 5.9-.9L12 3.5z" />
    </W>
  )
}
