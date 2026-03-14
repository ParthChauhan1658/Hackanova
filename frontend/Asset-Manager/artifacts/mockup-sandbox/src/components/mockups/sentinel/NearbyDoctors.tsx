import { useState, useEffect, useCallback } from 'react'
import { SentinelLayout } from './_SentinelNav'
import {
  fetchNearbyDoctors,
  fetchLatestVitals,
  fetchAuditLog,
  type NearbyDoctor,
  type NearbyDoctorsResponse,
} from '../../../lib/sentinelApi'

function cx(...c: (string | false | undefined | null)[]) {
  return c.filter(Boolean).join(' ')
}

// ── Design tokens (match existing SENTINEL palette) ──────────────────────────
const AMENITY_COLORS: Record<string, { bg: string; text: string; ring: string }> = {
  hospital: { bg: '#fdf1f0', text: '#b02a22', ring: '#f5c3bf' },
  clinic:   { bg: '#fef6ec', text: '#9a5200', ring: '#f5ddb5' },
  doctors:  { bg: '#edf7f4', text: '#145a48', ring: '#a3d9cb' },
  doctor:   { bg: '#edf7f4', text: '#145a48', ring: '#a3d9cb' },
  pharmacy: { bg: '#edf2f9', text: '#1e5a80', ring: '#a3c4de' },
}
const DEFAULT_AMENITY = { bg: '#f4f0eb', text: '#6b5438', ring: '#ddd0b6' }

const ALL_SYNDROMES = [
  'SIRS_EARLY_SEPSIS',
  'RESPIRATORY_FAILURE',
  'HYPOXIC_EPISODE',
  'DISTRIBUTIVE_SHOCK',
  'AUTONOMIC_COLLAPSE',
  'MULTI_SYSTEM_STRESS',
  'ECG_VT_VF',
  'ECG_STEMI',
  'FALL_UNRESPONSIVE',
  'TEMP_HYPERPYREXIA',
]

const RADIUS_OPTIONS = [
  { label: '500 m', value: 500 },
  { label: '1 km',  value: 1000 },
  { label: '2 km',  value: 2000 },
  { label: '5 km',  value: 5000 },
  { label: '10 km', value: 10000 },
  { label: '20 km', value: 20000 },
]

// ── Sub-components ────────────────────────────────────────────────────────────

function StarRating({ rating }: { rating: number | null }) {
  if (rating == null) {
    return <span className="text-[10px] text-[#9b8768] italic">No rating</span>
  }
  const full  = Math.floor(rating)
  const half  = rating - full >= 0.5
  const empty = 5 - full - (half ? 1 : 0)
  return (
    <div className="flex items-center gap-1">
      <span className="text-[#c07010] text-xs leading-none">
        {'★'.repeat(full)}{half ? '⯨' : ''}
        <span className="text-[#ddd0b6]">{'★'.repeat(empty)}</span>
      </span>
      <span className="text-[10px] font-bold text-[#6b5438]">{rating.toFixed(1)}</span>
    </div>
  )
}

function ScoreBar({ score }: { score: number }) {
  const pct   = Math.min(100, (score / 100) * 100)
  const color = score >= 70 ? '#1a6b58' : score >= 50 ? '#c07010' : score >= 30 ? '#a06a20' : '#9b8768'
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 rounded-full bg-[#ebe1ce] overflow-hidden">
        <div className="h-full rounded-full transition-all duration-300" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="text-[10px] font-bold w-6 text-right" style={{ color }}>{score}</span>
    </div>
  )
}

