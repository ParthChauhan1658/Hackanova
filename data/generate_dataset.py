import numpy as np
import pandas as pd
import uuid
from datetime import datetime, timedelta

np.random.seed(42)

# ── Patient profiles ──────────────────────────────────────────────────────────
patients = [
    {"patient_id": "P01", "age": 28, "gender": "M", "weight_kg": 72.0, "has_chronic_condition": False, "scenario": "NORMAL",                "lat": 19.0760, "lon": 72.8777},
    {"patient_id": "P02", "age": 45, "gender": "F", "weight_kg": 65.0, "has_chronic_condition": False, "scenario": "NORMAL",                "lat": 28.6139, "lon": 77.2090},
    {"patient_id": "P03", "age": 62, "gender": "M", "weight_kg": 80.0, "has_chronic_condition": True,  "scenario": "ELEVATED_RISK",        "lat": 12.9716, "lon": 77.5946},
    {"patient_id": "P04", "age": 55, "gender": "F", "weight_kg": 70.0, "has_chronic_condition": True,  "scenario": "ELEVATED_RISK",        "lat": 22.5726, "lon": 88.3639},
    {"patient_id": "P05", "age": 70, "gender": "M", "weight_kg": 68.0, "has_chronic_condition": True,  "scenario": "CRITICAL_VITALS_EVENT","lat": 17.3850, "lon": 78.4867},
    {"patient_id": "P06", "age": 38, "gender": "F", "weight_kg": 58.0, "has_chronic_condition": False, "scenario": "CRITICAL_VITALS_EVENT","lat": 23.0225, "lon": 72.5714},
    {"patient_id": "P07", "age": 75, "gender": "M", "weight_kg": 74.0, "has_chronic_condition": True,  "scenario": "CRITICAL_VITALS_EVENT","lat": 13.0827, "lon": 80.2707},
    {"patient_id": "P08", "age": 80, "gender": "F", "weight_kg": 55.0, "has_chronic_condition": True,  "scenario": "FALL_EVENT",           "lat": 18.5204, "lon": 73.8567},
    {"patient_id": "P09", "age": 67, "gender": "M", "weight_kg": 77.0, "has_chronic_condition": True,  "scenario": "FALL_EVENT",           "lat": 26.8467, "lon": 80.9462},
    {"patient_id": "P10", "age": 52, "gender": "F", "weight_kg": 63.0, "has_chronic_condition": False, "scenario": "ELEVATED_RISK",        "lat": 21.1702, "lon": 72.8311},
]

# ── Helpers ───────────────────────────────────────────────────────────────────
def clip(val, lo, hi):
    return float(max(lo, min(hi, val)))

def rn(mean, std, lo, hi):
    return clip(np.random.normal(mean, std), lo, hi)

def activity_from_steps(steps):
    if steps > 600: return "VIGOROUS"
    if steps > 400: return "MODERATE"
    if steps > 100: return "LIGHT"
    return "SEDENTARY"

# ── Row builder ───────────────────────────────────────────────────────────────
def build_row(p, seq, base_time, hr, rr, spo2, ecg_rhythm, st, qtc,
              temp, sleep_eff, deep_sleep, rem, hrv, stress,
              fall, steps, activity, sig_q):
    ts = base_time + timedelta(seconds=seq * 5)
    location_stale = fall == "CONFIRMED_FALL" and seq >= 62
    return {
        "reading_id":           str(uuid.uuid4()),
        "patient_id":           p["patient_id"],
        "session_id":           f"SES-{p['patient_id']}-001",
        "timestamp":            ts.strftime("%Y-%m-%dT%H:%M:%S"),
        "heart_rate_bpm":       round(hr, 1),
        "respiratory_rate":     round(rr, 1),
        "spo2_percent":         round(spo2, 1),
        "ecg_rhythm":           ecg_rhythm,
        "ecg_st_deviation_mm":  round(st, 2),
        "ecg_qtc_ms":           round(qtc, 1),
        "temperature_celsius":  round(temp, 1),
        "sleep_efficiency_pct": round(sleep_eff, 1),
        "deep_sleep_pct":       round(deep_sleep, 1),
        "rem_pct":              round(rem, 1),
        "hrv_rmssd_ms":         round(hrv, 1),
        "stress_score":         round(stress, 1),
        "fall_event":           fall,
        "steps_per_hour":       int(clip(steps, 0, 1200)),
        "activity_level":       activity,
        "age":                  p["age"],
        "gender":               p["gender"],
        "weight_kg":            p["weight_kg"],
        "has_chronic_condition":p["has_chronic_condition"],
        "latitude":             round(p["lat"] + np.random.normal(0, 0.0002), 6),
        "longitude":            round(p["lon"] + np.random.normal(0, 0.0002), 6),
        "location_stale":       location_stale,
        "source":               "synthetic_dataset",
        "signal_quality_pct":   round(clip(sig_q, 60, 100), 1),
    }

