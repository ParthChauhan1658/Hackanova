/**
 * Shared navigation sidebar for all SENTINEL pages.
 * Underscore prefix = excluded from mockupPreviewPlugin auto-routing.
 */
import { useEffect, useState } from 'react'

export interface SentinelUser {
  name: string
  email: string
  role: string
}

function getCurrentUser(): SentinelUser | null {
  try {
    const raw = localStorage.getItem('sentinel_user')
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function cx(...c: (string | false | undefined | null)[]) {
  return c.filter(Boolean).join(' ')
}

const BASE = import.meta.env.BASE_URL?.replace(/\/$/, '') || ''

const NAV_ITEMS = [
  {
    key: 'Dashboard',
    label: 'Dashboard',
    path: `${BASE}/preview/sentinel/Dashboard`,
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/>
        <rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/>
      </svg>
    ),
  },
  {
    key: 'AuditTrail',
    label: 'Audit Trail',
    path: `${BASE}/preview/sentinel/AuditTrail`,
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.586a1 1 0 0 1 .707.293l5.414 5.414a1 1 0 0 1 .293.707V19a2 2 0 0 1-2 2z"/>
      </svg>
    ),
  },
  {
    key: 'SystemHealth',
    label: 'System Health',
    path: `${BASE}/preview/sentinel/SystemHealth`,
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
      </svg>
    ),
  },
  {
    key: 'NearbyDoctors',
    label: 'Nearby Doctors',
    path: `${BASE}/preview/sentinel/NearbyDoctors`,
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/>
        <path d="M12 7v6m-3-3h6"/>
      </svg>
    ),
  },
  {
    key: 'Settings',
    label: 'Settings',
    path: `${BASE}/preview/sentinel/Settings`,
    icon: (
      <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    ),
  },
]

interface Props {
  children: React.ReactNode
}

export function SentinelLayout({ children }: Props) {
  const [user, setUser] = useState<SentinelUser | null>(null)
  const [currentKey, setCurrentKey] = useState('')

  useEffect(() => {
    setUser(getCurrentUser())
    const path = window.location.pathname
    const found = NAV_ITEMS.find(n => path.includes(n.key))
    setCurrentKey(found?.key ?? '')
  }, [])

  function navigate(path: string) {
    window.location.href = path
  }

  function logout() {
    localStorage.removeItem('sentinel_user')
    window.location.href = `${BASE}/preview/sentinel/Login`
  }

  function roleColor(role: string) {
    if (role === 'Doctor') return '#1a6b58'
    if (role === 'Nurse') return '#2a7fa0'
    return '#9b8768'
  }

  return (
    <div className="flex min-h-screen" style={{ background: '#f4ead8', fontFamily: 'inherit' }}>

      {/* ── Sidebar ────────────────────────────────────────────────────── */}
      <aside className="w-56 shrink-0 flex flex-col border-r border-[#ddd0b6]" style={{ background: '#ede0ca' }}>

        {/* Logo */}
        <div className="flex items-center gap-2.5 px-4 py-4 border-b border-[#ddd0b6]">
          <div className="w-7 h-7 rounded-xl bg-[#1a6b58] flex items-center justify-center shadow-sm shrink-0">
            <svg className="w-4 h-4 text-white" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 2L12.5 7.5H18L13.5 11L15.5 17L10 13.5L4.5 17L6.5 11L2 7.5H7.5L10 2Z"/>
            </svg>
          </div>
          <div>
            <div className="font-black text-[#271a0c] text-sm tracking-wider leading-tight">SENTINEL</div>
            <div className="text-[9px] text-[#a06a20] font-semibold uppercase tracking-widest leading-tight">Clinical AI</div>
          </div>
        </div>

        {/* Nav items */}
        <nav className="flex-1 p-3 space-y-1">
          {NAV_ITEMS.map(item => {
            const active = currentKey === item.key
            return (
              <button
                key={item.key}
                onClick={() => navigate(item.path)}
                className={cx(
                  'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-left text-sm font-medium transition-all',
                  active
                    ? 'bg-[#1a6b58] text-white shadow-sm'
                    : 'text-[#6b5438] hover:bg-[#ddd0b6] hover:text-[#271a0c]'
                )}
              >
                <span className={active ? 'text-white' : 'text-[#9b8768]'}>{item.icon}</span>
                {item.label}
              </button>
            )
          })}
        </nav>

        {/* Live indicator */}
        <div className="px-4 py-2">
          <div className="flex items-center gap-2 text-[10px] text-[#9b8768]">
            <span className="w-1.5 h-1.5 rounded-full bg-[#1a6b58] animate-pulse"/>
            Live · dataset.csv
          </div>
        </div>

        {/* User section */}
        <div className="border-t border-[#ddd0b6] p-3">
          {user ? (
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 rounded-xl flex items-center justify-center text-white text-xs font-bold shrink-0"
                style={{ background: roleColor(user.role) }}>
                {user.name.charAt(0).toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold text-[#271a0c] truncate">{user.name}</div>
                <div className="text-[9px] text-[#9b8768] truncate">{user.role}</div>
              </div>
              <button
                onClick={logout}
                title="Sign out"
                className="w-7 h-7 rounded-lg flex items-center justify-center hover:bg-[#f9eeec] transition-colors"
              >
                <svg className="w-3.5 h-3.5 text-[#9b8768]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
                  <polyline points="16 17 21 12 16 7"/>
                  <line x1="21" x2="9" y1="12" y2="12"/>
                </svg>
              </button>
            </div>
          ) : (
            <button
              onClick={() => navigate(`${BASE}/preview/sentinel/Login`)}
              className="w-full flex items-center gap-2 px-3 py-2 rounded-xl bg-[#1a6b58] text-white text-xs font-semibold hover:bg-[#155a49] transition-colors"
            >
              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/>
                <polyline points="10 17 15 12 10 7"/>
                <line x1="15" x2="3" y1="12" y2="12"/>
              </svg>
              Sign In
            </button>
          )}
        </div>
      </aside>

      {/* ── Main content ──────────────────────────────────────────────── */}
      <main className="flex-1 min-w-0 overflow-y-auto">
        {children}
      </main>
    </div>
  )
}
