/**
 * SENTINEL Backend API helpers.
 * All paths are relative — Vite proxies /api/* → http://localhost:8000
 */

const BASE = "";

// Matches the _serialize() output in backend/app/api/routes/audit.py
export interface AuditEntry {
  id: number;
  patient_id: string;
  session_id: string;
  reading_id: string;
  escalated_at: string;
  final_score: number;
  shal_band: string;
  hard_override_active: boolean;
  hard_override_type: string | null;
  decision_source: string;
  reasoning_summary: string | null;
  llm_thinking_chain: string | null;
  differential_diagnoses: Array<{ dx: string; probability: number; evidence: string }> | null;
  confidence: number | null;
  ems_dispatched: boolean;
  sms_sent: boolean;
  email_sent: boolean;
  fcm_sent: boolean;
  appointment_booked: boolean;
  ems_response_code: number | null;
  appointment_id: string | null;
  actions_latency_ms: number | null;
  vitals_snapshot: Record<string, number | null>;
  syndromes_fired: string[];
  trends_fired: string[];
  fall_event_type: string | null;
}

export interface AuditListResponse {
  count: number;
  entries: AuditEntry[];
}

// Matches the /health endpoint in backend/app/main.py
export interface HealthResponse {
  status: string;
  redis: string;
  isolation_forest: string;
  claude_api: string;
  gemini_api: string;
  database: string;
  twilio: string;
  sendgrid: string;
  calendly: string;
  serp_api: string;
  ems: string;
}

function parseJsonField<T>(value: unknown, fallback: T): T {
  if (value == null) return fallback;
  if (typeof value === "string") {
    try { return JSON.parse(value) as T; } catch { return fallback; }
  }
  return value as T;
}

export async function fetchAuditLog(limit = 50): Promise<AuditListResponse> {
  const res = await fetch(`${BASE}/api/v1/audit?limit=${limit}`);
  if (!res.ok) throw new Error(`Audit fetch failed: ${res.status}`);
  const data = await res.json();
  // vitals_snapshot, syndromes_fired, trends_fired, differential_diagnoses are
  // stored as JSON strings in the DB and returned as raw strings by the API.
  data.entries = data.entries.map((e: AuditEntry) => ({
    ...e,
    vitals_snapshot: parseJsonField(e.vitals_snapshot, {}),
    syndromes_fired: parseJsonField(e.syndromes_fired, []),
    trends_fired: parseJsonField(e.trends_fired, []),
    differential_diagnoses: parseJsonField(e.differential_diagnoses, null),
  }));
  return data as AuditListResponse;
}

export async function fetchPatientLatest(patientId: string): Promise<AuditListResponse> {
  const res = await fetch(`${BASE}/api/v1/audit/patient/${patientId}/latest`);
  if (!res.ok) throw new Error(`Patient audit fetch failed: ${res.status}`);
  const data = await res.json();
  data.entries = data.entries.map((e: AuditEntry) => ({
    ...e,
    vitals_snapshot: parseJsonField(e.vitals_snapshot, {}),
    syndromes_fired: parseJsonField(e.syndromes_fired, []),
    trends_fired: parseJsonField(e.trends_fired, []),
    differential_diagnoses: parseJsonField(e.differential_diagnoses, null),
  }));
  return data as AuditListResponse;
}

export async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch(`${BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export interface SimulatorStatus {
  patient_id: string;
  ticks_sent: number;
  elapsed_seconds: number;
  current_row_index: number;
  total_rows: number;
  is_running: boolean;
}

export async function startSimulator(patientId: string, csvFile: string, intervalSeconds = 0.5): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/simulator/start`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      patient_id: patientId,
      csv_file: csvFile,
      interval_seconds: intervalSeconds,
      loop: true,
    }),
  });
  if (!res.ok) throw new Error(`Simulator start failed: ${res.status} ${await res.text()}`);
}

export async function stopSimulator(patientId: string): Promise<void> {
  await fetch(`${BASE}/api/v1/simulator/stop`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ patient_id: patientId }),
  });
}

export async function fetchSimulatorStatus(patientId: string): Promise<SimulatorStatus> {
  const res = await fetch(`${BASE}/api/v1/simulator/status/${patientId}`);
  if (!res.ok) throw new Error(`Simulator status: ${res.status}`);
  return res.json();
}

// ── Settings / Contacts ────────────────────────────────────────────────────────

export interface EmergencyContacts {
  numbers: string[];
  emails: string[];
}

export async function fetchContacts(): Promise<EmergencyContacts> {
  const res = await fetch(`${BASE}/api/v1/settings/contacts`);
  if (!res.ok) throw new Error(`Contacts fetch failed: ${res.status}`);
  return res.json();
}

export async function addContactNumber(value: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/settings/contacts/number`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(`Add number failed: ${res.status}`);
}

export async function removeContactNumber(value: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/settings/contacts/number`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(`Remove number failed: ${res.status}`);
}

export async function addContactEmail(value: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/settings/contacts/email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(`Add email failed: ${res.status}`);
}

