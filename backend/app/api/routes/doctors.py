"""
Nearby doctors route — OpenStreetMap Overpass API + optional SerpAPI ratings.
GET /api/v1/doctors/nearby
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)
router = APIRouter()

_SERP_API_KEY_ENV = "SERP_API_KEY"
_SERP_BASE_URL    = "https://serpapi.com/search"
_OVERPASS_URL     = "https://overpass-api.de/api/interpreter"

# Syndrome → relevant medical specializations (for relevance scoring)
SYNDROME_SPECIALTY_MAP: dict[str, list[str]] = {
    "SIRS_EARLY_SEPSIS":   ["internal_medicine", "intensive_care", "emergency", "general"],
    "RESPIRATORY_FAILURE": ["pulmonology", "intensive_care", "emergency", "internal_medicine"],
    "HYPOXIC_EPISODE":     ["pulmonology", "cardiology", "emergency", "intensive_care"],
    "DISTRIBUTIVE_SHOCK":  ["intensive_care", "cardiology", "internal_medicine", "emergency"],
    "AUTONOMIC_COLLAPSE":  ["neurology", "cardiology", "intensive_care", "internal_medicine"],
    "MULTI_SYSTEM_STRESS": ["internal_medicine", "endocrinology", "intensive_care", "general"],
    "ECG_VT_VF":           ["cardiology", "emergency", "intensive_care", "internal_medicine"],
    "ECG_STEMI":           ["cardiology", "emergency", "intensive_care", "internal_medicine"],
    "FALL_UNRESPONSIVE":   ["neurology", "orthopaedics", "emergency", "traumatology"],
    "TEMP_HYPERPYREXIA":   ["infectious_diseases", "internal_medicine", "emergency", "intensive_care"],
}

_AMENITY_LABELS: dict[str, str] = {
    "hospital": "Hospital",
    "clinic":   "Clinic",
    "doctors":  "Doctor",
    "doctor":   "Doctor",
    "pharmacy": "Pharmacy",
}


def _haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    rl = [math.radians(x) for x in (lat1, lng1, lat2, lng2)]
    dlat, dlon = rl[2] - rl[0], rl[3] - rl[1]
    a = math.sin(dlat / 2) ** 2 + math.cos(rl[0]) * math.cos(rl[2]) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _score(doc: dict, specialties: list[str], max_r_km: float) -> float:
    """Composite score: proximity 40% + rating 20% + specialization 30% + completeness 10%."""
    # Proximity (40%)
    prox = max(0.0, 1.0 - doc["distance_km"] / max_r_km) * 40.0

    # Rating (20%) — from SERP if available
    rating  = doc.get("rating") or 0.0
    rat_s   = (rating / 5.0) * 20.0

    # Specialization match (30%)
    spec_text = (doc.get("specialization", "") + " " + doc.get("amenity_type", "")).lower()
    spec_s    = 3.0  # baseline: any healthcare node
    for i, sp in enumerate(specialties):
        if sp.lower() in spec_text:
            spec_s = max(spec_s, [30.0, 18.0, 9.0, 9.0][min(i, 3)])

    # Data completeness (10%)
    comp = sum([
        2.5 if doc.get("phone") else 0.0,
        2.5 if doc.get("website") else 0.0,
        2.5 if doc.get("opening_hours") != "Hours not listed" else 0.0,
        2.5 if doc.get("specialization") else 0.0,
    ])

    total = prox + rat_s + spec_s + comp
    doc["score_breakdown"] = {
        "proximity":      round(prox, 1),
        "rating":         round(rat_s, 1),
        "specialization": round(spec_s, 1),
        "completeness":   round(comp, 1),
    }
    return round(total, 1)


async def _fetch_serp_rating(
    http: httpx.AsyncClient, name: str, lat: float, lng: float, api_key: str
) -> Optional[float]:
    """Query SerpAPI Google Maps for the first-match rating of a healthcare facility."""
    try:
        resp = await http.get(
            _SERP_BASE_URL,
            params={
                "engine":  "google_maps",
                "q":       name,
                "ll":      f"@{lat},{lng},15z",
                "type":    "search",
                "api_key": api_key,
            },
            timeout=8.0,
        )
        if resp.status_code != 200:
            return None
        results = resp.json().get("local_results", [])
        return float(results[0]["rating"]) if results and results[0].get("rating") else None
    except Exception:
        return None


@router.get("/api/v1/doctors/nearby")
async def nearby_doctors(
    request:    Request,
    patient_id: str            = Query("P01"),
    lat:        Optional[float] = Query(None),
    lng:        Optional[float] = Query(None),
    radius_m:   int             = Query(5000, ge=500, le=50000),
    syndromes:  Optional[str]   = Query(None),   # comma-separated syndrome keys
    limit:      int             = Query(10, ge=1, le=25),
):
    """
    Returns ranked nearby healthcare facilities for a patient.
    Location resolved from Redis vitals cache when lat/lng not supplied.
    Optionally enriches with live Google ratings via SerpAPI (requires SERP_API_KEY).
    """
    t0 = time.time()

    # ── 1. Resolve patient location ──────────────────────────────────────────
    if lat is None or lng is None:
        try:
            redis = request.app.state.redis_client
            rc    = await redis.get_client()
            raw   = await rc.get(f"sentinel:vitals:{patient_id}:latest")
            if raw:
                vdata = json.loads(raw)
                lat   = vdata.get("latitude")  or lat
                lng   = vdata.get("longitude") or lng
        except Exception as exc:
            logger.warning("Redis vitals lookup failed: %s", exc)

    if lat is None or lng is None:
        return JSONResponse(
            status_code=422,
            content={
                "error": "Patient location unavailable. "
                         "Ensure the simulator is running and CSV has lat/lng data, "
                         "or supply ?lat=&lng= query params.",
            },
        )

    # ── 2. Resolve syndromes → specializations ───────────────────────────────
    syndrome_list: list[str] = [s.strip() for s in (syndromes or "").split(",") if s.strip()]
    relevant_specialties: list[str] = []
    for s in syndrome_list:
        for sp in SYNDROME_SPECIALTY_MAP.get(s, []):
            if sp not in relevant_specialties:
                relevant_specialties.append(sp)

    # ── 3. OSM Overpass query (Redis-cached 5 min) ───────────────────────────
    cache_key  = f"sentinel:osm:{round(lat, 3)}:{round(lng, 3)}:{radius_m}"
    elements: list[dict] = []
    osm_cache_hit = False

    try:
        rc     = await request.app.state.redis_client.get_client()
        cached = await rc.get(cache_key)
        if cached:
            elements      = json.loads(cached)
            osm_cache_hit = True
    except Exception:
        pass

    if not osm_cache_hit:
        overpass_query = f"""
        [out:json][timeout:25];
        (
          node["amenity"="doctors"](around:{radius_m},{lat},{lng});
          node["amenity"="clinic"](around:{radius_m},{lat},{lng});
          node["amenity"="hospital"](around:{radius_m},{lat},{lng});
          node["healthcare"="doctor"](around:{radius_m},{lat},{lng});
          node["amenity"="pharmacy"](around:{radius_m},{lat},{lng});
        );
        out body;
        """
        try:
            async with httpx.AsyncClient(timeout=30.0) as http:
                osm_resp = await http.post(_OVERPASS_URL, data={"data": overpass_query})
                osm_resp.raise_for_status()
                elements = osm_resp.json().get("elements", [])
            # Cache raw elements
            try:
                rc = await request.app.state.redis_client.get_client()
                await rc.setex(cache_key, 300, json.dumps(elements))
            except Exception:
                pass
        except Exception as exc:
            logger.warning("Overpass API error: %s", exc)
            return JSONResponse(
                status_code=502,
                content={"error": f"OpenStreetMap Overpass query failed: {exc}", "total_found": 0},
            )

    # ── 4. Build doctor objects ──────────────────────────────────────────────
    max_r_km = radius_m / 1000.0
    doctors: list[dict] = []

    for el in elements:
        tags = el.get("tags", {})
        if not tags:
            continue
        dlat = el.get("lat")
        dlng = el.get("lon")
        if dlat is None or dlng is None:
            continue

        name         = tags.get("name") or tags.get("operator") or "Unknown Clinic"
        amenity_type = tags.get("amenity") or tags.get("healthcare") or "unknown"

        if tags.get("addr:street") and tags.get("addr:housenumber"):
            address = f"{tags['addr:housenumber']} {tags['addr:street']}"
        else:
            address = tags.get("addr:full") or tags.get("addr:suburb") or ""

        doctors.append({
            "name":                 name,
            "amenity_type":         amenity_type,
            "amenity_label":        _AMENITY_LABELS.get(amenity_type, amenity_type.title()),
            "specialization":       tags.get("healthcare:speciality", ""),
            "address":              address,
            "phone":                tags.get("phone") or tags.get("contact:phone") or "",
            "website":              tags.get("website") or tags.get("contact:website") or "",
            "opening_hours":        tags.get("opening_hours") or "Hours not listed",
            "wheelchair_accessible": tags.get("wheelchair") == "yes",
            "lat":                  dlat,
            "lng":                  dlng,
            "osm_id":               str(el.get("id", "")),
            "osm_url":              f"https://www.openstreetmap.org/node/{el.get('id')}",
            "google_maps_url":      f"https://www.google.com/maps?q={dlat},{dlng}",
            "distance_km":          round(_haversine(lat, lng, dlat, dlng), 2),
            "rating":               None,
            "reviews_count":        None,
        })

    # ── 5. SERP rating enrichment (optional, parallel, Redis-cached 1 hr) ────
    serp_key      = os.getenv(_SERP_API_KEY_ENV, "")
    serp_enriched = False

    if serp_key and doctors:
        # Only enrich the closest 12 nodes (API cost control)
        by_dist = sorted(doctors, key=lambda d: d["distance_km"])[:12]
        osm_ids = [d["osm_id"] for d in by_dist]

        # Bulk-read SERP cache
        try:
            rc     = await request.app.state.redis_client.get_client()
            pipe   = rc.pipeline()
            for oid in osm_ids:
                pipe.get(f"sentinel:serp:{oid}")
            cached_ratings = await pipe.execute()
        except Exception:
            cached_ratings = [None] * len(by_dist)

        need_fetch: list[dict] = []
        for doc, cr in zip(by_dist, cached_ratings):
            if cr is not None:
                val = cr.decode() if isinstance(cr, bytes) else str(cr)
                doc["rating"] = float(val) if val != "null" else None
            else:
                need_fetch.append(doc)

        if need_fetch:
            async with httpx.AsyncClient() as http:
                raw_ratings = await asyncio.gather(
                    *[_fetch_serp_rating(http, d["name"], d["lat"], d["lng"], serp_key)
                      for d in need_fetch],
                    return_exceptions=True,
                )
            try:
                rc = await request.app.state.redis_client.get_client()
                for doc, r in zip(need_fetch, raw_ratings):
                    if isinstance(r, (int, float)):
                        doc["rating"] = float(r)
                        await rc.setex(f"sentinel:serp:{doc['osm_id']}", 3600, str(r))
                    else:
                        doc["rating"] = None
                        await rc.setex(f"sentinel:serp:{doc['osm_id']}", 3600, "null")
            except Exception:
                pass

        serp_enriched = True

    # ── 6. Score, sort, return ───────────────────────────────────────────────
    for doc in doctors:
        doc["score"] = _score(doc, relevant_specialties, max_r_km)

    # Primary sort: rated facilities first (by rating descending), unrated last.
    # Secondary sort: composite score as tiebreaker within same rating tier.
    doctors.sort(
        key=lambda d: (d["rating"] is not None, d["rating"] or 0.0, d["score"]),
        reverse=True,
    )

    return {
        "patient_location":    {"lat": lat, "lng": lng},
        "radius_m":            radius_m,
        "syndromes":           syndrome_list,
        "relevant_specialties": relevant_specialties,
        "total_found":         len(doctors),
        "ranked_doctors":      doctors[:limit],
        "fetch_time_ms":       round((time.time() - t0) * 1000, 1),
        "source":              "openstreetmap",
        "serp_enriched":       serp_enriched,
        "osm_cache_hit":       osm_cache_hit,
    }
