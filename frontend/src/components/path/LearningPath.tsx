/* 学习路径：目标/主题节点链（可汗范式：主干队列 + 状态圆点） */
interface Topic {
  title: string
  status: string
  date: string
}

export default function LearningPath({ topics }: { topics: Topic[] }) {
  if (topics.length === 0) {
    /* 空状态统一语言：一粒光 + 虚线轨迹（.empty-light / .empty-trail） */
    return (
      <div className="flex items-center gap-2.5 py-2">
        <span className="empty-light shrink-0" />
        <span className="empty-trail shrink-0" />
        <span className="text-[12px] text-[rgba(236,233,225,0.4)] leading-relaxed">
          告诉我"我想学 XX"，拾光会为你点亮第一站。
        </span>
      </div>
    )
  }
  return (
    <div className="flex flex-col">
      {topics.map((t, i) => (
        <div key={`${t.title}-${i}`} className="group flex gap-3">
          <div className="flex flex-col items-center">
            <span className="w-2.5 h-2.5 mt-1 rounded-full bg-primary shadow-[0_0_8px_rgba(62,201,176,0.5)] transition-shadow duration-200 group-hover:shadow-[0_0_14px_rgba(62,201,176,0.8)]" />
            {i < topics.length - 1 && (
              <span className="w-px flex-1 min-h-4 bg-hairline" />
            )}
          </div>
          <div className="pb-4">
            <div className="text-[13px] text-[rgba(236,233,225,0.9)] transition-colors duration-150 group-hover:text-primary">
              {t.title}
            </div>
            <div className="text-[11px] text-[rgba(236,233,225,0.4)] mt-0.5">
              {t.status === 'active' ? '学习中' : t.status} · {t.date}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