export async function removeContactEmail(value: string): Promise<void> {
  const res = await fetch(`${BASE}/api/v1/settings/contacts/email`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  if (!res.ok) throw new Error(`Remove email failed: ${res.status}`);
}

export async function sendTestSms(toNumber: string, message?: string): Promise<{ status: string; detail?: string }> {
  const res = await fetch(`${BASE}/api/v1/settings/test-sms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_number: toNumber, message }),
  });
  return res.json();
}

export async function sendTestEmail(toEmail: string, subject?: string, message?: string): Promise<{ status: string; detail?: string }> {
  const res = await fetch(`${BASE}/api/v1/settings/test-email`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to_email: toEmail, subject, message }),
  });
  return res.json();
}

export interface BookAppointmentRequest {
  patient_id: string;
  patient_name: string;
  patient_email: string;
  reason: string;
  notes?: string;
  event_type_uri?: string;  // Calendly event type URI
}

export interface BookAppointmentResponse {
  status: string;
  booking_url?: string;  // Calendly single-use scheduling link
  booking_id?: string;
  start?: string;
  patient?: string;
  detail?: string;
}

export async function bookAppointment(req: BookAppointmentRequest): Promise<BookAppointmentResponse> {
  const res = await fetch(`${BASE}/api/v1/settings/book-appointment`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return res.json();
}

// ── Latest vitals (real-time from CSV via Redis cache) ────────────────────────

export interface LatestVitals {
  patient_id: string;
  session_id: string;
  timestamp: string;
  heart_rate: number | null;
  respiratory_rate: number | null;
  spo2: number | null;
  ecg_rhythm: string | null;
  ecg_st_deviation_mm: number | null;
  ecg_qtc_ms: number | null;
  body_temperature: number | null;
  sleep_efficiency: number | null;
  deep_sleep_pct: number | null;
  rem_pct: number | null;
  hrv_ms: number | null;
  stress_score: number | null;
  fall_event: string;
  steps_per_hour: number | null;
  activity_context: string | null;
  age: number | null;
  gender: string | null;
  weight_kg: number | null;
  has_chronic_condition: boolean | null;
  latitude: number | null;
  longitude: number | null;
  location_stale: boolean;
  source: string;
  signal_quality: number | null;
}

export async function fetchLatestVitals(patientId: string): Promise<LatestVitals> {
  const res = await fetch(`${BASE}/api/v1/vitals/latest/${patientId}`);
  if (!res.ok) throw new Error(`Latest vitals: ${res.status}`);
  return res.json();
}

// ── Calendly event types ───────────────────────────────────────────────────────

export interface CalEventType {
  uri: string;
  name: string;
  duration: number;
  slug: string;
  color: string;
}

export async function fetchCalEventTypes(): Promise<{ status: string; event_types: CalEventType[]; detail?: string }> {
  const res = await fetch(`${BASE}/api/v1/settings/calendly-event-types`);
  if (!res.ok) return { status: "error", event_types: [], detail: `HTTP ${res.status}` };
  return res.json();
}

// ── Nearby Doctors (OSM + SerpAPI) ────────────────────────────────────────────

export interface ScoreBreakdown {
  proximity: number;
  rating: number;
  specialization: number;
  completeness: number;
}

export interface NearbyDoctor {
  name: string;
  amenity_type: string;
  amenity_label: string;
  specialization: string;
  address: string;
  phone: string;
  website: string;
  opening_hours: string;
  wheelchair_accessible: boolean;
  lat: number;
  lng: number;
  osm_id: string;
  osm_url: string;
  google_maps_url: string;
  distance_km: number;
  rating: number | null;
  reviews_count: number | null;
  score: number;
  score_breakdown: ScoreBreakdown;
}

export interface NearbyDoctorsResponse {
  patient_location: { lat: number; lng: number };
  radius_m: number;
  syndromes: string[];
  relevant_specialties: string[];
  total_found: number;
  ranked_doctors: NearbyDoctor[];
  fetch_time_ms: number;
  source: string;
  serp_enriched: boolean;
  osm_cache_hit: boolean;
}

export async function fetchNearbyDoctors(params: {
  patient_id?: string;
  lat?: number;
  lng?: number;
  radius_m?: number;
  syndromes?: string[];
  limit?: number;
}): Promise<NearbyDoctorsResponse> {
  const p = new URLSearchParams();
  if (params.patient_id)       p.set("patient_id", params.patient_id);
  if (params.lat != null)      p.set("lat", String(params.lat));
  if (params.lng != null)      p.set("lng", String(params.lng));
  if (params.radius_m != null) p.set("radius_m", String(params.radius_m));
  if (params.syndromes?.length) p.set("syndromes", params.syndromes.join(","));
  if (params.limit != null)    p.set("limit", String(params.limit));
  const res = await fetch(`${BASE}/api/v1/doctors/nearby?${p}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error ?? `Nearby doctors: ${res.status}`);
  }
  return res.json();
}