function AmenityBadge({ amenity }: { amenity: string }) {
  const col = AMENITY_COLORS[amenity] ?? DEFAULT_AMENITY
  return (
    <span
      className="inline-block px-2 py-0.5 rounded-full text-[9px] font-bold uppercase tracking-wider border"
      style={{ background: col.bg, color: col.text, borderColor: col.ring }}
    >
      {amenity.replace('_', ' ')}
    </span>
  )
}

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-[#ddd0b6] bg-[#fdfaf2] p-5 animate-pulse space-y-3">
      <div className="flex items-center gap-3">
        <div className="w-16 h-4 bg-[#ebe1ce] rounded-full" />
        <div className="flex-1 h-4 bg-[#ebe1ce] rounded-full" />
        <div className="w-12 h-4 bg-[#ebe1ce] rounded-full" />
      </div>
      <div className="h-3 bg-[#ebe1ce] rounded-full w-3/4" />
      <div className="h-3 bg-[#ebe1ce] rounded-full w-1/2" />
      <div className="flex gap-2 pt-1">
        <div className="h-7 bg-[#ebe1ce] rounded-xl flex-1" />
        <div className="h-7 bg-[#ebe1ce] rounded-xl w-20" />
      </div>
    </div>
  )
}

function DoctorCard({ doc, rank }: { doc: NearbyDoctor; rank: number }) {
  const col     = AMENITY_COLORS[doc.amenity_type] ?? DEFAULT_AMENITY
  const isOpen  = doc.opening_hours !== 'Hours not listed'

  return (
    <div className="rounded-2xl border border-[#ddd0b6] bg-[#fdfaf2] shadow-sm hover:shadow-md transition-shadow overflow-hidden">
      {/* Header */}
      <div className="flex items-start gap-3 p-4 pb-3 border-b border-[#ebe1ce]">
        {/* Rank + type icon */}
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0 text-sm font-black border"
          style={{ background: col.bg, color: col.text, borderColor: col.ring }}
        >
          {rank}
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start gap-2 flex-wrap">
            <AmenityBadge amenity={doc.amenity_type} />
            {doc.wheelchair_accessible && (
              <span className="px-1.5 py-0.5 rounded-full text-[9px] font-semibold bg-[#edf2f9] text-[#1e5a80] border border-[#a3c4de]">
                ♿ Accessible
              </span>
            )}
          </div>
          <h3 className="font-bold text-[#271a0c] text-sm mt-1 leading-tight truncate">{doc.name}</h3>
          {doc.specialization && (
            <p className="text-[10px] text-[#6b5438] mt-0.5 capitalize">{doc.specialization.replace(/_/g, ' ')}</p>
          )}
        </div>

        {/* Distance badge */}
        <div className="shrink-0 text-right">
          <span className="px-2.5 py-1 rounded-xl bg-[#f4ead8] border border-[#ddd0b6] text-[11px] font-bold text-[#6b5438]">
            {doc.distance_km < 1
              ? `${Math.round(doc.distance_km * 1000)} m`
              : `${doc.distance_km.toFixed(1)} km`}
          </span>
        </div>
      </div>

      {/* Body */}
      <div className="px-4 py-3 space-y-1.5">
        {doc.address && (
          <div className="flex items-start gap-2">
            <svg className="w-3.5 h-3.5 text-[#9b8768] shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
            </svg>
            <span className="text-[11px] text-[#6b5438] leading-snug">{doc.address}</span>
          </div>
        )}

        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-[#9b8768] shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
          </svg>
          <span className={cx('text-[11px]', isOpen ? 'text-[#145a48] font-semibold' : 'text-[#9b8768] italic')}>
            {doc.opening_hours}
          </span>
        </div>

        {/* Rating */}
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-[#c07010] shrink-0" viewBox="0 0 24 24" fill="currentColor">
            <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/>
          </svg>
          <StarRating rating={doc.rating} />
        </div>
      </div>

      {/* Score bar */}
      <div className="px-4 pb-3">
        <div className="flex items-center justify-between mb-1">
          <span className="text-[9px] font-bold uppercase tracking-wider text-[#9b8768]">Relevance Score</span>
          <div className="flex gap-2 text-[9px] text-[#9b8768]">
            <span>Prox {doc.score_breakdown.proximity}</span>
            <span>·</span>
            <span>Spec {doc.score_breakdown.specialization}</span>
            {doc.score_breakdown.rating > 0 && <><span>·</span><span>Rating {doc.score_breakdown.rating}</span></>}
          </div>
        </div>
        <ScoreBar score={doc.score} />
      </div>

      {/* Actions */}
      <div className="flex gap-2 px-4 pb-4">
        <a
          href={doc.google_maps_url}
          target="_blank"
          rel="noopener noreferrer"
          className="flex-1 flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-[#1a6b58] text-white text-[11px] font-semibold hover:bg-[#155a49] transition-colors"
        >
          <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
          </svg>
          Directions
        </a>

        {doc.phone && (
          <a
            href={`tel:${doc.phone}`}
            className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-[#271a0c] text-[11px] font-semibold hover:bg-[#ebe1ce] transition-colors"
          >
            <svg className="w-3.5 h-3.5 text-[#1a6b58]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.69 13.8 19.79 19.79 0 0 1 1.59 5.2 2 2 0 0 1 3.56 3h3a2 2 0 0 1 2 1.72c.127.96.361 1.903.7 2.81a2 2 0 0 1-.45 2.11L7.91 10.8a16 16 0 0 0 6.29 6.29l.87-.87a2 2 0 0 1 2.11-.45c.907.339 1.85.573 2.81.7A2 2 0 0 1 22 16.92z"/>
            </svg>
            Call
          </a>
        )}

        {doc.website && (
          <a
            href={doc.website.startsWith('http') ? doc.website : `https://${doc.website}`}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-[#271a0c] text-[11px] font-semibold hover:bg-[#ebe1ce] transition-colors"
          >
            <svg className="w-3.5 h-3.5 text-[#1a6b58]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/>
              <path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>
            </svg>
            Web
          </a>
        )}
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────────

export function NearbyDoctors() {
  const [patientId, setPatientId]   = useState('P01')
  const [radiusM, setRadiusM]       = useState(5000)
  const [syndromes, setSyndromes]   = useState<string[]>([])
  const [data, setData]             = useState<NearbyDoctorsResponse | null>(null)
  const [loading, setLoading]       = useState(false)
  const [error, setError]           = useState<string | null>(null)
  const [autoLoc, setAutoLoc]       = useState<{ lat: number; lng: number } | null>(null)
  const [lastFetch, setLastFetch]   = useState<Date | null>(null)

  // Auto-detect syndromes from latest audit entry
  useEffect(() => {
    fetchAuditLog(1).then(res => {
      const entry = res.entries[0]
      if (entry?.syndromes_fired?.length) {
        setSyndromes(entry.syndromes_fired.slice(0, 3))
      }
    }).catch(() => {})
  }, [])

  // Auto-detect patient location from latest vitals
  useEffect(() => {
    fetchLatestVitals(patientId).then(v => {
      if (v.latitude && v.longitude) {
        setAutoLoc({ lat: v.latitude, lng: v.longitude })
      }
    }).catch(() => {})
  }, [patientId])

  const doFetch = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetchNearbyDoctors({
        patient_id: patientId,
        radius_m:   radiusM,
        syndromes:  syndromes.length ? syndromes : undefined,
        limit:      12,
      })
      setData(res)
      setLastFetch(new Date())
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to fetch nearby doctors')
    } finally {
      setLoading(false)
    }
  }, [patientId, radiusM, syndromes])

  function toggleSyndrome(s: string) {
    setSyndromes(prev =>
      prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]
    )
  }

  const doctors = data?.ranked_doctors ?? []

  return (
    <SentinelLayout>
      <div className="p-6 space-y-5 max-w-5xl">

        {/* Header */}
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-black text-[#271a0c] tracking-tight">Nearby Medical Facilities</h1>
            <p className="text-xs text-[#9b8768] mt-0.5">
              Ranked by proximity, specialization match{data?.serp_enriched ? ', and Google ratings' : ''} — powered by OpenStreetMap
            </p>
          </div>

          {/* Location pill */}
          {(autoLoc || data?.patient_location) && (
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-xl bg-[#edf7f4] border border-[#1a6b5830] text-[10px] text-[#145a48] font-semibold">
              <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
              </svg>
              {(() => {
                const loc = data?.patient_location ?? autoLoc
                return loc ? `${loc.lat.toFixed(4)}, ${loc.lng.toFixed(4)}` : 'Detecting…'
              })()}
            </div>
          )}
        </div>

        {/* Controls */}
        <div className="rounded-2xl border border-[#ddd0b6] bg-[#fdfaf2] p-5 space-y-4">

          <div className="grid grid-cols-2 gap-4">
            {/* Patient ID */}
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Patient ID</label>
              <input
                value={patientId}
                onChange={e => setPatientId(e.target.value)}
                className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-sm text-[#271a0c] focus:outline-none focus:border-[#1a6b5880] transition-colors"
                placeholder="P01"
              />
            </div>

            {/* Radius */}
            <div>
              <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-1.5">Search Radius</label>
              <select
                value={radiusM}
                onChange={e => setRadiusM(Number(e.target.value))}
                className="w-full px-3.5 py-2.5 rounded-xl border border-[#ddd0b6] bg-[#f4ead8] text-sm text-[#271a0c] focus:outline-none focus:border-[#1a6b5880] transition-colors"
              >
                {RADIUS_OPTIONS.map(o => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Syndrome filter */}
          <div>
            <label className="block text-[10px] font-bold uppercase tracking-widest text-[#9b8768] mb-2">
              Active Syndromes (affects specialization scoring)
            </label>
            <div className="flex flex-wrap gap-1.5">
              {ALL_SYNDROMES.map(s => {
                const active = syndromes.includes(s)
                return (
                  <button
                    key={s}
                    onClick={() => toggleSyndrome(s)}
                    className={cx(
                      'px-2.5 py-1 rounded-full text-[10px] font-semibold border transition-all',
                      active
                        ? 'bg-[#1a6b58] text-white border-[#1a6b58]'
                        : 'bg-[#f4ead8] text-[#6b5438] border-[#ddd0b6] hover:border-[#9b8768]'
                    )}
                  >
                    {s.replace(/_/g, ' ')}
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex items-center justify-between pt-1">
            <div className="text-[10px] text-[#9b8768]">
              {data && (
                <div className="flex items-center gap-2 flex-wrap">
                  <span>{data.total_found} found · {data.fetch_time_ms.toFixed(0)} ms</span>
                  {data.osm_cache_hit && <span className="px-1.5 py-0.5 bg-[#ebe1ce] rounded-full text-[9px]">cached</span>}
                  {data.serp_enriched
                    ? <span className="px-1.5 py-0.5 bg-[#edf7f4] rounded-full text-[9px] text-[#145a48] font-semibold">★ sorted by rating</span>
                    : <span className="px-1.5 py-0.5 bg-[#f4ead8] rounded-full text-[9px] text-[#9b8768]">sorted by proximity + specialization</span>}
                </div>
              )}
            </div>
            <button
              onClick={doFetch}
              disabled={loading}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-[#1a6b58] text-white text-sm font-bold hover:bg-[#155a49] transition-colors disabled:opacity-60"
            >
              {loading ? (
                <>
                  <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M21 12a9 9 0 1 1-6.219-8.56"/>
                  </svg>
                  Searching…
                </>
              ) : (
                <>
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                  </svg>
                  Find Nearby
                </>
              )}
            </button>
          </div>
        </div>

        {/* Error state */}
        {error && (
          <div className="flex items-start gap-3 px-4 py-3 rounded-xl bg-[#fdf1f0] border border-[#f5c3bf]">
            <svg className="w-4 h-4 text-[#b02a22] shrink-0 mt-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            <div>
              <p className="text-[11px] font-bold text-[#b02a22]">Search failed</p>
              <p className="text-[11px] text-[#6b5438] mt-0.5">{error}</p>
            </div>
          </div>
        )}

        {/* Loading skeletons */}
        {loading && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {Array.from({ length: 6 }).map((_, i) => <SkeletonCard key={i} />)}
          </div>
        )}

        {/* Results grid */}
        {!loading && doctors.length > 0 && (
          <>
            {/* Specialization hint */}
            {data!.relevant_specialties.length > 0 && (
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[10px] font-bold uppercase tracking-wider text-[#9b8768]">Prioritising:</span>
                {data!.relevant_specialties.slice(0, 6).map(s => (
                  <span key={s} className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-[#edf7f4] text-[#145a48] border border-[#a3d9cb]">
                    {s.replace(/_/g, ' ')}
                  </span>
                ))}
              </div>
            )}

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {doctors.map((doc, i) => (
                <DoctorCard key={doc.osm_id || i} doc={doc} rank={i + 1} />
              ))}
            </div>

            {/* Map link */}
            {data?.patient_location && (
              <a
                href={`https://www.openstreetmap.org/?mlat=${data.patient_location.lat}&mlon=${data.patient_location.lng}&zoom=14`}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-center gap-2 py-2.5 rounded-xl border border-[#ddd0b6] text-xs text-[#6b5438] hover:bg-[#f4ead8] transition-colors"
              >
                <svg className="w-4 h-4 text-[#9b8768]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6"/>
                  <line x1="8" y1="2" x2="8" y2="18"/><line x1="16" y1="6" x2="16" y2="22"/>
                </svg>
                View patient location on OpenStreetMap
              </a>
            )}
          </>
        )}

        {/* Empty state (after a search with no results) */}
        {!loading && !error && data && doctors.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <div className="w-14 h-14 rounded-2xl bg-[#f4ead8] border border-[#ddd0b6] flex items-center justify-center mb-4">
              <svg className="w-7 h-7 text-[#9b8768]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>
              </svg>
            </div>
            <p className="font-bold text-[#271a0c] text-sm">No facilities found</p>
            <p className="text-[11px] text-[#9b8768] mt-1">Try increasing the search radius or check the patient's location.</p>
          </div>
        )}

        {/* Initial state (before first search) */}
        {!loading && !error && !data && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <div className="w-16 h-16 rounded-2xl bg-[#f4ead8] border border-[#ddd0b6] flex items-center justify-center mb-5">
              <svg className="w-8 h-8 text-[#9b8768]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
                <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
              </svg>
            </div>
            <p className="font-bold text-[#271a0c] text-sm">Find medical facilities near the patient</p>
            <p className="text-[11px] text-[#9b8768] mt-1 max-w-sm">
              Uses the patient's live GPS coordinates from the CSV simulation.
              Results are ranked by proximity, specialization match, and Google ratings.
            </p>
            <button
              onClick={doFetch}
              className="mt-5 flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[#1a6b58] text-white text-sm font-bold hover:bg-[#155a49] transition-colors"
            >
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
              </svg>
              Search Now
            </button>
          </div>
        )}

        {/* Footer attribution */}
        {data && (
          <div className="flex items-center justify-between text-[10px] text-[#9b8768] pt-2 border-t border-[#ebe1ce]">
            <span>
              Location data © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer" className="underline hover:text-[#6b5438]">OpenStreetMap</a> contributors
            </span>
            <span>
              {data.serp_enriched ? 'Ratings via Google Maps · SerpAPI' : 'Add SERP_API_KEY to enable live ratings'}
              {lastFetch && ` · Updated ${lastFetch.toLocaleTimeString()}`}
            </span>
          </div>
        )}

      </div>
    </SentinelLayout>
  )
}