# ── Scenario generators ───────────────────────────────────────────────────────
def gen_normal(p, seq, base_time):
    hr       = rn(70,  7,   45,  110)
    rr       = rn(14,  2,   10,   22)
    spo2     = rn(98,  0.8, 95,  100)
    ecg      = "NORMAL_SINUS" if np.random.random() > 0.05 else "PVC"
    st       = rn(0.1, 0.08, -0.3, 0.4)
    qtc      = rn(400, 18,  360,  440)
    temp     = rn(36.6,0.2,  36.0, 37.3)
    sl_eff   = rn(88,  4,   72,   98)
    deep     = rn(20,  3,   10,   30)
    rem      = rn(22,  3,   14,   30)
    hrv      = rn(50,  8,   28,   80)
    stress   = rn(20,  5,    5,   40)
    steps    = rn(300, 80,  50,  600)
    act      = activity_from_steps(steps)
    sig_q    = rn(96,  2,   88,  100)
    return build_row(p, seq, base_time, hr, rr, spo2, ecg, st, qtc,
                     temp, sl_eff, deep, rem, hrv, stress,
                     "NONE", steps, act, sig_q)

def gen_elevated(p, seq, base_time):
    if   seq <= 20: phase = 1
    elif seq <= 40: phase = 2
    elif seq <= 70: phase = 3
    else:           phase = 4

    hr_m    = {1:85,  2:98,  3:108, 4:95  }[phase]
    spo2_m  = {1:95,  2:94,  3:93,  4:94  }[phase]
    stress_m= {1:42,  2:55,  3:64,  4:50  }[phase]
    hrv_m   = {1:35,  2:30,  3:26,  4:30  }[phase]
    rr_m    = {1:17,  2:20,  3:22,  4:19  }[phase]

    if phase in (1, 4):
        ecg = "NORMAL_SINUS"
    elif phase == 2:
        ecg = "TACHYCARDIA" if np.random.random() < 0.20 else "NORMAL_SINUS"
    else:
        ecg = "TACHYCARDIA"

    hr     = rn(hr_m,    5, 65, 145)
    rr     = rn(rr_m,    2, 12,  35)
    spo2   = rn(spo2_m,  1, 88, 100)
    st     = rn(0.1,  0.08, -0.3, 0.5)
    qtc    = rn(410,    20, 360,  460)
    temp   = rn(36.8,  0.2, 36.2, 37.5)
    sl_eff = rn(80,      5,  65,   92)
    deep   = rn(17,      3,  10,   26)
    rem    = rn(20,      3,  13,   28)
    hrv    = rn(hrv_m,   4,  18,   55)
    stress = rn(stress_m,5,  25,   80)
    steps  = rn(200,    60,  30,  500)
    act    = activity_from_steps(steps)
    sig_q  = rn(93,      3,  80,  100)
    return build_row(p, seq, base_time, hr, rr, spo2, ecg, st, qtc,
                     temp, sl_eff, deep, rem, hrv, stress,
                     "NONE", steps, act, sig_q)

