import { useState, useEffect } from 'react'
import { fetchHealth, fetchAuditLog, fetchSimulatorStatus, type AuditEntry, type HealthResponse } from '../../../lib/sentinelApi'
import { SentinelLayout } from './_SentinelNav'

function cx(...classes: (string | false | undefined | null)[]) {
  return classes.filter(Boolean).join(' ')
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx('rounded-2xl border border-[#e4d8c4] bg-[#fdf8f0] shadow-sm', className)}>
      {children}
    </div>
  )
}

type ServiceStatus = 'connected' | 'loaded' | 'configured' | 'mock' | 'error' | 'ok'

interface Service {
  key: string
  label: string
  status: ServiceStatus
  latency?: number
  icon: React.ReactNode
  details: string
}

function statusColor(s: ServiceStatus) {
  if (s === 'connected' || s === 'loaded' || s === 'configured' || s === 'ok') return '#196f5a'
  if (s === 'mock') return '#c97f10'
  return '#b83025'
}

function statusLabel(s: ServiceStatus) {
  const map: Record<string, string> = { connected: 'Connected', loaded: 'Loaded', configured: 'Configured', ok: 'OK', mock: 'Mock Mode', error: 'Error' }
  return map[s] ?? s
}

function IconWifi() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M5 12.55a11 11 0 0 1 14.08 0" /><path d="M1.42 9a16 16 0 0 1 21.16 0" /><path d="M8.53 16.11a6 6 0 0 1 6.95 0" /><circle cx="12" cy="20" r="1" fill="currentColor" /></svg> }
function IconCpu() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="4" y="4" width="16" height="16" rx="2" /><rect x="8" y="8" width="8" height="8" /><path d="M9 1v3M15 1v3M9 20v3M15 20v3M1 9h3M1 15h3M20 9h3M20 15h3" /></svg> }
function IconDb() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /></svg> }
function IconBell() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.73 21a2 2 0 0 1-3.46 0" /></svg> }
function IconAlert() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" /><line x1="12" x2="12" y1="9" y2="13" /><line x1="12" x2="12.01" y1="17" y2="17" /></svg> }
function IconCal() { return <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="4" width="18" height="18" rx="2" ry="2" /><line x1="16" x2="16" y1="2" y2="6" /><line x1="8" x2="8" y1="2" y2="6" /><line x1="3" x2="21" y1="10" y2="10" /></svg> }

const SERVICES: Service[] = [
  { key: 'redis', label: 'Redis Cache', status: 'connected', latency: 0.8, icon: <IconWifi />, details: 'In-memory cache for real-time vital buffers and session state' },
  { key: 'isolation_forest', label: 'Isolation Forest ML', status: 'loaded', latency: 4.2, icon: <IconCpu />, details: 'Anomaly detection model for unsupervised vital pattern analysis' },
  { key: 'claude_api', label: 'Claude AI (Anthropic)', status: 'configured', latency: 820, icon: <IconCpu />, details: 'Primary LLM for clinical narrative generation and reasoning chains' },
  { key: 'gemini_api', label: 'Gemini AI (Google)', status: 'configured', latency: 650, icon: <IconCpu />, details: 'Secondary LLM with multimodal capabilities for ECG analysis' },
  { key: 'database', label: 'PostgreSQL Database', status: 'configured', latency: 12, icon: <IconDb />, details: 'Primary persistent store for patient records and audit trail' },
  { key: 'twilio', label: 'Twilio SMS/Voice', status: 'configured', latency: 180, icon: <IconBell />, details: 'SMS and voice calls for critical escalation notifications' },
  { key: 'sendgrid', label: 'SendGrid Email', status: 'configured', latency: 220, icon: <IconBell />, details: 'Email notifications to on-call physicians and ward staff' },
  { key: 'cal_com', label: 'Cal.com Scheduling', status: 'configured', latency: 310, icon: <IconCal />, details: 'Automated appointment scheduling for physician follow-ups' },
  { key: 'ems', label: 'EMS Integration', status: 'mock', icon: <IconAlert />, details: 'Emergency Medical Services API — running in mock/simulation mode' },
]

function MetricGauge({ label, value, unit, color }: { label: string; value: number; unit: string; color: string }) {
  const circumference = 2 * Math.PI * 28
  return (
    <div className="flex flex-col items-center gap-1">
      <svg width="80" height="80" viewBox="0 0 80 80">
        <circle cx="40" cy="40" r="28" fill="none" stroke="#e4d8c4" strokeWidth="6" />
        <circle
          cx="40" cy="40" r="28"
          fill="none"
          stroke={color}
          strokeWidth="6"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - Math.min(value, 100) / 100)}
          strokeLinecap="round"
          transform="rotate(-90 40 40)"
        />
        <text x="40" y="44" textAnchor="middle" fill="#2c2016" fontSize="13" fontWeight="700">{value}{unit}</text>
      </svg>
      <span className="text-[10px] text-[#9d8a72] text-center">{label}</span>
    </div>
  )
}

