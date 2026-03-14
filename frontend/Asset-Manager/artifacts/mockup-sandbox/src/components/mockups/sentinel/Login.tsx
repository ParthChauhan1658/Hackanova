import { useState, useEffect } from 'react'

function cx(...c: (string | false | undefined | null)[]) {
  return c.filter(Boolean).join(' ')
}

const BASE = import.meta.env.BASE_URL?.replace(/\/$/, '') || ''
const ROLES = ['Doctor', 'Nurse', 'Admin', 'Technician']

function saveUser(name: string, email: string, role: string) {
  localStorage.setItem('sentinel_user', JSON.stringify({ name, email, role }))
}

function redirectToDashboard() {
  window.location.href = `${BASE}/preview/sentinel/Dashboard`
}

export function Login() {
  const [mode, setMode]       = useState<'login' | 'signup'>('login')
  const [name, setName]       = useState('')
  const [email, setEmail]     = useState('')
  const [password, setPass]   = useState('')
  const [role, setRole]       = useState('Doctor')
  const [error, setError]     = useState('')
  const [loading, setLoading] = useState(false)

  // If already logged in, redirect
  useEffect(() => {
    try {
      const raw = localStorage.getItem('sentinel_user')
      if (raw) { JSON.parse(raw); redirectToDashboard() }
    } catch { /* ignore */ }
  }, [])

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')

    if (!email.trim()) { setError('Email is required'); return }
    if (!password.trim()) { setError('Password is required'); return }

    if (mode === 'signup') {
      if (!name.trim()) { setError('Full name is required'); return }
      if (password.length < 6) { setError('Password must be at least 6 characters'); return }
      saveUser(name.trim(), email.trim(), role)
      redirectToDashboard()
      return
    }

    // Login — accept any email/password (demo mode, no real auth backend)
    setLoading(true)
    setTimeout(() => {
      const displayName = email.split('@')[0]
        .replace(/[._-]/g, ' ')
        .replace(/\b\w/g, c => c.toUpperCase())
      saveUser(displayName, email.trim(), 'Doctor')
      redirectToDashboard()
    }, 600)
  }

  function demoLogin() {
    saveUser('Dr. Parth Joshi', 'parth@sentinel.local', 'Doctor')
    redirectToDashboard()
  }

  return (
    <div className="min-h-screen flex items-stretch" style={{ background: '#f4ead8', fontFamily: 'inherit' }}>

      {/* ── Left panel — branding ─────────────────────────────────── */}
      <div className="hidden lg:flex w-1/2 flex-col justify-between p-12"
        style={{ background: '#1a6b58' }}>
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-2xl bg-white/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-white" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 2L12.5 7.5H18L13.5 11L15.5 17L10 13.5L4.5 17L6.5 11L2 7.5H7.5L10 2Z"/>
            </svg>
          </div>
          <div>
            <div className="font-black text-white text-lg tracking-wider leading-tight">SENTINEL</div>
            <div className="text-[10px] text-white/60 font-semibold uppercase tracking-widest">Clinical Escalation Agent</div>
          </div>
        </div>

        <div>
          <h1 className="text-4xl font-black text-white leading-tight mb-4">
            AI-powered<br/>clinical<br/>escalation.
          </h1>
          <p className="text-white/70 text-sm leading-relaxed max-w-sm">
            SENTINEL monitors patient vitals in real-time, uses a 5-layer SHAL scoring engine and LLM reasoning to escalate critical conditions — automatically, accurately, and with full audit trails.
          </p>
        </div>

        <div className="space-y-3">
          {[
            { icon: '⚡', label: 'Real-time vital monitoring via Redis streams' },
            { icon: '🧠', label: 'Claude + Gemini LLM clinical reasoning' },
            { icon: '📱', label: 'SMS, email, FCM push escalations' },
            { icon: '📋', label: 'Immutable audit trail in PostgreSQL' },
          ].map(f => (
            <div key={f.label} className="flex items-center gap-3 text-sm text-white/80">
              <span className="text-base">{f.icon}</span>
              <span>{f.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right panel — form ────────────────────────────────────── */}
      <div className="flex-1 flex items-center justify-center p-8">
        <div className="w-full max-w-md">

          {/* Mobile logo */}
          <div className="flex items-center gap-3 mb-8 lg:hidden">
            <div className="w-8 h-8 rounded-xl bg-[#1a6b58] flex items-center justify-center">
              <svg className="w-4 h-4 text-white" viewBox="0 0 20 20" fill="currentColor">
                <path d="M10 2L12.5 7.5H18L13.5 11L15.5 17L10 13.5L4.5 17L6.5 11L2 7.5H7.5L10 2Z"/>
              </svg>
            </div>
            <span className="font-black text-[#271a0c] tracking-wider">SENTINEL</span>
          </div>

          <h2 className="text-2xl font-black text-[#271a0c] mb-1">
            {mode === 'login' ? 'Welcome back' : 'Create account'}
          </h2>
          <p className="text-sm text-[#9b8768] mb-7">
            {mode === 'login'
              ? 'Sign in to the SENTINEL clinical dashboard'
              : 'Register to access the SENTINEL platform'}
          </p>

          {/* Mode tabs */}
          <div className="flex rounded-xl border border-[#ddd0b6] bg-[#f0e6d0] p-1 mb-6">
            {(['login', 'signup'] as const).map(m => (
              <button
                key={m}
                onClick={() => { setMode(m); setError('') }}
                className={cx(
                  'flex-1 py-2 rounded-lg text-sm font-semibold transition-all',
                  mode === m ? 'bg-[#fdfaf2] text-[#271a0c] shadow-sm border border-[#ddd0b6]' : 'text-[#9b8768] hover:text-[#6b5438]'
                )}
              >
                {m === 'login' ? 'Sign In' : 'Sign Up'}
              </button>
            ))}
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">

            {/* Name (signup only) */}
            {mode === 'signup' && (
              <div>
                <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Full Name</label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Dr. Jane Smith"
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] text-sm text-[#271a0c] placeholder:text-[#9b8768] focus:outline-none focus:border-[#1a6b5880] transition-colors"
                />
              </div>
            )}

            {/* Email */}
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Email Address</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@hospital.com"
                className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] text-sm text-[#271a0c] placeholder:text-[#9b8768] focus:outline-none focus:border-[#1a6b5880] transition-colors"
              />
            </div>

            {/* Password */}
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Password</label>
              <input
                type="password"
                value={password}
                onChange={e => setPass(e.target.value)}
                placeholder="••••••••"
                className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] text-sm text-[#271a0c] placeholder:text-[#9b8768] focus:outline-none focus:border-[#1a6b5880] transition-colors"
              />
            </div>

            {/* Role (signup only) */}
            {mode === 'signup' && (
              <div>
                <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Role</label>
                <select
                  value={role}
                  onChange={e => setRole(e.target.value)}
                  className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#fdfaf2] text-sm text-[#271a0c] focus:outline-none focus:border-[#1a6b5880] transition-colors"
                >
                  {ROLES.map(r => <option key={r} value={r}>{r}</option>)}
                </select>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-xl bg-[#f9eeec] border border-[#a8291e30]">
                <svg className="w-4 h-4 text-[#a8291e] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <circle cx="12" cy="12" r="10"/><line x1="12" x2="12" y1="8" y2="12"/><line x1="12" x2="12.01" y1="16" y2="16"/>
                </svg>
                <span className="text-xs text-[#7a1e14]">{error}</span>
              </div>
            )}

            {/* Submit */}
            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 rounded-xl bg-[#1a6b58] text-white text-sm font-bold hover:bg-[#155a49] transition-colors disabled:opacity-60 mt-2"
            >
              {loading ? 'Signing in…' : mode === 'login' ? 'Sign In' : 'Create Account'}
            </button>

          </form>

          {/* Demo access */}
          <div className="mt-4">
            <div className="relative flex items-center gap-3 my-4">
              <div className="flex-1 h-px bg-[#ddd0b6]"/>
              <span className="text-[10px] text-[#9b8768] font-semibold uppercase tracking-widest">or</span>
              <div className="flex-1 h-px bg-[#ddd0b6]"/>
            </div>
            <button
              onClick={demoLogin}
              className="w-full py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f0e6d0] text-[#6b5438] text-sm font-semibold hover:bg-[#e5d9c3] transition-colors flex items-center justify-center gap-2"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>
              </svg>
              Demo Access — Dr. Parth Joshi
            </button>
          </div>

          <p className="text-center text-[10px] text-[#9b8768] mt-6">
            SENTINEL v1.0 · Clinical Escalation Agent · Demo build
          </p>
        </div>
      </div>
    </div>
  )
}