def gen_critical(p, seq, base_time):
    if   seq <= 20: phase = 1
    elif seq <= 40: phase = 2
    elif seq <= 70: phase = 3
    else:           phase = 4

    hr_m    = {1:82,  2:110, 3:145, 4:138}[phase]
    spo2_m  = {1:95,  2:92,  3:86,  4:87 }[phase]
    temp_m  = {1:36.8,2:37.5,3:38.9,4:38.7}[phase]
    hrv_m   = {1:30,  2:24,  3:18,  4:19 }[phase]
    rr_m    = {1:18,  2:24,  3:28,  4:27 }[phase]
    stress_m= {1:35,  2:55,  3:75,  4:72 }[phase]

    if phase == 1:
        ecg = "NORMAL_SINUS"
    elif phase == 2:
        ecg = "TACHYCARDIA"
    elif phase == 3:
        if p["patient_id"] == "P07":
            ecg = "VT" if np.random.random() < 0.50 else "AFIB"
        else:
            ecg = "TACHYCARDIA" if np.random.random() < 0.60 else "AFIB"
    else:
        ecg = "TACHYCARDIA" if p["patient_id"] != "P07" else "AFIB"

    hr     = rn(hr_m,    5,  40, 180)
    rr     = rn(rr_m,    3,  10,  45)
    spo2   = rn(spo2_m,  2,  72, 100)
    st_m   = 0.2 if phase >= 3 and p["patient_id"] == "P07" else 0.1
    st     = rn(st_m, 0.1, -0.5, 1.5)
    qtc    = rn(430,    25, 370,  530)
    temp   = rn(temp_m, 0.2, 35.5, 41.5)
    sl_eff = rn(70,      5,  55,   85)
    deep   = rn(14,      3,   8,   22)
    rem    = rn(16,      3,  10,   24)
    hrv    = rn(hrv_m,   3,   8,   45)
    stress = rn(stress_m,5,  20,   98)
    steps  = rn(50,     30,   0,  200)
    act    = "SEDENTARY" if phase >= 2 else activity_from_steps(steps)
    sig_q  = rn(88,      4,  65,  100)
    return build_row(p, seq, base_time, hr, rr, spo2, ecg, st, qtc,
                     temp, sl_eff, deep, rem, hrv, stress,
                     "NONE", steps, act, sig_q)

def gen_fall(p, seq, base_time):
    if seq <= 30:
        # Normal pre-fall
        hr     = rn(72,  7,  50, 100)
        rr     = rn(14,  2,  10,  20)
        spo2   = rn(97,  1,  93, 100)
        ecg    = "NORMAL_SINUS"
        st     = rn(0.1, 0.08, -0.2, 0.3)
        qtc    = rn(405, 18, 365, 445)
        temp   = rn(36.6,0.2, 36.0, 37.2)
        sl_eff = rn(84,  4,  70,  96)
        deep   = rn(19,  3,  11,  28)
        rem    = rn(21,  3,  13,  29)
        hrv    = rn(42,  7,  22,  68)
        stress = rn(22,  5,   8,  40)
        steps  = rn(250, 80, 30, 500)
        act    = activity_from_steps(steps)
        fall   = "NONE"
        sig_q  = rn(95,  2,  86, 100)
    elif seq == 31:
        # Fall impact
        hr     = rn(88,  5,  70, 110)
        rr     = rn(18,  2,  13,  25)
        spo2   = rn(95,  1,  90, 100)
        ecg    = "TACHYCARDIA"
        st     = rn(0.1, 0.1, -0.2, 0.4)
        qtc    = rn(410, 20, 370, 455)
        temp   = rn(36.5,0.2, 36.0, 37.2)
        sl_eff = rn(84,  4,  70,  96)
        deep   = rn(19,  3,  11,  28)
        rem    = rn(21,  3,  13,  29)
        hrv    = rn(35,  5,  18,  55)
        stress = rn(55,  6,  38,  72)
        steps  = 0
        act    = "SEDENTARY"
        fall   = "POSSIBLE_FALL"
        sig_q  = rn(88,  4,  72,  98)
    elif seq <= 62:
        # Confirmed fall — post-impact
        hr     = rn(55,  4,  38,  72)
        rr     = rn(16,  2,  10,  22)
        spo2   = rn(91,  2,  82,  96)
        ecg    = "BRADYCARDIA" if np.random.random() < 0.4 else "NORMAL_SINUS"
        st     = rn(0.1, 0.08, -0.2, 0.3)
        qtc    = rn(415, 20, 370, 460)
        temp   = rn(36.4,0.2, 35.8, 37.0)
        sl_eff = rn(84,  4,  70,  96)
        deep   = rn(19,  3,  11,  28)
        rem    = rn(21,  3,  13,  29)
        hrv    = rn(38,  5,  20,  58)
        stress = rn(62,  6,  44,  80)
        steps  = 0
        act    = "SEDENTARY"
        fall   = "CONFIRMED_FALL"
        sig_q  = rn(82,  5,  62,  94)
    else:
        # Sustained unresponsive
        hr     = rn(52,  4,  35,  68)
        rr     = rn(14,  2,   8,  20)
        spo2   = rn(90,  2,  80,  95)
        ecg    = "BRADYCARDIA" if np.random.random() < 0.5 else "NORMAL_SINUS"
        st     = rn(0.1, 0.08, -0.2, 0.3)
        qtc    = rn(420, 22, 375, 465)
        temp   = rn(36.2,0.2, 35.6, 36.9)
        sl_eff = rn(84,  4,  70,  96)
        deep   = rn(19,  3,  11,  28)
        rem    = rn(21,  3,  13,  29)
        hrv    = rn(35,  5,  18,  54)
        stress = rn(65,  6,  46,  82)
        steps  = 0
        act    = "SEDENTARY"
        fall   = "CONFIRMED_FALL"
        sig_q  = rn(80,  5,  60,  92)

    return build_row(p, seq, base_time, hr, rr, spo2, ecg, st, qtc,
                     temp, sl_eff, deep, rem, hrv, stress,
                     fall, steps, act, sig_q)

