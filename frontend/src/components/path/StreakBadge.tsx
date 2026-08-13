import Icon from '../ui/Icon'

/* streak 火焰徽章：M6 起接 daily_activity 真数据；0/null 时诚实空态（不虚构） */
export default function StreakBadge({ streak }: { streak: number | null }) {
  if (!streak || streak <= 0) {
    return (
      <div className="flex items-center gap-1.5 text-[12px] text-[rgba(236,233,225,0.35)]">
        <Icon name="flame" size={14} className="animate-flame text-warning/60" />
        <span>今天还没学习——学完说一声，火焰为你点亮</span>
      </div>
    )
  }
  return (
    <div className="flex items-center gap-1.5 text-[12px] text-[rgba(236,233,225,0.8)]">
      <Icon name="flame" size={14} className="animate-flame text-warning" />
      <span>
        连续学习 <span className="font-logo text-primary text-[16px]">{streak}</span> 天
      </span>
    </div>
  )
}