export function SystemHealth() {
  const [loading, setLoading]           = useState(false)
  const [lastRefresh, setLastRefresh]   = useState(new Date())
  const [uptimeSeconds, setUptimeSeconds] = useState(0)
  const [services, setServices]         = useState<Service[]>(SERVICES)
  const [recentAudit, setRecentAudit]   = useState<AuditEntry[]>([])
  const [simRunning, setSimRunning]     = useState<boolean | null>(null)
  const [simTicks, setSimTicks]         = useState<number>(0)

  // Uptime ticker
  useEffect(() => { const id = setInterval(() => setUptimeSeconds(u => u + 1), 1000); return () => clearInterval(id) }, [])

  function applyHealth(h: HealthResponse) {
    setServices(prev => prev.map(s => {
      if (s.key === 'redis')            return { ...s, status: h.redis === 'connected' ? 'connected' : 'error' as ServiceStatus }
      if (s.key === 'database')         return { ...s, status: h.database === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'isolation_forest') return { ...s, status: h.isolation_forest === 'loaded' ? 'loaded' : 'error' as ServiceStatus }
      if (s.key === 'claude_api')       return { ...s, status: h.claude_api === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'gemini_api')       return { ...s, status: h.gemini_api === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'twilio')           return { ...s, status: h.twilio === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'sendgrid')         return { ...s, status: h.sendgrid === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'cal_com')          return { ...s, status: h.cal_com === 'configured' ? 'configured' : 'error' as ServiceStatus }
      if (s.key === 'ems')              return { ...s, status: (h.ems === 'mock' ? 'mock' : h.ems === 'configured' ? 'configured' : 'error') as ServiceStatus }
      return s
    }))
    setLastRefresh(new Date())
  }

  // Poll health + audit + simulator
  useEffect(() => {
    let cancelled = false
    async function poll() {
      try {
        const [h, audit, sim] = await Promise.allSettled([
          fetchHealth(),
          fetchAuditLog(5),
          fetchSimulatorStatus('P01'),
        ])
        if (cancelled) return
        if (h.status === 'fulfilled')     applyHealth(h.value)
        if (audit.status === 'fulfilled') setRecentAudit(audit.value.entries)
        if (sim.status === 'fulfilled')   { setSimRunning(sim.value.is_running); setSimTicks(sim.value.ticks_sent) }
        else                              setSimRunning(false)
      } catch { /* backend not reachable */ }
    }
    poll()
    const id = setInterval(poll, 10000)
    return () => { cancelled = true; clearInterval(id) }
  }, [])

  const refresh = () => {
    setLoading(true)
    Promise.allSettled([fetchHealth(), fetchAuditLog(5), fetchSimulatorStatus('P01')])
      .then(([h, audit, sim]) => {
        if (h.status === 'fulfilled')     applyHealth(h.value)
        if (audit.status === 'fulfilled') setRecentAudit(audit.value.entries)
        if (sim.status === 'fulfilled')   { setSimRunning(sim.value.is_running); setSimTicks(sim.value.ticks_sent) }
        setLastRefresh(new Date())
      })
      .finally(() => setLoading(false))
  }

  const fmt = (s: number) => {
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
    return `${h}h ${m}m ${sec}s`
  }

  const healthy = services.filter(s => s.status !== 'error').length

  // Build recent events from live audit entries
  function auditEventType(e: AuditEntry) {
    if (e.shal_band === 'CRITICAL') return { type: 'ESCALATION', color: '#b83025' }
    if (e.shal_band === 'HIGH')     return { type: 'HIGH-ALERT', color: '#c97f10' }
    if (e.fall_event_type && e.fall_event_type !== 'NONE') return { type: 'FALL', color: '#2a7fa0' }
    if (e.decision_source === 'isolation_forest') return { type: 'ML', color: '#196f5a' }
    return { type: 'CYCLE', color: '#196f5a' }
  }

  function auditEventMsg(e: AuditEntry) {
    const acts: string[] = []
    if (e.ems_dispatched)     acts.push('EMS dispatched')
    if (e.sms_sent)           acts.push('SMS sent')
    if (e.email_sent)         acts.push('email sent')
    if (e.appointment_booked) acts.push('appointment booked')
    const actionStr = acts.length > 0 ? ` — ${acts.join(', ')}` : ''
    if (e.reasoning_summary) return `${e.reasoning_summary.slice(0, 80)}${actionStr}`
    return `Patient ${e.patient_id} · Score ${e.final_score.toFixed(1)} · Band ${e.shal_band}${actionStr}`
  }

  return (
    <SentinelLayout>
    <div className="min-h-screen font-sans p-6 space-y-5" style={{ background: '#f5ede0' }}>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-black text-[#2c2016] tracking-tight">System Health</h1>
          <p className="text-xs text-[#9d8a72] mt-0.5">Last checked: {lastRefresh.toLocaleTimeString()}</p>
        </div>
        <button
          onClick={refresh}
          className="flex items-center gap-2 px-4 py-2 rounded-xl bg-[#196f5a1a] text-[#196f5a] text-xs font-semibold border border-[#196f5a30] hover:bg-[#196f5a28] transition-colors"
        >
          <svg className={cx('w-4 h-4', loading && 'animate-spin')} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8" />
            <path d="M21 3v5h-5" />
            <path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16" />
            <path d="M8 16H3v5" />
          </svg>
          Refresh
        </button>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-4 gap-3">
        {[
          { label: 'Services Online',   value: `${healthy}/${services.length}`, color: '#196f5a',   mono: false },
          { label: 'Audit Entries',     value: recentAudit.length > 0 ? '100+' : '0',           color: '#196f5a',   mono: false },
          { label: 'Current Session',   value: fmt(uptimeSeconds),                               color: '#2c2016',   mono: true  },
          { label: 'Readings Sent',     value: simRunning === null ? '—' : String(simTicks),     color: simRunning ? '#196f5a' : '#9d8a72', mono: false },
        ].map(s => (
          <Card key={s.label} className="p-4 text-center">
            <div className={cx('text-2xl font-black', s.mono && 'font-mono text-base leading-tight mt-1')} style={{ color: s.color }}>{s.value}</div>
            <div className="text-[10px] text-[#9d8a72] uppercase tracking-widest mt-1">{s.label}</div>
          </Card>
        ))}
      </div>

      {/* Simulator status banner */}
      <Card className="p-4">
        <div className="flex items-center gap-3">
          <span className={cx('w-2.5 h-2.5 rounded-full shrink-0', simRunning ? 'bg-[#196f5a] animate-pulse' : 'bg-[#9d8a72]')} />
          <span className="text-xs font-semibold text-[#2c2016]">
            {simRunning === null ? 'Connecting to backend…' : simRunning ? `Simulation active — ${simTicks} readings sent` : 'Simulation stopped'}
          </span>
          <span className="ml-auto text-[10px] text-[#9d8a72] font-mono">patient=P01 · dataset.csv</span>
        </div>
      </Card>

      {/* Gauges */}
      <Card className="p-5">
        <p className="text-[10px] font-semibold uppercase tracking-widest text-[#9d8a72] mb-4">System Performance</p>
        <div className="flex items-center justify-around">
          <MetricGauge label="CPU Usage" value={34} unit="%" color="#196f5a" />
          <MetricGauge label="Memory" value={58} unit="%" color="#2a7fa0" />
          <MetricGauge label="API Response" value={72} unit="ms" color="#196f5a" />
          <MetricGauge label="DB Pool" value={23} unit="%" color="#196f5a" />
          <MetricGauge label="Cache Hit" value={94} unit="%" color="#196f5a" />
        </div>
      </Card>

      {/* Services */}
      <div className="grid grid-cols-3 gap-3">
        {services.map(svc => {
          const col = statusColor(svc.status)
          return (
            <Card key={svc.key} className="p-4">
              <div className="flex items-start gap-3">
                <div
                  className="flex-shrink-0 w-10 h-10 rounded-xl flex items-center justify-center"
                  style={{ background: `${col}18`, color: col }}
                >
                  {svc.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <span className="text-sm font-semibold text-[#2c2016] block truncate mb-1">{svc.label}</span>
                  <div className="flex items-center gap-2 mb-2">
                    <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: col }} />
                    <span className="text-[10px] font-semibold" style={{ color: col }}>{statusLabel(svc.status)}</span>
                    {svc.latency !== undefined && (
                      <span className="text-[10px] text-[#9d8a72] font-mono ml-auto">{svc.latency}ms</span>
                    )}
                  </div>
                  <p className="text-[10px] text-[#9d8a72] leading-relaxed">{svc.details}</p>
                </div>
              </div>
            </Card>
          )
        })}
      </div>

      {/* Recent Events — live from audit log */}
      <Card className="p-5">
        <div className="flex items-center justify-between mb-3">
          <p className="text-[10px] font-semibold uppercase tracking-widest text-[#9d8a72]">Recent System Events</p>
          {recentAudit.length > 0 && (
            <span className="w-1.5 h-1.5 rounded-full bg-[#196f5a] animate-pulse" />
          )}
        </div>
        <div className="space-y-0">
          {recentAudit.length === 0 ? (
            <p className="text-xs text-[#9d8a72] text-center py-4 italic">
              No audit events yet — events appear as the simulation processes readings through the pipeline.
            </p>
          ) : (
            recentAudit.slice(0, 5).map((e, i) => {
              const { type, color } = auditEventType(e)
              return (
                <div key={i} className="flex items-start gap-3 text-xs py-2.5 border-b border-[#e4d8c4] last:border-0">
                  <span className="text-[#9d8a72] font-mono shrink-0 w-16">
                    {new Date(e.escalated_at).toLocaleTimeString()}
                  </span>
                  <span
                    className="px-1.5 py-0.5 rounded text-[9px] font-bold shrink-0"
                    style={{ color, background: `${color}14`, border: `1px solid ${color}30` }}
                  >
                    {type}
                  </span>
                  <span className="text-[#6b5840] leading-relaxed truncate">{auditEventMsg(e)}</span>
                </div>
              )
            })
          )}
        </div>
      </Card>

    </div>
    </SentinelLayout>
  )
}
