import { useState, useEffect } from 'react'
import { fetchAuditLog, type AuditEntry } from '../../../lib/sentinelApi'
import { SentinelLayout } from './_SentinelNav'

function cx(...classes: (string | false | undefined | null)[]) {
  return classes.filter(Boolean).join(' ')
}

function Card({ children, className = '', onClick }: { children: React.ReactNode; className?: string; onClick?: () => void }) {
  return (
    <div className={cx('rounded-2xl border border-[#e4d8c4] bg-[#fdf8f0] shadow-sm', className)} onClick={onClick}>
      {children}
    </div>
  )
}

const bandStyles: Record<string, string> = {
  CRITICAL: 'bg-[#b83025] text-white',
  HIGH:     'bg-[#c97f10] text-white',
  WARNING:  'bg-[#e4d8c4] text-[#6b5840]',
  NOMINAL:  'bg-[#d0ebe4] text-[#196f5a]',
  FALL:     'bg-[#2a7fa0] text-white',
}

function actionBadges(e: AuditEntry) {
  const acts: string[] = []
  if (e.ems_dispatched)     acts.push('EMS')
  if (e.sms_sent)           acts.push('SMS')
  if (e.email_sent)         acts.push('EMAIL')
  if (e.fcm_sent)           acts.push('FCM')
  if (e.appointment_booked) acts.push('APPT')
  return acts
}

function succeeded(e: AuditEntry) {
  return e.ems_dispatched || e.sms_sent || e.email_sent || e.fcm_sent || e.appointment_booked || e.shal_band === 'NOMINAL' || e.shal_band === 'WARNING'
}

// Vitals to display in expanded view
const VITAL_LABELS: Record<string, { label: string; unit: string; low: number; high: number }> = {
  heart_rate:          { label: 'Heart Rate',       unit: 'bpm',  low: 60,   high: 100  },
  spo2:                { label: 'SpO₂',             unit: '%',    low: 95,   high: 100  },
  respiratory_rate:    { label: 'Resp. Rate',       unit: '/min', low: 12,   high: 20   },
  body_temperature:    { label: 'Temperature',      unit: '°C',   low: 36,   high: 37.5 },
  hrv_ms:              { label: 'HRV',              unit: 'ms',   low: 20,   high: 80   },
  ecg_st_deviation_mm: { label: 'ECG ST Dev.',      unit: 'mm',   low: -0.5, high: 0.5  },
  ecg_qtc_ms:          { label: 'QTc',              unit: 'ms',   low: 380,  high: 440  },
  stress_score:        { label: 'Stress',           unit: '',     low: 0,    high: 50   },
  sleep_efficiency:    { label: 'Sleep Eff.',       unit: '%',    low: 75,   high: 100  },
}

