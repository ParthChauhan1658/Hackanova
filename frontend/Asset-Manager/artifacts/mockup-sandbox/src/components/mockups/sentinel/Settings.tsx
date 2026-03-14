import { useState, useEffect } from 'react'
import { SentinelLayout } from './_SentinelNav'
import {
  fetchContacts,
  addContactNumber, removeContactNumber,
  addContactEmail,  removeContactEmail,
  sendTestSms,      sendTestEmail,
  bookAppointment,
  fetchCalEventTypes,
  type EmergencyContacts,
  type CalEventType,
} from '../../../lib/sentinelApi'

function cx(...c: (string | false | undefined | null)[]) {
  return c.filter(Boolean).join(' ')
}

function Card({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cx('rounded-2xl border border-[#ddd0b6] bg-[#fdfaf2] shadow-sm', className)}>
      {children}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <p className="text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-3">{children}</p>
}

function Input(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className={cx(
        'w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-sm text-[#271a0c] placeholder:text-[#9b8768] focus:outline-none focus:border-[#1a6b5880] transition-colors',
        props.className
      )}
    />
  )
}

function Select(props: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cx(
        'w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-sm text-[#271a0c] focus:outline-none focus:border-[#1a6b5880] transition-colors',
        props.className
      )}
    />
  )
}

type ToastType = 'success' | 'error' | 'info'
interface Toast { id: number; msg: string; type: ToastType }

function useToast() {
  const [toasts, setToasts] = useState<Toast[]>([])
  const add = (msg: string, type: ToastType = 'info') => {
    const id = Date.now()
    setToasts(t => [...t, { id, msg, type }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000)
  }
  return { toasts, add }
}

function ToastContainer({ toasts }: { toasts: Toast[] }) {
  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2">
      {toasts.map(t => (
        <div key={t.id}
          className={cx(
            'px-4 py-3 rounded-xl shadow-lg text-sm font-semibold max-w-xs',
            t.type === 'success' && 'bg-[#1a6b58] text-white',
            t.type === 'error'   && 'bg-[#a8291e] text-white',
            t.type === 'info'    && 'bg-[#fdfaf2] text-[#271a0c] border border-[#ddd0b6]',
          )}
        >
          {t.msg}
        </div>
      ))}
    </div>
  )
}

// ─── Emergency Contacts Section ───────────────────────────────────────────────

