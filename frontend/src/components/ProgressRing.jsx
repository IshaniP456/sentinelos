// Circular progress ring — the headline visual for how full a zone is.
// Color follows the status tone; a soft glow adds drama without noise.

const TONE_HEX = {
  green: '#34d399',
  amber: '#f59e0b',
  red: '#fb5a5a',
  blue: '#6aa8ff',
  gray: '#7c7a85',
}

export default function ProgressRing({
  value, // 0..100
  tone = 'green',
  size = 132,
  stroke = 10,
  label,
  sublabel,
  projected, // optional 0..100 overlay (counterfactual)
}) {
  const pct = Math.max(0, Math.min(100, value))
  const r = (size - stroke) / 2
  const c = 2 * Math.PI * r
  const dash = (pct / 100) * c
  const color = TONE_HEX[tone] || TONE_HEX.gray
  const hasProj = typeof projected === 'number' && Math.round(projected) !== Math.round(pct)
  const projDash = hasProj ? (Math.max(0, Math.min(100, projected)) / 100) * c : 0

  return (
    <div className="relative inline-flex items-center justify-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-90">
        {/* track */}
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#2c2a31" strokeWidth={stroke} />
        {/* projected (faint arc — the counterfactual) */}
        {hasProj && (
          <circle
            cx={size / 2} cy={size / 2} r={r} fill="none"
            stroke={color} strokeOpacity="0.3" strokeWidth={stroke + 3}
            strokeDasharray={`${projDash} ${c}`} strokeLinecap="round"
          />
        )}
        {/* actual */}
        <circle
          cx={size / 2} cy={size / 2} r={r} fill="none"
          stroke={color} strokeWidth={stroke}
          strokeDasharray={`${dash} ${c}`} strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 600ms cubic-bezier(.2,.8,.2,1)', filter: `drop-shadow(0 0 6px ${color}66)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-2xl font-bold text-white">{Math.round(pct)}%</span>
        {label && <span className="mt-0.5 text-[11px] font-semibold uppercase tracking-wider text-slate-400">{label}</span>}
        {sublabel && <span className="font-mono text-[11px] text-slate-500">{sublabel}</span>}
      </div>
    </div>
  )
}