export function AuditTrail() {
  const [search, setSearch]   = useState('')
  const [filter, setFilter]   = useState('ALL')
  const [expanded, setExpanded] = useState<number | null>(null)
  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [live, setLive]       = useState(false)

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const res = await fetchAuditLog(100)
        if (!cancelled) {
          setEntries(res.entries)
          setLive(true)
        }
      } catch {
        // backend not reachable — keep empty / previous data
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    const id = setInterval(load, 8000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  // Compute effective path for display / filter
  function entryPath(e: AuditEntry) {
    if (e.fall_event_type && e.fall_event_type !== 'NONE') return 'FALL'
    return e.shal_band
  }

  const filtered = entries.filter(e => {
    const path = entryPath(e)
    return (filter === 'ALL' || path === filter) &&
      (e.patient_id.toLowerCase().includes(search.toLowerCase()) ||
       path.toLowerCase().includes(search.toLowerCase()) ||
       (e.reasoning_summary ?? '').toLowerCase().includes(search.toLowerCase()))
  })

  const stats = {
    total:    entries.length,
    critical: entries.filter(e => e.shal_band === 'CRITICAL').length,
    high:     entries.filter(e => e.shal_band === 'HIGH').length,
    success:  entries.length > 0 ? Math.round(entries.filter(succeeded).length / entries.length * 100) : 0,
  }

  return (
    <SentinelLayout>
    <div className="min-h-screen font-sans p-6 space-y-5" style={{ background: '#f5ede0' }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-[#2c2016] tracking-tight">Audit Trail</h1>
          <p className="text-xs text-[#9d8a72] mt-0.5">Immutable escalation log — all pipeline decisions recorded</p>
        </div>
        <div className="flex items-center gap-2">
          {loading && <span className="w-2 h-2 rounded-full bg-[#c97f10] animate-pulse" />}
          {!loading && live && <span className="w-2 h-2 rounded-full bg-[#196f5a] animate-pulse" />}
          <span className="px-3 py-1 rounded-xl text-xs font-semibold bg-[#196f5a1a] text-[#196f5a] border border-[#196f5a30]">
            {loading ? 'Loading…' : `${filtered.length} entries${live ? ' · Live' : ''}`}
          </span>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Total Events',  value: stats.total,              color: '#196f5a' },
          { label: 'Critical Esc.', value: stats.critical,           color: '#b83025' },
          { label: 'High Esc.',     value: stats.high,               color: '#c97f10' },
          { label: 'Actions Fired', value: `${stats.success}%`,      color: '#196f5a' },
        ].map(s => (
          <Card key={s.label} className="p-4 text-center">
            <div className="text-2xl font-black" style={{ color: s.color }}>{s.value}</div>
            <div className="text-[10px] text-[#9d8a72] uppercase tracking-widest mt-1">{s.label}</div>
          </Card>
        ))}
      </div>

      {/* Filters */}
      <Card className="p-4 flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-[#9d8a72]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
          </svg>
          <input
            className="w-full pl-9 pr-4 py-2 rounded-xl bg-[#f5ede0] border border-[#e4d8c4] text-sm text-[#2c2016] placeholder:text-[#9d8a72] focus:outline-none focus:border-[#196f5a80]"
            placeholder="Search patient ID, band, or narrative…"
            value={search}
            onChange={e => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-2 flex-wrap">
          {['ALL', 'CRITICAL', 'HIGH', 'WARNING', 'NOMINAL', 'FALL'].map(f => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={cx(
                'px-3 py-1.5 rounded-xl text-xs font-semibold transition-all',
                filter === f
                  ? 'bg-[#196f5a] text-white shadow-sm'
                  : 'bg-[#f5ede0] text-[#6b5840] border border-[#e4d8c4] hover:bg-[#ede3d0]'
              )}
            >
              {f}
            </button>
          ))}
        </div>
      </Card>

      {/* No entries placeholder */}
      {!loading && filtered.length === 0 && (
        <Card className="p-10 text-center">
          <p className="text-sm text-[#9d8a72]">
            {entries.length === 0
              ? 'No audit entries yet. Backend simulation running — entries appear when SHAL score triggers escalation.'
              : 'No entries match the current filter.'}
          </p>
        </Card>
      )}

      {/* Entries */}
      <div className="space-y-2">
        {filtered.map(entry => {
          const path    = entryPath(entry)
          const acts    = actionBadges(entry)
          const ok      = succeeded(entry)
          const isOpen  = expanded === entry.id

          return (
            <Card
              key={entry.id}
              className="overflow-hidden cursor-pointer hover:border-[#196f5a50] transition-colors"
              onClick={() => setExpanded(isOpen ? null : entry.id)}
            >
              {/* Row */}
              <div className="p-4 flex items-center gap-4">
                {ok
                  ? <svg className="w-5 h-5 text-[#196f5a] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                  : <svg className="w-5 h-5 text-[#b83025] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><line x1="12" x2="12" y1="9" y2="13" /><line x1="12" x2="12.01" y1="17" y2="17" /></svg>
                }
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-[#2c2016]">{entry.patient_id}</span>
                    <span className={cx('px-2 py-0.5 rounded-lg text-[10px] font-bold', bandStyles[path] ?? bandStyles.NOMINAL)}>
                      {path}
                    </span>
                    <span className="text-xs text-[#196f5a] font-mono font-bold">
                      {entry.final_score.toFixed(1)} pts
                    </span>
                    {entry.hard_override_active && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-[#b83025] text-white">OVERRIDE</span>
                    )}
                    {acts.map(a => (
                      <span key={a} className="px-1.5 py-0.5 rounded text-[10px] bg-[#f5ede0] text-[#6b5840] border border-[#e4d8c4]">{a}</span>
                    ))}
                    {acts.length === 0 && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] bg-[#f5ede0] text-[#9d8a72] border border-[#e4d8c4]">LOG</span>
                    )}
                  </div>
                  {entry.reasoning_summary && (
                    <p className="text-[10px] text-[#9d8a72] mt-0.5 truncate">{entry.reasoning_summary.slice(0, 100)}</p>
                  )}
                </div>
                <div className="flex items-center gap-1.5 text-xs text-[#9d8a72] shrink-0">
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
                  {new Date(entry.escalated_at).toLocaleTimeString()}
                </div>
                <svg
                  className={cx('w-4 h-4 text-[#9d8a72] transition-transform shrink-0', isOpen && 'rotate-180')}
                  viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
                >
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </div>

              {/* Expanded detail */}
              {isOpen && (
                <div className="border-t border-[#e4d8c4] bg-[#f5ede0] p-5 space-y-4">

                  {/* Meta row */}
                  <div className="flex flex-wrap gap-4 text-[10px] text-[#9d8a72]">
                    <span>Patient: <span className="text-[#2c2016] font-semibold">{entry.patient_id}</span></span>
                    <span>Session: <span className="font-mono text-[#6b5840]">{entry.session_id}</span></span>
                    <span>Reading: <span className="font-mono text-[#6b5840]">{entry.reading_id}</span></span>
                    <span>Band: <span className="font-semibold" style={{ color: entry.shal_band === 'CRITICAL' ? '#b83025' : entry.shal_band === 'HIGH' ? '#c97f10' : '#196f5a' }}>{entry.shal_band}</span></span>
                    <span>Decision: <span className="font-semibold text-[#196f5a]">{entry.decision_source}</span></span>
                    {entry.confidence != null && (
                      <span>Confidence: <span className="font-semibold text-[#196f5a]">{Math.round(entry.confidence * 100)}%</span></span>
                    )}
                    {entry.actions_latency_ms != null && (
                      <span>Latency: <span className="font-mono text-[#6b5840]">{entry.actions_latency_ms}ms</span></span>
                    )}
                  </div>

                  {/* Clinical narrative */}
                  {entry.reasoning_summary && (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Clinical Narrative</p>
                      <div className="rounded-xl bg-[#fdf8f0] border border-[#e4d8c4] p-3">
                        <p className="text-xs text-[#2c2016] leading-relaxed font-mono">{entry.reasoning_summary}</p>
                      </div>
                    </div>
                  )}

                  {/* LLM thinking chain */}
                  {entry.llm_thinking_chain && (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">AI Reasoning Chain</p>
                      <div className="rounded-xl bg-[#fdf8f0] border border-[#e4d8c4] p-3 max-h-40 overflow-y-auto">
                        <pre className="text-[10px] text-[#6b5840] leading-relaxed whitespace-pre-wrap font-mono">{entry.llm_thinking_chain}</pre>
                      </div>
                    </div>
                  )}

                  {/* Vitals snapshot */}
                  {Object.keys(entry.vitals_snapshot ?? {}).length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Vitals Snapshot</p>
                      <div className="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-5 gap-2">
                        {Object.entries(entry.vitals_snapshot).map(([key, val]) => {
                          if (val == null) return null
                          const def = VITAL_LABELS[key]
                          if (!def) return null
                          const numVal = typeof val === 'number' ? val : parseFloat(String(val))
                          const abnormal = numVal < def.low || numVal > def.high
                          return (
                            <div key={key} className={cx(
                              'rounded-xl border p-2 text-center',
                              abnormal ? 'bg-[#f9eeec] border-[#b8302540]' : 'bg-[#fdf8f0] border-[#e4d8c4]'
                            )}>
                              <p className="text-[9px] text-[#9d8a72] mb-0.5">{def.label}</p>
                              <p className={cx('text-sm font-black', abnormal ? 'text-[#b83025]' : 'text-[#2c2016]')}>
                                {numVal.toFixed(1)}
                              </p>
                              <p className="text-[9px] text-[#9d8a72]">{def.unit}</p>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}

                  {/* Syndromes + Trends */}
                  {((entry.syndromes_fired?.length ?? 0) > 0 || (entry.trends_fired?.length ?? 0) > 0) && (
                    <div className="grid grid-cols-2 gap-4">
                      {(entry.syndromes_fired?.length ?? 0) > 0 && (
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Syndromes Fired</p>
                          <div className="flex flex-wrap gap-1.5">
                            {entry.syndromes_fired!.map(s => (
                              <span key={s} className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-[#f9eeec] text-[#7a1e14] border border-[#b8302520]">{s}</span>
                            ))}
                          </div>
                        </div>
                      )}
                      {(entry.trends_fired?.length ?? 0) > 0 && (
                        <div>
                          <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Trends Detected</p>
                          <div className="flex flex-wrap gap-1.5">
                            {entry.trends_fired!.map(t => (
                              <span key={t} className="px-2 py-1 rounded-lg text-[10px] font-semibold bg-[#fdf3e7] text-[#7a4010] border border-[#c9701020]">{t}</span>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Differential diagnoses */}
                  {entry.differential_diagnoses && entry.differential_diagnoses.length > 0 && (
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Differential Diagnoses</p>
                      <div className="space-y-2">
                        {entry.differential_diagnoses.map((d, i) => (
                          <div key={i} className="rounded-xl border border-[#e4d8c4] bg-[#fdf8f0] p-3">
                            <div className="flex items-center gap-2 mb-1">
                              <span className="text-xs font-semibold text-[#2c2016] flex-1">{d.dx}</span>
                              <div className="w-20 h-1.5 rounded-full bg-[#e4d8c4] overflow-hidden">
                                <div className="h-full rounded-full bg-[#196f5a]" style={{ width: `${d.probability * 100}%` }} />
                              </div>
                              <span className="text-[10px] font-mono font-bold text-[#196f5a] w-8 text-right">
                                {Math.round(d.probability * 100)}%
                              </span>
                            </div>
                            <p className="text-[10px] text-[#9d8a72] leading-relaxed">{d.evidence}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* Actions taken */}
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-widest text-[#9d8a72] mb-2">Actions Taken</p>
                    <div className="flex flex-wrap gap-2">
                      {entry.ems_dispatched && (
                        <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#b83025] text-white">
                          EMS{entry.ems_response_code ? ` · HTTP ${entry.ems_response_code}` : ''}
                        </span>
                      )}
                      {entry.sms_sent && <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#c97f10] text-white">SMS</span>}
                      {entry.email_sent && <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#196f5a] text-white">EMAIL</span>}
                      {entry.fcm_sent && <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#2a7fa0] text-white">FCM PUSH</span>}
                      {entry.appointment_booked && (
                        <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#196f5a] text-white">
                          APPOINTMENT{entry.appointment_id ? ` · ${entry.appointment_id}` : ''}
                        </span>
                      )}
                      {!entry.ems_dispatched && !entry.sms_sent && !entry.email_sent && !entry.fcm_sent && !entry.appointment_booked && (
                        <span className="px-2.5 py-1 rounded-xl text-[10px] font-semibold bg-[#e4d8c4] text-[#6b5840]">Internal Log Only</span>
                      )}
                    </div>
                  </div>

                  {/* Hard override info */}
                  {entry.hard_override_active && (
                    <div className="rounded-xl border border-[#b8302540] bg-[#f9eeec] p-3">
                      <p className="text-[10px] font-bold text-[#b83025] uppercase tracking-widest mb-1">Hard Override Active</p>
                      <p className="text-xs text-[#7a1e14]">
                        Override type: <span className="font-semibold">{entry.hard_override_type ?? 'Unknown'}</span> — Clinical rule forced CRITICAL regardless of composite score.
                      </p>
                    </div>
                  )}

                  {/* Fall event */}
                  {entry.fall_event_type && entry.fall_event_type !== 'NONE' && (
                    <div className="rounded-xl border border-[#2a7fa040] bg-[#eff7fd] p-3">
                      <p className="text-[10px] font-bold text-[#2a7fa0] uppercase tracking-widest mb-1">Fall Event</p>
                      <p className="text-xs text-[#1a5068]">
                        Detected: <span className="font-semibold">{entry.fall_event_type}</span> — Fall protocol automatically triggered.
                      </p>
                    </div>
                  )}

                </div>
              )}
            </Card>
          )
        })}
      </div>
    </div>
    </SentinelLayout>
  )
}
