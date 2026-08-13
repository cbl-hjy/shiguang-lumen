/* 线性图标统一封装（lucide-react，1.5px 细线，颜色继承 currentColor）
   "拾光"主题图标：去 emoji 化，前沿 agent 线性风格 */
import {
  ArrowRight,
  Bell,
  BookOpen,
  Brain,
  Check,
  ChevronRight,
  Code,
  Copy,
  Download,
  FileText,
  Flame,
  History,
  Image as ImageIcon,
  LayoutPanelLeft,
  Loader2,
  Paperclip,
  Plus,
  Search,
  ThumbsDown,
  ThumbsUp,
  Trash2,
  User,
  Wrench,
  X,
  type LucideIcon,
} from 'lucide-react'

export type IconName =
  | 'arrow-right'
  | 'bell'
  | 'book'
  | 'brain'
  | 'check'
  | 'chevron-right'
  | 'code'
  | 'copy'
  | 'download'
  | 'file'
  | 'flame'
  | 'history'
  | 'image'
  | 'loader'
  | 'panels'
  | 'paperclip'
  | 'plus'
  | 'search'
  | 'thumbs-down'
  | 'thumbs-up'
  | 'trash'
  | 'user'
  | 'wrench'
  | 'x'

const MAP: Record<IconName, LucideIcon> = {
  'arrow-right': ArrowRight,
  bell: Bell,
  book: BookOpen,
  brain: Brain,
  check: Check,
  'chevron-right': ChevronRight,
  code: Code,
  copy: Copy,
  download: Download,
  file: FileText,
  flame: Flame,
  history: History,
  image: ImageIcon,
  loader: Loader2,
  panels: LayoutPanelLeft,
  paperclip: Paperclip,
  plus: Plus,
  search: Search,
  'thumbs-down': ThumbsDown,
  'thumbs-up': ThumbsUp,
  trash: Trash2,
  user: User,
  wrench: Wrench,
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
