// Pill tab navigation. The active pill is the signature gold.
export default function TabNav({ tabs, active, onChange }) {
  return (
    <nav className="inline-flex flex-wrap gap-1 rounded-2xl border border-ink-500/70 bg-ink-800/70 p-1 backdrop-blur-sm">
      {tabs.map((t) => {
        const isActive = t.id === active
        return (
          <button
            key={t.id}
            className={`tab ${isActive ? 'tab-active' : ''}`}
            onClick={() => onChange(t.id)}
            aria-current={isActive ? 'page' : undefined}
          >
            {isActive && (
              <span className="absolute inset-0 -z-0 rounded-xl bg-brand shadow-glow" aria-hidden />
            )}
            <span className="relative z-10 flex items-center gap-2">
              {t.icon}
              {t.label}
            </span>
          </button>
        )
      })}
    </nav>
  )
}
