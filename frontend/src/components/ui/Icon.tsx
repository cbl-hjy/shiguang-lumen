/* 图标统一封装（星座语言 v3：夜空中拾光——星点+星图连线，品牌入口图标）
   - 品牌图标（手绘 SVG）：星尘/问星/星图/领航/传光/拾入/夜谈/调光/萃光/星阁——星=光点，线=星座连线
   - 通用操作保留 lucide（arrow-right/check/x/plus 等——基础操作不改=用户认识度优先）
   风格：星点 fill currentColor + 连线 1.5px stroke currentColor（与 lucide 同粗），24x24 viewBox */
import {
  ArrowRight,
  Bell,
  Check,
  ChevronRight,
  Code,
  Copy,
  Download,
  FileText,
  Flame,
  Image as ImageIcon,
  LayoutPanelLeft,
  Loader2,
  Plus,
  Search,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  User,
  X,
  type LucideIcon,
} from 'lucide-react'
import type { ComponentType } from 'react'

/* ===== 星座品牌图标（手绘 SVG，星点+连线语言） ===== */

/* 星尘（星尘=记忆）：散落的星 + 收集弧线 */
function DustIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M7 18Q12 16 17 18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="8" cy="8" r="1.6" fill="currentColor" />
      <circle cx="16" cy="6.5" r="1.2" fill="currentColor" />
      <circle cx="12.5" cy="12.5" r="1.5" fill="currentColor" />
    </svg>
  )
}

/* 问星（问星=会议）：三星围环——星宿如星聚首 */
function StarsIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
      <circle cx="12" cy="6" r="1.5" fill="currentColor" />
      <circle cx="17.2" cy="15" r="1.2" fill="currentColor" />
      <circle cx="6.8" cy="15" r="1.2" fill="currentColor" />
    </svg>
  )
}

/* 星图（星图=学习路径）：北斗七星——指路 */
function ChartIcon() {
  const pts = [
    [6, 8], [10, 6], [13, 8], [9, 10], [15, 11], [17, 14], [19, 17],
  ]
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path
        d="M6 8L10 6L13 8L9 10L15 11L17 14L19 17"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      {pts.map(([x, y], i) => (
        <circle key={i} cx={x} cy={y} r="1.4" fill="currentColor" />
      ))}
    </svg>
  )
}

/* 领航（领航=下一步）：北极星 + 小星链指向——导航 */
function NorthIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <circle cx="18" cy="6" r="3.6" fill="currentColor" opacity="0.18" />
      <path d="M7.5 16.5L12 12L15 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="18" cy="6" r="2.1" fill="currentColor" />
      <circle cx="7.5" cy="16.5" r="1.2" fill="currentColor" />
      <circle cx="12" cy="12" r="1.3" fill="currentColor" />
      <circle cx="15" cy="9" r="1.1" fill="currentColor" />
    </svg>
  )
}

/* 传光（传光=发送）：星沿弧线射出 */
function SendLightIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M5 19Q10 15 14 10T18 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="18.5" cy="4.5" r="1.9" fill="currentColor" />
    </svg>
  )
}

/* 拾入（拾入=上传）：星落向收集线 */
function GatherIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M5 4Q12 9 12 15" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="12" cy="15.5" r="1.7" fill="currentColor" />
      <path d="M6 20L18 20" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
    </svg>
  )
}

/* 夜谈（夜谈=会话）：双星对望连线 */
function TalkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M9.2 10.5Q12.5 12.5 15.5 13.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="7" cy="9" r="1.7" fill="currentColor" />
      <circle cx="17" cy="14.5" r="1.7" fill="currentColor" />
    </svg>
  )
}

/* 调光（调光=设置）：星在圆环中心 + 光晕 */
function TuneIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
      <circle cx="12" cy="12" r="3.4" fill="currentColor" opacity="0.2" />
      <circle cx="12" cy="12" r="1.8" fill="currentColor" />
    </svg>
  )
}

/* 萃光（萃光=蒸馏）：星落入杯——萃取书的光华 */
function DistillIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M6 9Q6 19 12 19Q18 19 18 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <path d="M4 9L20 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="12" cy="4.5" r="1.7" fill="currentColor" />
    </svg>
  )
}

/* 星阁（星阁=星阁）：阁形 + 门内星光 */
function PavilionIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path d="M6 19L12 9L18 19" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" fill="none" />
      <path d="M4 19L20 19" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" fill="none" />
      <circle cx="12" cy="14.5" r="1.6" fill="currentColor" />
    </svg>
  )
}

export type IconName =
  | 'arrow-right'
  | 'bell'
  | 'book'
  | 'brain'
  | 'check'
  | 'chevron-right'
  | 'code'
  | 'copy'
  | 'distill'
  | 'download'
  | 'file'
  | 'flame'
  | 'history'
  | 'image'
  | 'loader'
  | 'north'
  | 'panels'
  | 'paperclip'
  | 'pavilion'
  | 'plus'
  | 'search'
  | 'send-light'
  | 'thumbs-down'
  | 'thumbs-up'
  | 'trash'
  | 'user'
  | 'users'
  | 'wrench'
  | 'x'

type IconProps = { size?: number; strokeWidth?: number; className?: string }
const MAP: Record<IconName, ComponentType<IconProps> | LucideIcon> = {
  'arrow-right': ArrowRight,
  bell: Bell,
  book: ChartIcon, // 星图（学习路径）
  brain: DustIcon, // 星尘（记忆）
  check: Check,
  'chevron-right': ChevronRight,
  code: Code,
  copy: Copy,
  distill: DistillIcon, // 萃光（蒸馏）
  download: Download,
  file: FileText,
  flame: Flame,
  history: TalkIcon, // 夜谈（会话）
  image: ImageIcon,
  loader: Loader2,
  north: NorthIcon, // 领航（下一步）
  panels: LayoutPanelLeft,
  paperclip: GatherIcon, // 拾入（上传）
  pavilion: PavilionIcon, // 星阁（星阁）
  plus: Plus,
  search: Search,
  'send-light': SendLightIcon, // 传光（发送）
  'thumbs-down': ThumbsDown,
  'thumbs-up': ThumbsUp,
  trash: Trash2,
  user: User,
  users: StarsIcon, // 问星（会议）
  wrench: TuneIcon, // 调光（设置）
  x: X,
}

export default function Icon({
  name,
  size = 16,
  className = '',
}: {
  name: IconName
  size?: number
  className?: string
}) {
  const C = MAP[name]
  return <C size={size} strokeWidth={1.5} className={className} aria-hidden />
}