# ── Main generation loop ──────────────────────────────────────────────────────
rows = []
base_time = datetime(2025, 1, 15, 8, 0, 0)

for p in patients:
    for seq in range(1, 101):
        if   p["scenario"] == "NORMAL":                row = gen_normal(p, seq, base_time)
        elif p["scenario"] == "ELEVATED_RISK":         row = gen_elevated(p, seq, base_time)
        elif p["scenario"] == "CRITICAL_VITALS_EVENT": row = gen_critical(p, seq, base_time)
        elif p["scenario"] == "FALL_EVENT":            row = gen_fall(p, seq, base_time)
        rows.append(row)

df = pd.DataFrame(rows)

# ── Save ──────────────────────────────────────────────────────────────────────
df.to_csv("D:/Hackanova/data/dataset.csv", index=False)

# ── Summary ───────────────────────────────────────────────────────────────────
print(f"\n{'='*55}")
print(f"  Dataset generated: D:/Hackanova/data/dataset.csv")
print(f"{'='*55}")
print(f"  Total rows       : {len(df)}")
print(f"  Total columns    : {len(df.columns)}")
print(f"\n  Rows per scenario:")
scenario_map = {
    "P01":"NORMAL","P02":"NORMAL",
    "P03":"ELEVATED_RISK","P04":"ELEVATED_RISK","P10":"ELEVATED_RISK",
    "P05":"CRITICAL_VITALS_EVENT","P06":"CRITICAL_VITALS_EVENT","P07":"CRITICAL_VITALS_EVENT",
    "P08":"FALL_EVENT","P09":"FALL_EVENT"
}
df["scenario"] = df["patient_id"].map(scenario_map)
for s, cnt in df["scenario"].value_counts().items():
    print(f"    {s:<28}: {cnt}")

print(f"\n  fall_event distribution:")
for v, c in df["fall_event"].value_counts().items():
    print(f"    {v:<20}: {c}")

print(f"\n  ecg_rhythm distribution:")
for v, c in df["ecg_rhythm"].value_counts().items():
    print(f"    {v:<20}: {c}")

print(f"\n  Columns ({len(df.columns)}):")
print(f"    {', '.join(df.columns.tolist())}")
print(f"\n  Sample row (P06, seq 50 — critical peak):")
sample = df[(df["patient_id"]=="P06")].iloc[49]
for col in ["heart_rate_bpm","respiratory_rate","spo2_percent","ecg_rhythm",
            "temperature_celsius","hrv_rmssd_ms","stress_score","fall_event","signal_quality_pct"]:
    print(f"    {col:<25}: {sample[col]}")
print(f"{'='*55}\n")
