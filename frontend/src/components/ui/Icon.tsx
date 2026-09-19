/* 图标统一封装（星座语言 v3：夜空中拾光——星点+星图连线，品牌入口图标）
   - 品牌图标（手绘 SVG）：星尘/问星/星图/领航/传光/拾入/夜谈/调光/萃光/星阁——星=光点，线=星座连线
   - 通用操作保留 lucide（arrow-right/check/x/plus 等——基础操作不改=用户认识度优先）
   风格：星点 fill currentColor + 连线 1.5px stroke currentColor（与 lucide 同粗），24x24 viewBox */
import type { ComponentType } from 'react'
import {
  ActivityIcon,
  AlertTriangleIcon,
  ArrowLeftIcon,
  ArrowRightIcon,
  BellIcon,
  BookIcon,
  CameraIcon,
  CheckIcon,
  ChevronRightIcon,
  CodeIcon,
  CopyIcon,
  DatabaseIcon,
  DownloadIcon,
  FileIcon,
  FlameIcon,
  GridIcon,
  ImageIcon,
  InfoIcon,
  LoaderIcon,
  LogoutIcon,
  MaximizeIcon,
  MicIcon,
  PaletteIcon,
  PanelsIcon,
  PlusIcon,
  RefreshIcon,
  RouteIcon,
  SearchIcon,
  ServerIcon,
  SettingsIcon,
  ShareIcon,
  ShieldIcon,
  SparklesIcon,
  StarIcon,
  SproutIcon,
  ThumbsDownIcon,
  ThumbsUpIcon,
  TrashIcon,
  TrendingUpIcon,
  UserIcon,
  VolumeIcon,
  XIcon,
} from './icon-set'

/* ===== 星座品牌图标（手绘 SVG，星点+连线语言） ===== */

/* 星尘（星尘=记忆）：散落的星 + 收集弧线 */
function DustIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path
        d="M7 18Q12 16 17 18"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
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
    [6, 8],
    [10, 6],
    [13, 8],
    [9, 10],
    [15, 11],
    [17, 14],
    [19, 17],
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
      <path
        d="M7.5 16.5L12 12L15 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
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
      <path
        d="M5 19Q10 15 14 10T18 4.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="18.5" cy="4.5" r="1.9" fill="currentColor" />
    </svg>
  )
}

/* 拾入（拾入=上传）：星落向收集线 */
function GatherIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path
        d="M5 4Q12 9 12 15"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="12" cy="15.5" r="1.7" fill="currentColor" />
      <path
        d="M6 20L18 20"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
    </svg>
  )
}

/* 夜谈（夜谈=会话）：双星对望连线 */
function TalkIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path
        d="M9.2 10.5Q12.5 12.5 15.5 13.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
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
      <path
        d="M6 9Q6 19 12 19Q18 19 18 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <path
        d="M4 9L20 9"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="12" cy="4.5" r="1.7" fill="currentColor" />
    </svg>
  )
}

/* 星阁（星阁=星阁）：阁形 + 门内星光 */
function PavilionIcon() {
  return (
    <svg viewBox="0 0 24 24" width="1em" height="1em" fill="none" aria-hidden>
      <path
        d="M6 19L12 9L18 19"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M4 19L20 19"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        fill="none"
      />
      <circle cx="12" cy="14.5" r="1.6" fill="currentColor" />
    </svg>
  )
}

export type IconName =
  | 'activity'
  | 'alert'
  | 'arrow-left'
  | 'arrow-right'
  | 'bell'
  | 'book'
  | 'book-open'
  | 'brain'
  | 'camera'
  | 'check'
  | 'chevron-right'
  | 'code'
  | 'copy'
  | 'database'
  | 'distill'
  | 'download'
  | 'file'
  | 'flame'
  | 'grid'
  | 'history'
  | 'image'
  | 'info'
  | 'loader'
  | 'logout'
  | 'mic'
  | 'maximize'
  | 'north'
  | 'palette'
  | 'panels'
  | 'paperclip'
  | 'pavilion'
  | 'plus'
  | 'refresh'
  | 'route'
  | 'search'
  | 'send-light'
  | 'server'
  | 'settings'
  | 'share'
  | 'shield'
  | 'sparkles'
  | 'star'
  | 'sprout'
  | 'thumbs-down'
  | 'thumbs-up'
  | 'trash'
  | 'trending-up'
  | 'user'
  | 'users'
  | 'volume'
  | 'wrench'
  | 'x'

type IconProps = { size?: number; strokeWidth?: number; className?: string }
/* 2026-08-29 定制图标集替换 lucide：全部自绘（icon-set.tsx，圆润线条+星点语言与精灵同源）。
   品牌图标（星尘/问星/星图等）保留手绘版。 */
const MAP: Record<IconName, ComponentType<IconProps>> = {
  activity: ActivityIcon,
  alert: AlertTriangleIcon,
  'arrow-left': ArrowLeftIcon,
  'arrow-right': ArrowRightIcon,
  bell: BellIcon,
  book: ChartIcon, // 星图（学习路径）
  'book-open': BookIcon, // 记忆/知识库（翻开的书）
  brain: DustIcon, // 星尘（记忆）
  camera: CameraIcon,
  check: CheckIcon,
  'chevron-right': ChevronRightIcon,
  code: CodeIcon,
  copy: CopyIcon,
  database: DatabaseIcon,
  distill: DistillIcon, // 萃光（蒸馏）
  download: DownloadIcon,
  file: FileIcon,
  flame: FlameIcon,
  grid: GridIcon,
  history: TalkIcon, // 夜谈（会话）
  image: ImageIcon,
  info: InfoIcon,
  loader: LoaderIcon,
  logout: LogoutIcon,
  mic: MicIcon,
  maximize: MaximizeIcon,
  north: NorthIcon, // 领航（下一步）
  palette: PaletteIcon,
  panels: PanelsIcon,
  paperclip: GatherIcon, // 拾入（上传）
  pavilion: PavilionIcon, // 星阁（星阁）
  plus: PlusIcon,
  refresh: RefreshIcon,
  route: RouteIcon,
  search: SearchIcon,
  'send-light': SendLightIcon, // 传光（发送）
  server: ServerIcon,
  settings: SettingsIcon,
  share: ShareIcon,
  shield: ShieldIcon,
  sparkles: SparklesIcon,
  star: StarIcon,
  sprout: SproutIcon,
  'thumbs-down': ThumbsDownIcon,
  'thumbs-up': ThumbsUpIcon,
  trash: TrashIcon,
  'trending-up': TrendingUpIcon,
  user: UserIcon,
  users: StarsIcon, // 问星（会议）
  volume: VolumeIcon,
  wrench: TuneIcon, // 调光（设置）
  x: XIcon,
}

export default function Icon({
  name,
  size = 16,
  strokeWidth = 1.5,
  className = '',
}: {
  name: IconName
  size?: number
  strokeWidth?: number
  className?: string
}) {
  const C = MAP[name]
  return <C size={size} strokeWidth={strokeWidth} className={className} aria-hidden />
}
