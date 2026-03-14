import { useState, useEffect, useRef } from 'react'
import {
  fetchAuditLog,
  fetchLatestVitals,
  startSimulator,
  stopSimulator,
  fetchSimulatorStatus,
  type AuditEntry,
  type LatestVitals,
  type SimulatorStatus,
} from '../../../lib/sentinelApi'
import { SentinelLayout } from './_SentinelNav'

// ─── Premium Beige Palette ────────────────────────────────────────────────────
// bg-page:       #f4ead8   warm parchment
// bg-card:       #fdfaf2   warm cream
// bg-inset:      #f0e6d0   deeper parchment for code/mono areas
// border:        #ddd0b6   warm gold-tan
// border-subtle: #ebe1ce   barely-there dividers
// text-espresso: #271a0c   near-black warm brown  (headers)
// text-sienna:   #6b5438   mid warmth             (body)
// text-taupe:    #9b8768   muted warmth            (labels/caps)
// accent-teal:   #1a6b58   deep forest green
// accent-gold:   #a06a20   antique gold
// danger:        #a8291e   deep crimson
// danger-bg:     #f9eeec   crimson wash
// amber:         #c07010   rich amber
// amber-bg:      #fdf3e7   amber wash
// surface-nav:   #ede0ca   parchment nav

function cx(...c: (string | false | undefined | null)[]) { return c.filter(Boolean).join(' ') }

// ─── Vital definitions for threshold checking ─────────────────────────────────

interface VitalDef { key: string; label: string; unit: string; low: number; high: number }
const VITAL_DEFS: VitalDef[] = [
  { key: 'heart_rate',          label: 'Heart Rate',       unit: 'bpm',  low: 60,   high: 100  },
  { key: 'spo2',                label: 'SpO₂',             unit: '%',    low: 95,   high: 100  },
  { key: 'respiratory_rate',    label: 'Respiratory Rate', unit: '/min', low: 12,   high: 20   },
  { key: 'body_temperature',    label: 'Temperature',      unit: '°C',   low: 36,   high: 37.5 },
  { key: 'hrv_ms',              label: 'HRV (RMSSD)',      unit: 'ms',   low: 20,   high: 80   },
  { key: 'ecg_st_deviation_mm', label: 'ECG ST Deviation', unit: 'mm',   low: -0.5, high: 0.5  },
  { key: 'ecg_qtc_ms',          label: 'ECG QTc',          unit: 'ms',   low: 380,  high: 440  },
  { key: 'stress_score',        label: 'Stress Score',     unit: '',     low: 0,    high: 50   },
]

function getAbnormalVitals(snap: Record<string, number | null>) {
  return VITAL_DEFS.filter(v => {
    const val = snap[v.key]
    return val != null && (val < v.low || val > v.high)
  }).map(v => ({
    ...v,
    value: snap[v.key] as number,
    direction: (snap[v.key] as number) > v.high ? 'HIGH' as const : 'LOW' as const,
    delta: (snap[v.key] as number) > v.high
      ? `+${((snap[v.key] as number) - v.high).toFixed(1)} above ${v.high}${v.unit}`
      : `${((snap[v.key] as number) - v.low).toFixed(1)} below ${v.low}${v.unit}`,
  }))
}

// ─── Subcomponents ────────────────────────────────────────────────────────────

function Card({ children, className = '', glow, onClick }: {
  children: React.ReactNode; className?: string; glow?: 'red' | 'amber' | 'green'; onClick?: () => void
}) {
  const glowMap = { red: 'shadow-[0_4px_20px_rgba(168,41,30,0.12)]', amber: 'shadow-[0_4px_20px_rgba(192,112,16,0.12)]', green: 'shadow-[0_4px_20px_rgba(26,107,88,0.12)]' }
  return (
    <div
      className={cx('rounded-2xl border bg-[#fdfaf2] border-[#ddd0b6] shadow-[0_2px_8px_rgba(60,35,10,0.05)]', glow && glowMap[glow], className)}
      onClick={onClick}
    >{children}</div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#9b8768] mb-3">{children}</p>
}

function ECGStrip({ hr }: { hr: number }) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const dataRef = useRef<number[]>(Array(200).fill(0))
  const phaseRef = useRef(0)
  useEffect(() => {
    const canvas = canvasRef.current; if (!canvas) return
    const ctx = canvas.getContext('2d')!
    const draw = () => {
      phaseRef.current += (hr / 60) * 0.12
      const p = phaseRef.current % 1
      let y = 0
      if (p < 0.08) y = 0
      else if (p < 0.13) y = -0.4 * Math.sin(Math.PI * (p - 0.08) / 0.05)
      else if (p < 0.18) y = 0
      else if (p < 0.22) y = -3.5 * Math.sin(Math.PI * (p - 0.18) / 0.04)
      else if (p < 0.26) y = 0.5 * Math.sin(Math.PI * (p - 0.22) / 0.04)
      else if (p < 0.32) y = -0.3 * Math.sin(Math.PI * (p - 0.26) / 0.06)
      dataRef.current.push(y); if (dataRef.current.length > 200) dataRef.current.shift()
      const w = canvas.width, h = canvas.height
      ctx.clearRect(0, 0, w, h)
      ctx.strokeStyle = 'rgba(160,140,100,0.18)'; ctx.lineWidth = 0.5
      for (let i = 0; i < w; i += 20) { ctx.beginPath(); ctx.moveTo(i, 0); ctx.lineTo(i, h); ctx.stroke() }
      for (let j = 0; j < h; j += 20) { ctx.beginPath(); ctx.moveTo(0, j); ctx.lineTo(w, j); ctx.stroke() }
      const grad = ctx.createLinearGradient(0, 0, w, 0)
      grad.addColorStop(0, 'rgba(26,107,88,0)'); grad.addColorStop(0.3, 'rgba(26,107,88,0.7)'); grad.addColorStop(1, 'rgba(26,107,88,1)')
      ctx.strokeStyle = grad; ctx.lineWidth = 2; ctx.shadowColor = '#1a6b58'; ctx.shadowBlur = 3
      ctx.beginPath()
      dataRef.current.forEach((v, i) => { const x = (i / dataRef.current.length) * w, vy = h / 2 + v * (h * 0.18); i === 0 ? ctx.moveTo(x, vy) : ctx.lineTo(x, vy) })
      ctx.stroke(); ctx.shadowBlur = 0
    }
    const id = setInterval(draw, 40); return () => clearInterval(id)
  }, [hr])
  return <canvas ref={canvasRef} width={340} height={80} className="w-full rounded-lg bg-[#f0e6d0] border border-[#ddd0b6]" />
}

