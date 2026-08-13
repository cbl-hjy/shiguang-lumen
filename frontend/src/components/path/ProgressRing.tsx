/* 进度圆环：SVG 圆弧 + 数字（1s 填充动画；无数据显示空态） */
interface Props {
  value: number | null
  label: string
}

export default function ProgressRing({ value, label }: Props) {
  const size = 84
  const stroke = 5
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value / 100))

  return (
    <div className="group flex flex-col items-center gap-1.5">
      <div
        className="relative transition-all duration-300 group-hover:drop-shadow-[0_0_10px_rgba(62,201,176,0.25)]"
        style={{ width: size, height: size }}
      >
        <svg width={size} height={size} className="-rotate-90">
          <circle
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke="rgba(255,255,255,0.1)"
            strokeWidth={stroke}
          />
          {value !== null && (
            <circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              fill="none"
              stroke="var(--color-primary)"
              strokeWidth={stroke}
              strokeLinecap="round"
              strokeDasharray={c}
              strokeDashoffset={c * (1 - pct)}
              style={{ transition: 'stroke-dashoffset 1s cubic-bezier(0.22,1,0.36,1)' }}
            />
          )}
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="font-logo text-[18px] text-primary">
            {value === null ? '—' : `${Math.round(pct * 100)}%`}
          </span>
        </div>
      </div>
      <span className="text-[11px] text-[rgba(236,233,225,0.45)]">{label}</span>
    </div>
  )
}