function ContactsSection({ toast }: { toast: (m: string, t?: ToastType) => void }) {
  const [contacts, setContacts]  = useState<EmergencyContacts>({ numbers: [], emails: [] })
  const [loading, setLoading]    = useState(true)
  const [newNumber, setNewNumber] = useState('')
  const [newEmail, setNewEmail]   = useState('')
  const [testNum, setTestNum]   = useState('')
  const [testEmail, setTestEmail] = useState('')
  const [busy, setBusy]         = useState(false)

  useEffect(() => {
    fetchContacts()
      .then(c => setContacts(c))
      .catch(() => toast('Could not load contacts — backend may be offline', 'error'))
      .finally(() => setLoading(false))
  }, [])

  async function addNumber() {
    if (!newNumber.trim()) return
    setBusy(true)
    try {
      await addContactNumber(newNumber.trim())
      setContacts(c => ({ ...c, numbers: [...c.numbers, newNumber.trim()] }))
      setNewNumber('')
      toast(`Added ${newNumber.trim()}`, 'success')
    } catch { toast('Failed to add number', 'error') }
    finally { setBusy(false) }
  }

  async function removeNumber(n: string) {
    setBusy(true)
    try {
      await removeContactNumber(n)
      setContacts(c => ({ ...c, numbers: c.numbers.filter(x => x !== n) }))
      toast('Contact removed', 'success')
    } catch { toast('Failed to remove', 'error') }
    finally { setBusy(false) }
  }

  async function addEmail() {
    if (!newEmail.trim()) return
    setBusy(true)
    try {
      await addContactEmail(newEmail.trim())
      setContacts(c => ({ ...c, emails: [...c.emails, newEmail.trim()] }))
      setNewEmail('')
      toast(`Added ${newEmail.trim()}`, 'success')
    } catch { toast('Failed to add email', 'error') }
    finally { setBusy(false) }
  }

  async function removeEmail(e: string) {
    setBusy(true)
    try {
      await removeContactEmail(e)
      setContacts(c => ({ ...c, emails: c.emails.filter(x => x !== e) }))
      toast('Email removed', 'success')
    } catch { toast('Failed to remove', 'error') }
    finally { setBusy(false) }
  }

  async function doTestSms() {
    if (!testNum.trim()) { toast('Enter a number to test', 'error'); return }
    setBusy(true)
    try {
      const res = await sendTestSms(testNum.trim())
      if (res.status === 'queued' || res.status === 'sent') {
        toast(`SMS queued → ${testNum}. Check device (trial accounts require verified numbers).`, 'success')
      } else {
        const detail = res.detail ?? 'unknown error'
        if (detail.includes('unverified') || detail.includes('21608')) {
          toast(`Twilio trial: ${testNum} is not a verified number. Add it at twilio.com/user/account/phone-numbers/verified`, 'error')
        } else {
          toast(`SMS failed: ${detail}`, 'error')
        }
      }
    } finally { setBusy(false) }
  }

  async function doTestEmail() {
    if (!testEmail.trim()) { toast('Enter an email to test', 'error'); return }
    setBusy(true)
    try {
      const res = await sendTestEmail(
        testEmail.trim(),
        'SENTINEL Test — System Operational',
        'This is a test notification from SENTINEL. If you receive this, the SendGrid integration is working correctly.'
      )
      if (res.status === 'sent') {
        toast(`Email sent to ${testEmail} via Resend`, 'success')
      } else {
        toast(`Email failed: ${res.detail ?? 'unknown error'}`, 'error')
      }
    } finally { setBusy(false) }
  }

  return (
    <div className="space-y-5">

      {/* Phone numbers */}
      <Card className="p-5">
        <SectionLabel>Emergency Phone Numbers</SectionLabel>
        <p className="text-[10px] text-[#9b8768] mb-4 leading-relaxed">
          These numbers receive SMS alerts during HIGH and CRITICAL escalations via Twilio. Numbers starting with <code className="bg-[#f0e6d0] px-1 rounded">#</code> in .env are disabled.
        </p>

        {loading ? (
          <div className="text-xs text-[#9b8768]">Loading contacts…</div>
        ) : contacts.numbers.length === 0 ? (
          <div className="text-xs text-[#9b8768] italic">No phone numbers configured.</div>
        ) : (
          <div className="space-y-1.5 mb-4">
            {contacts.numbers.map(n => (
              <div key={n} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#f4ead8] border border-[#ddd0b6]">
                <svg className="w-3.5 h-3.5 text-[#1a6b58] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.8 19.79 19.79 0 0 1 1.59 5.2 2 2 0 0 1 3.56 3h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 10.8a16 16 0 0 0 6.29 6.29l.87-.87a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
                </svg>
                <span className="flex-1 text-sm font-mono text-[#271a0c]">{n}</span>
                <button onClick={() => removeNumber(n)} disabled={busy}
                  className="w-6 h-6 rounded-lg hover:bg-[#f9eeec] flex items-center justify-center transition-colors disabled:opacity-40">
                  <svg className="w-3.5 h-3.5 text-[#a8291e]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/>
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            type="tel"
            placeholder="+91 98765 43210"
            value={newNumber}
            onChange={e => setNewNumber(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addNumber()}
          />
          <button onClick={addNumber} disabled={busy || !newNumber.trim()}
            className="px-4 py-2 rounded-xl bg-[#1a6b58] text-white text-xs font-semibold hover:bg-[#155a49] transition-colors disabled:opacity-50 shrink-0">
            Add
          </button>
        </div>

        {/* Test SMS */}
        <div className="mt-4 pt-4 border-t border-[#ebe1ce]">
          <SectionLabel>Test SMS Delivery</SectionLabel>
          <div className="flex gap-2">
            <Input type="tel" placeholder="+91 98765 43210" value={testNum} onChange={e => setTestNum(e.target.value)}/>
            <button onClick={doTestSms} disabled={busy || !testNum.trim()}
              className="px-4 py-2 rounded-xl bg-[#c07010] text-white text-xs font-semibold hover:bg-[#a05e0c] transition-colors disabled:opacity-50 shrink-0">
              Send Test SMS
            </button>
          </div>
        </div>
      </Card>

      {/* Email addresses */}
      <Card className="p-5">
        <SectionLabel>Emergency Email Addresses</SectionLabel>
        <p className="text-[10px] text-[#9b8768] mb-4 leading-relaxed">
          These addresses receive full HTML clinical reports via Resend during escalations.
        </p>

        {loading ? (
          <div className="text-xs text-[#9b8768]">Loading contacts…</div>
        ) : contacts.emails.length === 0 ? (
          <div className="text-xs text-[#9b8768] italic">No email addresses configured.</div>
        ) : (
          <div className="space-y-1.5 mb-4">
            {contacts.emails.map(em => (
              <div key={em} className="flex items-center gap-2 px-3 py-2 rounded-xl bg-[#f4ead8] border border-[#ddd0b6]">
                <svg className="w-3.5 h-3.5 text-[#1a6b58] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/>
                  <polyline points="22,6 12,13 2,6"/>
                </svg>
                <span className="flex-1 text-sm text-[#271a0c]">{em}</span>
                <button onClick={() => removeEmail(em)} disabled={busy}
                  className="w-6 h-6 rounded-lg hover:bg-[#f9eeec] flex items-center justify-center transition-colors disabled:opacity-40">
                  <svg className="w-3.5 h-3.5 text-[#a8291e]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/>
                  </svg>
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="flex gap-2">
          <Input
            type="email"
            placeholder="doctor@hospital.com"
            value={newEmail}
            onChange={e => setNewEmail(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && addEmail()}
          />
          <button onClick={addEmail} disabled={busy || !newEmail.trim()}
            className="px-4 py-2 rounded-xl bg-[#1a6b58] text-white text-xs font-semibold hover:bg-[#155a49] transition-colors disabled:opacity-50 shrink-0">
            Add
          </button>
        </div>

        {/* Test email */}
        <div className="mt-4 pt-4 border-t border-[#ebe1ce]">
          <SectionLabel>Test Email Delivery</SectionLabel>
          <div className="flex gap-2">
            <Input type="email" placeholder="test@example.com" value={testEmail} onChange={e => setTestEmail(e.target.value)}/>
            <button onClick={doTestEmail} disabled={busy || !testEmail.trim()}
              className="px-4 py-2 rounded-xl bg-[#c07010] text-white text-xs font-semibold hover:bg-[#a05e0c] transition-colors disabled:opacity-50 shrink-0">
              Send Test Email
            </button>
          </div>

        </div>
      </Card>

      {/* Twilio trial note */}
      <Card className="p-4">
        <div className="flex items-start gap-3">
          <svg className="w-4 h-4 text-[#9b8768] shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>
          </svg>
          <div>
            <p className="text-[10px] font-bold text-[#6b5438] mb-1">Twilio Trial Account — SMS Delivery</p>
            <p className="text-[10px] text-[#9b8768] leading-relaxed">
              On Twilio trial accounts, SMS can only be delivered to <strong>verified phone numbers</strong>.
              Add recipient numbers at{' '}
              <button onClick={() => window.open('https://console.twilio.com/us1/develop/phone-numbers/manage/verified', '_blank')}
                className="text-[#2a7fa0] underline">
                console.twilio.com → Verified Caller IDs
              </button>.
              Production accounts have no such restriction.
            </p>
          </div>
        </div>
      </Card>
    </div>
  )
}

// ─── Appointment Booking Section ──────────────────────────────────────────────

const APPOINTMENT_REASONS = [
  'Urgent clinical review — escalation follow-up',
  'Post-critical event assessment',
  'Respiratory distress monitoring review',
  'Cardiac rhythm follow-up',
  'Fall event follow-up',
  'Medication adjustment consultation',
  'General ward review',
  'Discharge planning',
]

function AppointmentSection({ toast }: { toast: (m: string, t?: ToastType) => void }) {
  const [patientId, setPatientId]   = useState('P01')
  const [patientName, setName]      = useState('')
  const [patientEmail, setEmail]    = useState('')
  const [reason, setReason]         = useState(APPOINTMENT_REASONS[0])
  const [notes, setNotes]           = useState('')
  const [minutesFrom, setMinutes]   = useState(60)
  const [busy, setBusy]             = useState(false)
  const [lastBooking, setLastBooking] = useState<{ id: string; start: string } | null>(null)
  const [calEventTypes, setCalEventTypes] = useState<CalEventType[]>([])
  const [selectedEventTypeId, setSelectedEventTypeId] = useState<number | null>(null)

  useEffect(() => {
    fetchCalEventTypes().then(res => {
      if (res.status === 'ok' && res.event_types.length > 0) {
        setCalEventTypes(res.event_types)
        setSelectedEventTypeId(res.event_types[0].id)
      } else if (res.detail) {
        toast(`Cal.com: ${res.detail}`, 'error')
      }
    }).catch(() => { /* cal.com offline */ })
  }, [])

  async function handleBook(e: React.FormEvent) {
    e.preventDefault()
    if (!patientName.trim()) { toast('Patient name required', 'error'); return }
    if (!patientEmail.trim()) { toast('Patient email required', 'error'); return }
    setBusy(true)
    try {
      const res = await bookAppointment({
        patient_id: patientId,
        patient_name: patientName,
        patient_email: patientEmail,
        reason,
        notes,
        minutes_from_now: minutesFrom,
        event_type_id: selectedEventTypeId ?? undefined,
      })
      if (res.status === 'booked') {
        setLastBooking({ id: res.booking_id ?? 'confirmed', start: res.start ?? '' })
        toast(`Appointment booked — ID: ${res.booking_id}`, 'success')
      } else {
        // Extract the key message from Cal.com's verbose error JSON
        let errMsg = res.detail ?? 'Cal.com error'
        try {
          const jsonStart = errMsg.indexOf('{')
          if (jsonStart !== -1) {
            const parsed = JSON.parse(errMsg.slice(errMsg.indexOf('{') ))
            const inner = parsed?.error?.message ?? parsed?.message ?? ''
            if (inner) errMsg = inner
          }
        } catch { /* keep original */ }
        toast(`Booking failed: ${errMsg}`, 'error')
      }
    } catch { toast('Booking failed — check backend', 'error') }
    finally { setBusy(false) }
  }

  const slotTime = new Date(Date.now() + minutesFrom * 60 * 1000)

  return (
    <Card className="p-5">
      <SectionLabel>Book Appointment via Cal.com</SectionLabel>
      <p className="text-[10px] text-[#9b8768] mb-5 leading-relaxed">
        Schedule an urgent clinical review directly from SENTINEL. Booking is created via the Cal.com REST API and sent to the patient's email.
      </p>

      {lastBooking && (
        <div className="mb-5 flex items-start gap-3 px-4 py-3 rounded-xl bg-[#edf7f4] border border-[#1a6b5830]">
          <svg className="w-5 h-5 text-[#1a6b58] shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <div>
            <p className="text-sm font-semibold text-[#1a6b58]">Appointment Booked</p>
            <p className="text-xs text-[#6b5438] mt-0.5">
              Booking ID: <span className="font-mono">{lastBooking.id}</span>
              {lastBooking.start && <> · {new Date(lastBooking.start).toLocaleString()}</>}
            </p>
          </div>
          <button onClick={() => setLastBooking(null)} className="ml-auto text-[#9b8768] hover:text-[#6b5438]">
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><line x1="18" x2="6" y1="6" y2="18"/><line x1="6" x2="18" y1="6" y2="18"/></svg>
          </button>
        </div>
      )}

      {calEventTypes.length > 0 && (
        <div className="mb-5 flex items-center gap-2 px-3 py-2.5 rounded-xl bg-[#edf7f4] border border-[#1a6b5830]">
          <svg className="w-4 h-4 text-[#1a6b58] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <span className="text-xs text-[#1a6b58] font-semibold">{calEventTypes.length} event type(s) loaded from Cal.com</span>
        </div>
      )}

      <form onSubmit={handleBook} className="space-y-4">

        {calEventTypes.length > 0 && (
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Event Type</label>
            <Select value={selectedEventTypeId ?? ''} onChange={e => setSelectedEventTypeId(Number(e.target.value))}>
              {calEventTypes.map(et => (
                <option key={et.id} value={et.id}>{et.title} ({et.length} min)</option>
              ))}
            </Select>
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Patient ID</label>
            <Input value={patientId} onChange={e => setPatientId(e.target.value)} placeholder="P01"/>
          </div>
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Schedule</label>
            <Select value={minutesFrom} onChange={e => setMinutes(Number(e.target.value))}>
              <option value={30}>In 30 minutes</option>
              <option value={60}>In 1 hour</option>
              <option value={120}>In 2 hours</option>
              <option value={240}>In 4 hours</option>
              <option value={480}>Tomorrow (8h)</option>
            </Select>
          </div>
        </div>

        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Patient Name</label>
          <Input value={patientName} onChange={e => setName(e.target.value)} placeholder="John Doe"/>
        </div>

        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Patient Email</label>
          <Input type="email" value={patientEmail} onChange={e => setEmail(e.target.value)} placeholder="patient@example.com"/>
        </div>

        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Reason</label>
          <Select value={reason} onChange={e => setReason(e.target.value)}>
            {APPOINTMENT_REASONS.map(r => <option key={r} value={r}>{r}</option>)}
          </Select>
        </div>

        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Additional Notes</label>
          <textarea
            value={notes}
            onChange={e => setNotes(e.target.value)}
            rows={3}
            placeholder="Optional clinical context, special requirements…"
            className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-sm text-[#271a0c] placeholder:text-[#9b8768] focus:outline-none focus:border-[#1a6b5880] transition-colors resize-none"
          />
        </div>

        <div className="flex items-center justify-between pt-1">
          <div className="text-xs text-[#9b8768]">
            Slot: <span className="font-mono text-[#271a0c] font-semibold">
              {slotTime.toLocaleDateString()} {slotTime.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            </span>
          </div>
          <button type="submit" disabled={busy}
            className="px-6 py-2.5 rounded-xl bg-[#1a6b58] text-white text-sm font-bold hover:bg-[#155a49] transition-colors disabled:opacity-60 flex items-center gap-2">
            {busy ? (
              <>
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                </svg>
                Booking…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/>
                </svg>
                Book Appointment
              </>
            )}
          </button>
        </div>
      </form>
    </Card>
  )
}

// ─── Profile Section ──────────────────────────────────────────────────────────

function ProfileSection({ toast }: { toast: (m: string, t?: ToastType) => void }) {
  const [name, setName]   = useState('')
  const [email, setEmail] = useState('')
  const [role, setRole]   = useState('Doctor')

  useEffect(() => {
    try {
      const raw = localStorage.getItem('sentinel_user')
      if (raw) {
        const u = JSON.parse(raw)
        setName(u.name ?? '')
        setEmail(u.email ?? '')
        setRole(u.role ?? 'Doctor')
      }
    } catch { /* ignore */ }
  }, [])

  function save(e: React.FormEvent) {
    e.preventDefault()
    localStorage.setItem('sentinel_user', JSON.stringify({ name, email, role }))
    toast('Profile saved', 'success')
  }

  return (
    <Card className="p-5">
      <SectionLabel>Your Profile</SectionLabel>
      <form onSubmit={save} className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Full Name</label>
            <Input value={name} onChange={e => setName(e.target.value)} placeholder="Dr. Jane Smith"/>
          </div>
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Role</label>
            <Select value={role} onChange={e => setRole(e.target.value)}>
              {['Doctor', 'Nurse', 'Admin', 'Technician'].map(r => <option key={r}>{r}</option>)}
            </Select>
          </div>
        </div>
        <div>
          <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Email</label>
          <Input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@hospital.com"/>
        </div>
        <div className="flex justify-end">
          <button type="submit"
            className="px-5 py-2 rounded-xl bg-[#1a6b58] text-white text-sm font-semibold hover:bg-[#155a49] transition-colors">
            Save Profile
          </button>
        </div>
      </form>
    </Card>
  )
}

// ─── Main Settings page ───────────────────────────────────────────────────────

type Tab = 'contacts' | 'appointments' | 'profile'

export function Settings() {
  const [tab, setTab] = useState<Tab>('contacts')
  const { toasts, add: toast } = useToast()

  const tabs: { key: Tab; label: string; icon: React.ReactNode }[] = [
    {
      key: 'contacts', label: 'Emergency Contacts',
      icon: <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.8 19.79 19.79 0 0 1 1.59 5.2 2 2 0 0 1 3.56 3h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 10.8a16 16 0 0 0 6.29 6.29l.87-.87a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/></svg>,
    },
    {
      key: 'appointments', label: 'Book Appointment',
      icon: <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" x2="16" y1="2" y2="6"/><line x1="8" x2="8" y1="2" y2="6"/><line x1="3" x2="21" y1="10" y2="10"/></svg>,
    },
    {
      key: 'profile', label: 'Profile',
      icon: <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>,
    },
  ]

  return (
    <SentinelLayout>
      <ToastContainer toasts={toasts}/>

      <div className="p-6 space-y-5">
        <div>
          <h1 className="text-2xl font-black text-[#271a0c] tracking-tight">Settings</h1>
          <p className="text-xs text-[#9b8768] mt-0.5">Manage emergency contacts, book appointments, and configure your profile</p>
        </div>

        {/* Tab bar */}
        <div className="flex gap-2 border-b border-[#ddd0b6] pb-1">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={cx(
                'flex items-center gap-2 px-4 py-2 rounded-t-xl text-sm font-semibold transition-all border border-b-0',
                tab === t.key
                  ? 'bg-[#fdfaf2] text-[#271a0c] border-[#ddd0b6]'
                  : 'text-[#9b8768] border-transparent hover:text-[#6b5438]'
              )}
            >
              {t.icon}
              {t.label}
            </button>
          ))}
        </div>

        {tab === 'contacts'     && <ContactsSection    toast={toast}/>}
        {tab === 'appointments' && <AppointmentSection toast={toast}/>}
        {tab === 'profile'      && <ProfileSection     toast={toast}/>}
      </div>
    </SentinelLayout>
  )
}