function RiskOrb({ score }: { score: number }) {
  const color = score >= 70 ? '#a8291e' : score >= 50 ? '#c07010' : '#1a6b58'
  return (
    <div className="relative flex items-center justify-center" style={{ width: 180, height: 180 }}>
      <svg width="180" height="180" className="absolute inset-0" style={{ transform: 'rotate(-90deg)' }}>
        <circle cx="90" cy="90" r="78" fill="none" stroke="#e5d9c3" strokeWidth="8" />
        <circle cx="90" cy="90" r="78" fill="none" stroke={color} strokeWidth="8"
          strokeDasharray={`${2 * Math.PI * 78}`} strokeDashoffset={`${2 * Math.PI * 78 * (1 - score / 100)}`}
          strokeLinecap="round" style={{ filter: `drop-shadow(0 0 6px ${color}55)`, transition: 'stroke-dashoffset 1s ease' }} />
      </svg>
      <div className="text-center z-10">
        <div className="text-4xl font-black" style={{ color }}>{Math.round(score)}</div>
        <div className="text-xs text-[#9b8768] mt-0.5">/ 100</div>
      </div>
    </div>
  )
}

function VitalCard({ label, value, unit, normal }: { label: string; value: number; unit: string; normal: [number, number] }) {
  const [low, high] = normal
  const isAbnormal = value < low || value > high
  const isHi = value > high
  const pct = Math.min(Math.max((value - low * 0.5) / (high * 1.5 - low * 0.5), 0), 1)
  return (
    <Card className={cx('p-4', isAbnormal && 'border-[#c0701050]')}>
      <SectionLabel>{label}</SectionLabel>
      <div className="flex items-baseline gap-1 mb-3">
        <span className={cx('text-2xl font-black', isAbnormal ? 'text-[#a8291e]' : 'text-[#271a0c]')}>{value}</span>
        <span className="text-xs text-[#9b8768]">{unit}</span>
        {isAbnormal && <span className="ml-auto text-[10px] font-bold text-[#a8291e]">{isHi ? '↑' : '↓'}</span>}
      </div>
      <div className="h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden">
        <div className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct * 100}%`, background: isAbnormal ? '#a8291e' : '#1a6b58' }} />
      </div>
    </Card>
  )
}

function RiskBadge({ band, score }: { band: string; score?: number }) {
  const s = band === 'CRITICAL' ? 'bg-[#a8291e] text-white' :
    band === 'HIGH' ? 'bg-[#c07010] text-white' :
    band === 'WARNING' ? 'bg-[#fdf3e7] text-[#c07010] border border-[#c0701040]' :
    'bg-[#edf7f4] text-[#1a6b58] border border-[#1a6b5830]'
  return <span className={`px-2.5 py-1 rounded-xl text-xs font-bold ${s}`}>{band}{score !== undefined ? ` · ${score.toFixed(1)}` : ''}</span>
}

// ─── XAI Explanation Drawer (uses real AuditEntry) ────────────────────────────

function XAIDrawer({ entry, onClose }: { entry: AuditEntry; onClose: () => void }) {
  const band = entry.shal_band
  const levelColor = band === 'CRITICAL' ? '#a8291e' : band === 'HIGH' ? '#c07010' : '#1a6b58'
  const levelBg   = band === 'CRITICAL' ? '#f9eeec' : band === 'HIGH' ? '#fdf3e7' : '#edf7f4'

  const snap = entry.vitals_snapshot ?? {}
  const abnormal = getAbnormalVitals(snap)

  // Parse LLM thinking chain into steps
  const thinkingSteps = entry.llm_thinking_chain
    ? entry.llm_thinking_chain.split(/\n+/).map(s => s.trim()).filter(s => s.length > 15)
    : []

  // Build action summary
  const actionsTaken: { label: string; detail: string }[] = []
  if (entry.ems_dispatched)      actionsTaken.push({ label: 'EMS Dispatch', detail: `HTTP ${entry.ems_response_code ?? '—'} · Emergency services notified` })
  if (entry.sms_sent)            actionsTaken.push({ label: 'SMS Alert', detail: 'On-call nurse and physician notified via SMS' })
  if (entry.email_sent)          actionsTaken.push({ label: 'Email Notification', detail: 'Detailed SHAL report sent to responsible consultant' })
  if (entry.fcm_sent)            actionsTaken.push({ label: 'Push Notification', detail: 'Mobile push sent to nursing station app' })
  if (entry.appointment_booked)  actionsTaken.push({ label: 'Appointment Booked', detail: `Booking ID: ${entry.appointment_id ?? 'scheduled'}` })
  if (actionsTaken.length === 0) actionsTaken.push({ label: 'Logged Only', detail: 'Score below escalation threshold — internal record only' })

  // Approximate SHAL layer breakdown from available real data
  const synCount = entry.syndromes_fired?.length ?? 0
  const trendCount = entry.trends_fired?.length ?? 0
  const sl3Est = Math.min(synCount * 7, 30)
  const sl4Est = Math.min(trendCount * 5, 15)
  const remaining = Math.max(0, entry.final_score - sl3Est - sl4Est)
  const sl1Est = +(remaining * 0.50).toFixed(1)
  const sl2Est = +(remaining * 0.30).toFixed(1)
  const sl5Est = +(remaining * 0.20).toFixed(1)
  const shalLayers = [
    { layer: 'SL1 — Vital Thresholds',  pts: sl1Est, reason: `${abnormal.length} vital(s) outside normal range`,                             color: '#1a6b58' },
    { layer: 'SL2 — Trajectory',        pts: sl2Est, reason: 'Trend analysis across 12-tick sliding window',                                  color: '#2a7fa0' },
    { layer: 'SL3 — Syndromes',         pts: sl3Est, reason: `${synCount} clinical syndrome(s) matched: ${entry.syndromes_fired?.join(', ') || 'none'}`, color: '#5a4faa' },
    { layer: 'SL4 — Trends',            pts: sl4Est, reason: `${trendCount} deterioration trend(s) detected: ${entry.trends_fired?.join(', ') || 'none'}`, color: '#c07010' },
    { layer: 'SL5 — Isolation Forest',  pts: sl5Est, reason: entry.decision_source === 'isolation_forest' ? 'ML anomaly confirmed pattern' : 'Context and signal quality modifiers', color: '#a8291e' },
  ]

  const time = new Date(entry.escalated_at).toLocaleTimeString()

  return (
    <div className="fixed inset-0 z-50 flex" style={{ fontFamily: 'inherit' }}>
      <div className="flex-1 bg-[#271a0c20]" onClick={onClose} />

      <div className="w-[520px] h-full bg-[#fdfaf2] border-l border-[#ddd0b6] shadow-[-8px_0_32px_rgba(60,35,10,0.12)] flex flex-col overflow-hidden">

        {/* Panel header */}
        <div className="px-6 py-5 border-b border-[#ebe1ce] shrink-0" style={{ background: levelBg }}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-[#9b8768]">XAI Explanation</span>
                <span className="px-2 py-0.5 rounded-lg text-[10px] font-bold" style={{ background: `${levelColor}18`, color: levelColor, border: `1px solid ${levelColor}30` }}>{band}</span>
                {entry.hard_override_active && (
                  <span className="px-2 py-0.5 rounded-lg text-[10px] font-bold bg-[#a8291e] text-white">OVERRIDE</span>
                )}
              </div>
              <p className="text-sm font-semibold text-[#271a0c] leading-snug">
                {entry.reasoning_summary?.slice(0, 120) ?? `SHAL Score ${entry.final_score.toFixed(1)} · ${band}`}
              </p>
              <div className="flex items-center gap-3 mt-2 text-xs text-[#9b8768]">
                <span className="font-mono">{time}</span>
                <span>·</span>
                <span>Patient {entry.patient_id}</span>
                <span>·</span>
                <span className="font-semibold" style={{ color: levelColor }}>
                  {actionsTaken.map(a => a.label.split(' ')[0]).join(' + ')}
                </span>
              </div>
            </div>
            <button onClick={onClose} className="w-8 h-8 rounded-xl bg-[#f0e6d0] hover:bg-[#e5d9c3] flex items-center justify-center transition-colors shrink-0">
              <svg className="w-4 h-4 text-[#6b5438]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/></svg>
            </button>
          </div>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-6">

          {/* 1. Vitals that crossed threshold */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>1</div>
              <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">What Crossed the Threshold</h3>
            </div>
            {abnormal.length === 0 ? (
              <p className="text-xs text-[#9b8768] italic">No individual vital threshold breaches — composite score from syndrome and trend layers.</p>
            ) : (
              <div className="space-y-2">
                {abnormal.map((v) => (
                  <div key={v.key} className="rounded-xl border border-[#ddd0b6] bg-[#f4ead8] p-3">
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-xs font-bold text-[#271a0c]">{v.label}</span>
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded" style={{ background: `${levelColor}20`, color: levelColor }}>
                        {v.direction}
                      </span>
                    </div>
                    <div className="grid grid-cols-3 gap-2 text-[10px]">
                      <div><span className="text-[#9b8768] block">Measured</span><span className="font-bold text-xs" style={{ color: levelColor }}>{v.value.toFixed(1)}{v.unit}</span></div>
                      <div><span className="text-[#9b8768] block">Range</span><span className="font-bold text-[#6b5438]">{v.low}–{v.high}{v.unit}</span></div>
                      <div><span className="text-[#9b8768] block">Delta</span><span className="font-bold text-[#a8291e]">{v.delta}</span></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* 2. Clinical narrative */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>2</div>
              <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">Clinical Significance</h3>
            </div>
            <div className="rounded-xl border border-[#ddd0b6] bg-[#f0e6d0] p-4">
              <p className="text-xs text-[#271a0c] leading-relaxed font-mono">
                {entry.reasoning_summary ?? 'No narrative available for this assessment level.'}
              </p>
            </div>
          </section>

          {/* 3. AI Reasoning Chain */}
          {thinkingSteps.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>3</div>
                <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">AI Reasoning Chain</h3>
                <span className="text-[10px] text-[#9b8768] ml-1">({entry.decision_source})</span>
              </div>
              <div className="space-y-2">
                {thinkingSteps.slice(0, 10).map((step, i) => (
                  <div key={i} className="flex gap-3 text-xs">
                    <div className="w-5 h-5 rounded-full border-2 border-[#ddd0b6] bg-[#fdfaf2] flex items-center justify-center font-bold text-[#9b8768] shrink-0 mt-0.5 text-[9px]">{i + 1}</div>
                    <p className="text-[#6b5438] leading-relaxed pt-0.5">{step}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 4. SHAL Score Breakdown */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>4</div>
              <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">SHAL Score Breakdown</h3>
              <span className="ml-auto text-sm font-black" style={{ color: levelColor }}>{entry.final_score.toFixed(1)} pts</span>
            </div>
            <div className="space-y-2">
              {shalLayers.map((l) => (
                <div key={l.layer} className="rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] p-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] font-bold" style={{ color: l.color }}>{l.layer}</span>
                    <span className="text-sm font-black" style={{ color: l.color }}>~{l.pts}</span>
                  </div>
                  <div className="h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden mb-2">
                    <div className="h-full rounded-full" style={{ width: `${Math.min(l.pts / entry.final_score * 100, 100)}%`, background: l.color }} />
                  </div>
                  <p className="text-[10px] text-[#9b8768] leading-relaxed">{l.reason}</p>
                </div>
              ))}
            </div>
          </section>

          {/* 5. Syndromes */}
          {entry.syndromes_fired && entry.syndromes_fired.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>5</div>
                <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">Clinical Syndromes Matched</h3>
              </div>
              <div className="flex flex-wrap gap-2">
                {entry.syndromes_fired.map(s => (
                  <span key={s} className="px-2.5 py-1.5 rounded-xl text-[10px] font-semibold bg-[#f9eeec] text-[#7a1e14] border border-[#a8291e25]">{s}</span>
                ))}
              </div>
            </section>
          )}

          {/* 6. Trends */}
          {entry.trends_fired && entry.trends_fired.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>6</div>
                <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">Deterioration Trends Detected</h3>
              </div>
              <div className="space-y-1.5">
                {entry.trends_fired.map(t => (
                  <div key={t} className="flex items-center gap-2 text-xs px-3 py-2 rounded-xl bg-[#fdf3e7] border border-[#c0701030]">
                    <span className="text-[#c07010] font-bold">↗</span>
                    <span className="text-[#6b5438]">{t}</span>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 7. Differential Diagnoses */}
          {entry.differential_diagnoses && entry.differential_diagnoses.length > 0 && (
            <section>
              <div className="flex items-center gap-2 mb-3">
                <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>7</div>
                <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">Differential Diagnoses</h3>
                {entry.confidence != null && (
                  <span className="ml-auto text-[10px] font-semibold text-[#1a6b58]">{Math.round(entry.confidence * 100)}% confidence</span>
                )}
              </div>
              <div className="space-y-2">
                {entry.differential_diagnoses.map((d, i) => (
                  <div key={i} className="rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] p-3">
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-xs font-semibold text-[#271a0c] flex-1">{d.dx}</span>
                      <div className="flex items-center gap-1.5">
                        <div className="w-16 h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden">
                          <div className="h-full rounded-full bg-[#1a6b58]" style={{ width: `${d.probability * 100}%` }} />
                        </div>
                        <span className="text-[10px] font-mono font-bold text-[#1a6b58] w-8 text-right">{Math.round(d.probability * 100)}%</span>
                      </div>
                    </div>
                    <p className="text-[10px] text-[#9b8768] leading-relaxed">{d.evidence}</p>
                  </div>
                ))}
              </div>
            </section>
          )}

          {/* 8. Actions taken */}
          <section>
            <div className="flex items-center gap-2 mb-3">
              <div className="w-5 h-5 rounded-lg flex items-center justify-center text-white text-[10px] font-black shrink-0" style={{ background: levelColor }}>8</div>
              <h3 className="text-xs font-bold uppercase tracking-[0.1em] text-[#271a0c]">Actions Taken</h3>
              {entry.actions_latency_ms != null && (
                <span className="ml-auto text-[10px] font-mono text-[#9b8768]">{entry.actions_latency_ms}ms total</span>
              )}
            </div>
            <div className="space-y-2">
              {actionsTaken.map((a, i) => (
                <div key={i} className="rounded-xl border border-[#ddd0b6] p-3" style={{ background: levelBg }}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="px-2 py-0.5 rounded-lg text-[10px] font-bold text-white" style={{ background: levelColor }}>{a.label}</span>
                  </div>
                  <p className="text-xs text-[#6b5438]">{a.detail}</p>
                </div>
              ))}
            </div>
          </section>

        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-[#ebe1ce] shrink-0 flex items-center justify-between bg-[#f4ead8]">
          <span className="text-[10px] text-[#9b8768]">
            SENTINEL AI · {entry.decision_source} · {entry.confidence != null ? `${Math.round(entry.confidence * 100)}% confidence` : 'rule-based'}
          </span>
          <button onClick={onClose} className="px-4 py-1.5 rounded-xl bg-[#1a6b58] text-white text-xs font-semibold hover:bg-[#155a49] transition-colors">
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Decision Log (uses real AuditEntry) ──────────────────────────────────────

function DecisionLog({ entries, onSelect }: { entries: AuditEntry[]; onSelect: (e: AuditEntry) => void }) {
  const bandStyle: Record<string, string> = {
    CRITICAL: 'text-[#a8291e] bg-[#f9eeec] border border-[#a8291e30]',
    HIGH:     'text-[#c07010] bg-[#fdf3e7] border border-[#c0701030]',
    WARNING:  'text-[#9b8768] bg-[#f4ead8] border border-[#9b876830]',
    NOMINAL:  'text-[#1a6b58] bg-[#edf7f4] border border-[#1a6b5830]',
  }

  function actionBadge(e: AuditEntry) {
    const acts: string[] = []
    if (e.ems_dispatched)     acts.push('EMS')
    if (e.sms_sent)           acts.push('SMS')
    if (e.email_sent)         acts.push('EMAIL')
    if (e.fcm_sent)           acts.push('FCM')
    if (e.appointment_booked) acts.push('APPT')
    if (acts.length === 0)    return e.fall_event_type && e.fall_event_type !== 'NONE' ? 'FALL' : 'LOG'
    return acts.join('+')
  }

  if (entries.length === 0) {
    return (
      <div className="text-center py-8 text-[#9b8768] text-xs">
        <p>No audit entries yet — backend simulation running…</p>
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {entries.map(e => (
        <div
          key={e.id}
          className="flex items-center gap-3 text-xs py-2.5 px-3 rounded-xl border border-transparent hover:border-[#ddd0b6] hover:bg-[#f4ead8] cursor-pointer transition-all group"
          onClick={() => onSelect(e)}
        >
          <span className="text-[#9b8768] font-mono shrink-0 w-16">
            {new Date(e.escalated_at).toLocaleTimeString()}
          </span>
          <span className={`px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0 ${bandStyle[e.shal_band] ?? bandStyle.NOMINAL}`}>
            {e.shal_band}
          </span>
          <span className="text-[#6b5438] leading-relaxed flex-1 truncate">
            {e.reasoning_summary
              ? e.reasoning_summary.slice(0, 80)
              : `Score ${e.final_score.toFixed(1)} · ${e.decision_source}`}
          </span>
          <span className="text-[#9b8768] shrink-0 font-mono text-[10px]">{actionBadge(e)}</span>
          <svg className="w-3.5 h-3.5 text-[#9b8768] opacity-0 group-hover:opacity-100 transition-opacity shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M9 18l6-6-6-6"/>
          </svg>
        </div>
      ))}
      <p className="text-[10px] text-[#9b8768] text-center pt-1">Click any entry to see full AI explanation</p>
    </div>
  )
}

// ─── Simulator Control Panel ──────────────────────────────────────────────────

const PATIENT_ID = 'P01'
const CSV_FILE   = 'dataset.csv'

function SimulatorPanel() {
  const [status, setStatus] = useState<SimulatorStatus | null>(null)
  const [busy, setBusy]     = useState(false)
  const [error, setError]   = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const s = await fetchSimulatorStatus(PATIENT_ID)
        if (!cancelled) setStatus(s)
      } catch {
        if (!cancelled) setStatus(null)
      }
    }
    poll()
    const id = setInterval(poll, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const running = status?.is_running ?? false
  const pct = status && status.total_rows > 0
    ? Math.round((status.current_row_index / status.total_rows) * 100)
    : 0

  async function handleStop() {
    setBusy(true); setError(null)
    try { await stopSimulator(PATIENT_ID); setStatus(null) }
    catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  async function handleRestart() {
    setBusy(true); setError(null)
    try {
      await stopSimulator(PATIENT_ID)
      await startSimulator(PATIENT_ID, CSV_FILE, 0.5)
    } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }

  return (
    <Card className="p-4">
      <div className="flex items-center gap-4 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <span className={cx('w-2.5 h-2.5 rounded-full shrink-0',
            running ? 'bg-[#1a6b58] animate-pulse' : 'bg-[#9b8768]')}/>
          <span className="text-xs font-bold text-[#271a0c]">
            {running ? 'BACKEND SIMULATING' : status === null ? 'CONNECTING…' : 'STOPPED'}
          </span>
        </div>
        <span className="h-4 w-px bg-[#ddd0b6]"/>
        <div className="flex items-center gap-1.5 text-xs text-[#9b8768]">
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
          <span className="font-mono">{CSV_FILE}</span>
          <span>·</span>
          <span>Patient <span className="font-semibold text-[#271a0c]">{PATIENT_ID}</span></span>
          {status && <><span>·</span><span className="font-mono">{status.ticks_sent} readings sent</span></>}
        </div>
        {status && status.total_rows > 0 && (
          <div className="flex items-center gap-2 flex-1 min-w-[140px]">
            <div className="flex-1 h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden">
              <div className="h-full rounded-full bg-[#1a6b58] transition-all duration-700" style={{ width: `${pct}%` }} />
            </div>
            <span className="text-[10px] font-mono text-[#9b8768] shrink-0">
              row {status.current_row_index}/{status.total_rows}
            </span>
          </div>
        )}
        <div className="ml-auto flex items-center gap-2 shrink-0">
          {error && <span className="text-[10px] text-[#a8291e] max-w-[180px] truncate">{error}</span>}
          <button onClick={handleRestart} disabled={busy}
            className="px-3 py-1.5 rounded-xl bg-[#f0e6d0] text-[#6b5438] text-xs font-semibold border border-[#ddd0b6] hover:bg-[#e5d9c3] transition-colors disabled:opacity-50">
            ↺ Restart
          </button>
          {running && (
            <button onClick={handleStop} disabled={busy}
              className="px-3 py-1.5 rounded-xl bg-[#f9eeec] text-[#a8291e] text-xs font-semibold border border-[#a8291e30] hover:bg-[#f0ddd9] transition-colors disabled:opacity-50">
              ■ Stop
            </button>
          )}
        </div>
      </div>
    </Card>
  )
}

// ─── Main Dashboard ───────────────────────────────────────────────────────────

export function Dashboard() {
  const [tick, setTick] = useState(0)
  const [selectedEntry, setSelectedEntry] = useState<AuditEntry | null>(null)
  const [liveEntry, setLiveEntry] = useState<AuditEntry | null>(null)
  const [recentEntries, setRecentEntries] = useState<AuditEntry[]>([])
  const [latestVitals, setLatestVitals] = useState<LatestVitals | null>(null)

  useEffect(() => { const id = setInterval(() => setTick(t => t + 1), 3000); return () => clearInterval(id) }, [])

  // Poll audit log for risk scores, syndromes, differentials
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const res = await fetchAuditLog(10)
        if (!cancelled && res.entries.length > 0) {
          setLiveEntry(res.entries[0])
          setRecentEntries(res.entries)
        }
      } catch { /* backend not reachable */ }
    }
    poll()
    const id = setInterval(poll, 3000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Poll latest raw vitals (includes lat/lng, ECG, sleep, steps — every reading from CSV)
  useEffect(() => {
    let cancelled = false
    async function pollVitals() {
      try {
        const lv = await fetchLatestVitals('P01')
        if (!cancelled) setLatestVitals(lv)
      } catch { /* backend not reachable or no data yet */ }
    }
    pollVitals()
    const id = setInterval(pollVitals, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Vitals: latestVitals (fresh from CSV) > vitals_snapshot (from audit log) > animated placeholder
  const snap      = liveEntry?.vitals_snapshot ?? {}
  const lv        = latestVitals
  const riskScore = liveEntry ? liveEntry.final_score : 45 + Math.sin(tick * 0.4) * 8
  const hr        = lv?.heart_rate          ?? snap.heart_rate          ?? 72 + Math.sin(tick * 0.3) * 6
  const spo2      = lv?.spo2                ?? snap.spo2                ?? 97 - Math.sin(tick * 0.2) * 0.8
  const rr        = lv?.respiratory_rate    ?? snap.respiratory_rate    ?? 16 + Math.sin(tick * 0.5) * 2
  const temp      = lv?.body_temperature    ?? snap.body_temperature    ?? 36.8 + Math.sin(tick * 0.1) * 0.2
  const hrv       = lv?.hrv_ms             ?? snap.hrv_ms              ?? 45 + Math.sin(tick * 0.4) * 8
  const stress    = lv?.stress_score        ?? snap.stress_score        ?? null
  const steps     = lv?.steps_per_hour      ?? snap.steps_per_hour      ?? null
  const ecgST     = lv?.ecg_st_deviation_mm ?? snap.ecg_st_deviation_mm ?? null
  const ecgQTc    = lv?.ecg_qtc_ms          ?? snap.ecg_qtc_ms          ?? null
  const sleepEff  = lv?.sleep_efficiency    ?? snap.sleep_efficiency    ?? null
  const deepSleep = lv?.deep_sleep_pct      ?? snap.deep_sleep_pct      ?? null
  const band      = liveEntry?.shal_band ?? (riskScore >= 75 ? 'CRITICAL' : riskScore >= 60 ? 'HIGH' : riskScore >= 35 ? 'WARNING' : 'NOMINAL')

  // Live XAI panel data from most recent audit entry
  const liveSyndromes  = liveEntry?.syndromes_fired  ?? []
  const liveTrends     = liveEntry?.trends_fired     ?? []
  const liveDiffs      = liveEntry?.differential_diagnoses ?? []
  const liveNarrative  = liveEntry?.reasoning_summary ?? null
  const liveConf       = liveEntry?.confidence

  // Derive vital triggers from vitals_snapshot
  const abnormalVitals = liveEntry ? getAbnormalVitals(snap) : []

  // Approximate SHAL layer breakdown
  const synCount  = liveSyndromes.length
  const trendCount = liveTrends.length
  const sl3Est    = Math.min(synCount * 7, 30)
  const sl4Est    = Math.min(trendCount * 5, 15)
  const remaining = Math.max(0, riskScore - sl3Est - sl4Est)
  const scoreBreakdown = [
    { label: 'SL1 Vitals',     pts: +(remaining * 0.50).toFixed(1), color: '#1a6b58' },
    { label: 'SL2 Trajectory', pts: +(remaining * 0.30).toFixed(1), color: '#2a7fa0' },
    { label: 'SL3 Syndromes',  pts: sl3Est,                         color: '#5a4faa' },
    { label: 'SL4 Trends',     pts: sl4Est,                         color: '#c07010' },
    { label: 'SL5 IF/Context', pts: +(remaining * 0.20).toFixed(1), color: '#a8291e' },
  ]

  return (
    <SentinelLayout>
    <div className="min-h-screen font-sans" style={{ background: '#f4ead8' }}>
      {selectedEntry && <XAIDrawer entry={selectedEntry} onClose={() => setSelectedEntry(null)} />}

      {/* ── Nav ──────────────────────────────────────────────────── */}
      <div className="sticky top-0 z-40 flex items-center justify-between px-6 py-3 border-b border-[#ddd0b6]"
        style={{ background: 'rgba(237,224,202,0.94)', backdropFilter: 'blur(12px)' }}>
        <div className="flex items-center gap-3">
          <div className="w-7 h-7 rounded-xl bg-[#1a6b58] flex items-center justify-center shadow-sm">
            <svg className="w-4 h-4 text-white" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 2L12.5 7.5H18L13.5 11L15.5 17L10 13.5L4.5 17L6.5 11L2 7.5H7.5L10 2Z"/>
            </svg>
          </div>
          <span className="font-black text-[#271a0c] tracking-wider text-sm">SENTINEL</span>
          <span className="h-4 w-px bg-[#ddd0b6]"/>
          <span className="text-[10px] font-semibold text-[#a06a20] uppercase tracking-[0.1em]">Clinical Escalation Agent</span>
        </div>
        <div className="flex items-center gap-5 text-xs text-[#9b8768]">
          <span className="font-mono text-[#6b5438]">Patient {liveEntry?.patient_id ?? 'P01'} · Ward 4B</span>
          {liveEntry && (
            <span className="font-mono text-[#9b8768] text-[10px]">
              {new Date(liveEntry.escalated_at).toLocaleTimeString()}
            </span>
          )}
          <span className="flex items-center gap-1.5">
            <span className={cx('w-2 h-2 rounded-full', liveEntry ? 'bg-[#1a6b58] animate-pulse' : 'bg-[#9b8768]')}/>
            {liveEntry ? 'Live' : 'Connecting'}
          </span>
        </div>
      </div>

      <div className="p-5 space-y-4">

        {/* ── Simulator Status ─────────────────────────────────────── */}
        <SimulatorPanel />

        {/* ── Alert Banner ─────────────────────────────────────────── */}
        {liveEntry && (liveEntry.shal_band === 'CRITICAL' || liveEntry.shal_band === 'HIGH' || (liveEntry.fall_event_type && liveEntry.fall_event_type !== 'NONE')) && (
          <div
            className="flex items-center gap-3 px-4 py-3 rounded-2xl border cursor-pointer hover:opacity-90 transition-opacity"
            style={{ background: liveEntry.shal_band === 'CRITICAL' ? '#f9eeec' : liveEntry.fall_event_type && liveEntry.fall_event_type !== 'NONE' ? '#eff7fd' : '#fdf3e7',
                     borderColor: liveEntry.shal_band === 'CRITICAL' ? '#a8291e30' : liveEntry.fall_event_type && liveEntry.fall_event_type !== 'NONE' ? '#2a7fa030' : '#c0701030' }}
            onClick={() => setSelectedEntry(liveEntry)}
          >
            <div className="w-2.5 h-2.5 rounded-full animate-pulse shrink-0"
              style={{ background: liveEntry.shal_band === 'CRITICAL' ? '#a8291e' : liveEntry.fall_event_type && liveEntry.fall_event_type !== 'NONE' ? '#2a7fa0' : '#c07010' }}/>
            <p className="text-sm font-semibold"
              style={{ color: liveEntry.shal_band === 'CRITICAL' ? '#7a1e14' : '#6b4010' }}>
              {liveEntry.fall_event_type && liveEntry.fall_event_type !== 'NONE'
                ? `⚠ FALL EVENT — ${liveEntry.fall_event_type} · Patient ${liveEntry.patient_id} · Score ${liveEntry.final_score.toFixed(1)}`
                : `⚠ ${liveEntry.shal_band} — Patient ${liveEntry.patient_id} · Score ${liveEntry.final_score.toFixed(1)} · ${liveEntry.reasoning_summary?.slice(0, 70) ?? 'Escalation triggered'}`}
            </p>
            {liveEntry.hard_override_active && (
              <span className="px-2 py-0.5 rounded-lg text-[10px] font-bold bg-[#a8291e] text-white shrink-0">OVERRIDE</span>
            )}
            <span className="ml-auto text-xs text-[#9b8768] shrink-0">↗ View details</span>
          </div>
        )}

        {/* ── Hero row ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-3 gap-4">
          <Card glow={riskScore > 70 ? 'red' : 'amber'} className="p-5 flex flex-col items-center">
            <SectionLabel>Risk Index</SectionLabel>
            <RiskOrb score={riskScore}/>
            <div className="mt-4"><RiskBadge band={band} score={riskScore}/></div>
          </Card>

          <Card className="p-5">
            <SectionLabel>Vital Network</SectionLabel>
            <svg viewBox="0 0 220 160" className="w-full">
              {[[110,80,55,40],[110,80,165,40],[110,80,55,120],[110,80,165,120],[110,80,20,80],[110,80,200,80]].map(([x1,y1,x2,y2],i) => (
                <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#a06a2035" strokeWidth="1" strokeDasharray="4 3"/>
              ))}
              <circle cx="110" cy="80" r="20" fill="#1a6b5818" stroke="#1a6b58" strokeWidth="1.5"/>
              <text x="110" y="84" textAnchor="middle" fill="#1a6b58" fontSize="9" fontWeight="bold">AI</text>
              {[
                [55,40,`HR\n${Math.round(hr)}`,hr>100||hr<60?'#a8291e':'#1a6b58'],
                [165,40,`SpO₂\n${spo2.toFixed(0)}`,spo2<95?'#a8291e':'#1a6b58'],
                [55,120,`RR\n${Math.round(rr)}`,rr>20||rr<12?'#a8291e':'#1a6b58'],
                [165,120,`Temp\n${temp.toFixed(1)}`,temp>37.5?'#c07010':'#1a6b58'],
                [20,80,`HRV\n${Math.round(hrv)}`,hrv<20?'#a8291e':'#1a6b58'],
                [200,80,`SHAL\n${riskScore.toFixed(0)}`,riskScore>=60?'#a8291e':riskScore>=35?'#c07010':'#1a6b58'],
              ].map(([cx_,cy_,label,col])=>(
                <g key={String(label)}>
                  <circle cx={cx_ as number} cy={cy_ as number} r="16" fill={`${col}14`} stroke={col as string} strokeWidth="1.5"/>
                  {String(label).split('\n').map((line,li)=>(
                    <text key={li} x={cx_ as number} y={(cy_ as number)-3+li*9} textAnchor="middle" fill="#271a0c" fontSize="6.5" fontWeight="600">{line}</text>
                  ))}
                </g>
              ))}
            </svg>
          </Card>

          <Card className="p-5 flex flex-col gap-3">
            <SectionLabel>Live ECG</SectionLabel>
            <ECGStrip hr={Math.round(hr)}/>
            <div className="grid grid-cols-2 gap-3 mt-auto">
              <div className="text-center p-2 rounded-xl" style={{ background: hr > 100 || hr < 60 ? '#f9eeec' : '#edf7f4' }}>
                <p className="text-[10px] text-[#9b8768]">HR</p>
                <p className="text-2xl font-black" style={{ color: hr > 100 || hr < 60 ? '#a8291e' : '#1a6b58' }}>{Math.round(hr)}</p>
                <p className="text-[10px] text-[#9b8768]">bpm</p>
              </div>
              <div className="text-center p-2 rounded-xl" style={{ background: spo2 < 95 ? '#f9eeec' : '#edf7f4' }}>
                <p className="text-[10px] text-[#9b8768]">SpO₂</p>
                <p className="text-2xl font-black" style={{ color: spo2 < 95 ? '#a8291e' : '#1a6b58' }}>{spo2.toFixed(1)}%</p>
              </div>
            </div>
          </Card>
        </div>

        {/* ── Vital cards — all CSV channels ──────────────────────── */}
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: 'Heart Rate',   value: Math.round(hr),           unit: 'bpm', normal: [60,100]    as [number,number] },
            { label: 'Resp Rate',    value: Math.round(rr),           unit: '/min', normal: [12,20]    as [number,number] },
            { label: 'SpO₂',        value: Math.round(spo2*10)/10,   unit: '%',   normal: [95,100]    as [number,number] },
            { label: 'Temperature', value: Math.round(temp*10)/10,   unit: '°C',  normal: [36,37.5]   as [number,number] },
            { label: 'HRV',         value: Math.round(hrv),          unit: 'ms',  normal: [20,80]     as [number,number] },
          ].map(v=><VitalCard key={v.label} {...v}/>)}
        </div>

        {/* ── Extended CSV vitals + location ───────────────────────── */}
        <div className="grid grid-cols-4 gap-3">

          {/* ECG details */}
          <Card className="p-4">
            <SectionLabel>ECG Details</SectionLabel>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Rhythm</span>
                <span className="text-xs font-bold text-[#271a0c]">{lv?.ecg_rhythm ?? 'NORMAL_SINUS'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">ST Deviation</span>
                <span className={cx('text-xs font-bold font-mono', ecgST != null && Math.abs(ecgST) > 1 ? 'text-[#a8291e]' : 'text-[#1a6b58]')}>
                  {ecgST != null ? `${ecgST > 0 ? '+' : ''}${ecgST.toFixed(2)} mm` : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">QTc</span>
                <span className={cx('text-xs font-bold font-mono', ecgQTc != null && ecgQTc > 450 ? 'text-[#c07010]' : 'text-[#271a0c]')}>
                  {ecgQTc != null ? `${ecgQTc.toFixed(0)} ms` : '—'}
                </span>
              </div>
            </div>
          </Card>

          {/* Sleep metrics */}
          <Card className="p-4">
            <SectionLabel>Sleep Metrics</SectionLabel>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Efficiency</span>
                <span className={cx('text-xs font-bold', sleepEff != null && sleepEff < 75 ? 'text-[#c07010]' : 'text-[#1a6b58]')}>
                  {sleepEff != null ? `${sleepEff.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Deep Sleep</span>
                <span className={cx('text-xs font-bold', deepSleep != null && deepSleep < 15 ? 'text-[#c07010]' : 'text-[#1a6b58]')}>
                  {deepSleep != null ? `${deepSleep.toFixed(1)}%` : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Stress Score</span>
                <span className={cx('text-xs font-bold', stress != null && stress > 70 ? 'text-[#a8291e]' : 'text-[#271a0c]')}>
                  {stress != null ? `${stress.toFixed(0)}/100` : '—'}
                </span>
              </div>
            </div>
          </Card>

          {/* Activity */}
          <Card className="p-4">
            <SectionLabel>Activity</SectionLabel>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Steps/Hour</span>
                <span className="text-xs font-bold text-[#271a0c]">
                  {steps != null ? steps.toFixed(0) : '—'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Activity</span>
                <span className="text-xs font-bold text-[#271a0c]">{lv?.activity_context ?? '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">Signal Quality</span>
                <span className={cx('text-xs font-bold', lv?.signal_quality != null && lv.signal_quality < 50 ? 'text-[#a8291e]' : 'text-[#1a6b58]')}>
                  {lv?.signal_quality != null ? `${lv.signal_quality.toFixed(0)}%` : '—'}
                </span>
              </div>
            </div>
          </Card>

          {/* Patient location (from CSV lat/lng) */}
          <Card className="p-4">
            <SectionLabel>Patient Location</SectionLabel>
            {lv?.latitude != null && lv?.longitude != null ? (
              <div className="space-y-2">
                <div className="flex items-center gap-1.5">
                  <span className={cx('w-2 h-2 rounded-full shrink-0', lv.location_stale ? 'bg-[#c07010]' : 'bg-[#1a6b58] animate-pulse')}/>
                  <span className="text-[10px] text-[#9b8768]">{lv.location_stale ? 'Stale GPS' : 'Live GPS'}</span>
                </div>
                <div className="font-mono text-[10px] text-[#271a0c] bg-[#f0e6d0] rounded-lg px-2 py-1.5 border border-[#ddd0b6] leading-relaxed">
                  {lv.latitude.toFixed(6)}<br/>{lv.longitude.toFixed(6)}
                </div>
                <a
                  href={`https://maps.google.com/?q=${lv.latitude.toFixed(6)},${lv.longitude.toFixed(6)}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1.5 text-[10px] font-semibold text-[#2a7fa0] hover:underline"
                >
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
                  </svg>
                  Open in Google Maps ↗
                </a>
                <div className="text-[10px] text-[#9b8768]">
                  Patient {lv.gender ?? '?'} · Age {lv.age ?? '?'} · {lv.weight_kg != null ? `${lv.weight_kg}kg` : '?'}
                  {lv.has_chronic_condition && <span className="ml-1 text-[#c07010] font-semibold">· Chronic</span>}
                </div>
              </div>
            ) : (
              <p className="text-[10px] text-[#9b8768] italic">No GPS data — waiting for simulator reading…</p>
            )}
          </Card>
        </div>

        {/* ── XAI Panel ────────────────────────────────────────────── */}
        <div>
          <div className="flex items-center gap-3 mb-3">
            <h2 className="text-sm font-black text-[#271a0c] tracking-tight">Explainable AI — Why This Alert?</h2>
            <RiskBadge band={band} score={riskScore}/>
            {!liveEntry && <span className="text-[10px] text-[#9b8768] italic">Awaiting backend data…</span>}
          </div>
          <div className="grid grid-cols-2 gap-3">

            {/* Score breakdown */}
            <Card className="p-4">
              <SectionLabel>Score Breakdown</SectionLabel>
              <div className="space-y-2">
                {scoreBreakdown.map(l=>(
                  <div key={l.label} className="flex items-center gap-2">
                    <span className="text-[10px] text-[#6b5438] w-28 shrink-0">{l.label}</span>
                    <div className="flex-1 h-2 rounded-full bg-[#e5d9c3] overflow-hidden">
                      <div className="h-full rounded-full transition-all duration-1000" style={{ width:`${riskScore > 0 ? Math.min(l.pts/riskScore*100,100) : 0}%`, background:l.color }}/>
                    </div>
                    <span className="text-[10px] font-mono font-bold w-8 text-right" style={{color:l.color}}>{l.pts}</span>
                  </div>
                ))}
              </div>
              <div className="mt-3 pt-3 border-t border-[#ebe1ce] flex items-center justify-between">
                <span className="text-[10px] text-[#9b8768]">SHAL Total</span>
                <span className="text-xl font-black text-[#271a0c]">{riskScore.toFixed(1)}</span>
              </div>
            </Card>

            {/* Vital triggers */}
            <Card className="p-4">
              <SectionLabel>Vital Triggers</SectionLabel>
              {abnormalVitals.length === 0 ? (
                <div className="space-y-2">
                  {[
                    { name: 'Heart Rate',        normal: hr >= 60 && hr <= 100 },
                    { name: 'SpO₂',              normal: spo2 >= 95 },
                    { name: 'Respiratory Rate',  normal: rr >= 12 && rr <= 20 },
                    { name: 'Temperature',       normal: temp >= 36 && temp <= 37.5 },
                    { name: 'HRV',               normal: hrv >= 20 },
                  ].map(v => (
                    <div key={v.name} className="flex items-center gap-2">
                      <span className="text-xs text-[#6b5438] flex-1">{v.name}</span>
                      <span className="text-[10px] font-bold" style={{ color: v.normal ? '#1a6b58' : '#a8291e' }}>
                        {v.normal ? '✓ Normal' : '✗ Abnormal'}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2.5">
                  {abnormalVitals.map(v => (
                    <div key={v.key} className="flex items-center gap-2">
                      <span className="text-xs text-[#6b5438] flex-1">{v.label}</span>
                      <div className="w-20 h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden">
                        <div className="h-full rounded-full" style={{
                          width: `${Math.min(Math.abs(v.value - (v.direction === 'HIGH' ? v.high : v.low)) / (v.high - v.low) * 100 + 40, 100)}%`,
                          background: '#a8291e'
                        }}/>
                      </div>
                      <span className="text-[10px] font-mono font-bold text-[#a8291e] w-16 text-right">
                        {v.value.toFixed(1)}{v.unit}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Syndromes */}
            <Card className="p-4">
              <SectionLabel>Clinical Syndromes Fired</SectionLabel>
              {liveSyndromes.length === 0 ? (
                <p className="text-[10px] text-[#9b8768] italic">No syndromes matched in current assessment cycle</p>
              ) : (
                <div className="flex flex-wrap gap-2">
                  {liveSyndromes.map(s=>(
                    <span key={s} className="px-2.5 py-1.5 rounded-xl text-[10px] font-semibold bg-[#f9eeec] text-[#7a1e14] border border-[#a8291e25]">{s}</span>
                  ))}
                </div>
              )}
            </Card>

            {/* Trends */}
            <Card className="p-4">
              <SectionLabel>Deterioration Trends</SectionLabel>
              {liveTrends.length === 0 ? (
                <p className="text-[10px] text-[#9b8768] italic">No multi-window deterioration trends detected</p>
              ) : (
                <div className="space-y-2">
                  {liveTrends.map(t=>(
                    <div key={t} className="flex items-center gap-2 text-xs px-3 py-2 rounded-xl bg-[#fdf3e7] border border-[#c0701030]">
                      <span className="text-[#c07010] font-bold">↗</span>
                      <span className="text-[#6b5438]">{t}</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Differentials */}
            <Card className="p-4">
              <SectionLabel>
                AI Differentials{liveConf != null && (
                  <span className="normal-case font-normal text-[#1a6b58] ml-1">{Math.round(liveConf * 100)}% conf.</span>
                )}
              </SectionLabel>
              {liveDiffs.length === 0 ? (
                <p className="text-[10px] text-[#9b8768] italic">Differential diagnoses only generated for HIGH/CRITICAL bands</p>
              ) : (
                <div className="space-y-2">
                  {liveDiffs.map((d,i)=>(
                    <div key={i} className="flex items-center gap-2">
                      <span className="flex-1 text-[10px] text-[#271a0c] truncate">{d.dx}</span>
                      <div className="w-20 h-1.5 rounded-full bg-[#e5d9c3] overflow-hidden">
                        <div className="h-full rounded-full bg-[#1a6b58]" style={{width:`${d.probability*100}%`, transition:'width 0.9s ease'}}/>
                      </div>
                      <span className="text-[10px] font-mono font-bold text-[#1a6b58] w-8 text-right">{Math.round(d.probability*100)}%</span>
                    </div>
                  ))}
                </div>
              )}
            </Card>

            {/* Clinical narrative */}
            <Card className="p-4 col-span-1">
              <SectionLabel>Clinical Narrative</SectionLabel>
              <div className="rounded-xl bg-[#f0e6d0] border border-[#ddd0b6] p-3 min-h-[80px]">
                {liveNarrative ? (
                  <p className="text-xs text-[#271a0c] leading-relaxed font-mono">
                    {liveNarrative}
                    <span className="inline-block w-0.5 h-3.5 bg-[#1a6b58] ml-0.5 align-middle animate-pulse"/>
                  </p>
                ) : (
                  <p className="text-[10px] text-[#9b8768] italic">
                    Narrative generated by LLM for HIGH/CRITICAL escalations only. Monitoring for threshold breach…
                  </p>
                )}
              </div>
            </Card>

          </div>
        </div>

        {/* ── Decision Log ─────────────────────────────────────────── */}
        <Card className="p-5">
          <div className="flex items-center justify-between mb-4">
            <SectionLabel>Decision Log — Live</SectionLabel>
            <span className="text-[10px] text-[#a06a20] font-semibold">↗ Click any row for full XAI explanation</span>
          </div>
          <DecisionLog entries={recentEntries} onSelect={setSelectedEntry}/>
        </Card>

      </div>
    </div>
    </SentinelLayout>
  )
}
