import asyncio
import json
import math
import sys
import time

import httpx

# Predefined Syndromes and their mapped specializations
SYNDROME_SPECIALTY_MAP = {
    "SIRS_EARLY_SEPSIS": ["internal_medicine", "intensive_care", "emergency", "general"],
    "RESPIRATORY_FAILURE": ["pulmonology", "intensive_care", "emergency", "internal_medicine"],
    "HYPOXIC_EPISODE": ["pulmonology", "cardiology", "emergency", "intensive_care"],
    "DISTRIBUTIVE_SHOCK": ["intensive_care", "cardiology", "internal_medicine", "emergency"],
    "AUTONOMIC_COLLAPSE": ["neurology", "cardiology", "intensive_care", "internal_medicine"],
    "MULTI_SYSTEM_STRESS": ["internal_medicine", "endocrinology", "intensive_care", "general"],
    "ECG_VT_VF": ["cardiology", "emergency", "intensive_care", "internal_medicine"],
    "ECG_STEMI": ["cardiology", "emergency", "intensive_care", "internal_medicine"],
    "FALL_UNRESPONSIVE": ["neurology", "orthopaedics", "emergency", "traumatology"],
    "TEMP_HYPERPYREXIA": ["infectious_diseases", "internal_medicine", "emergency", "intensive_care"]
}

def haversine(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0  # Earth radius in km
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lng1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lng2)

    dlon = lon2_rad - lon1_rad
    dlat = lat2_rad - lat1_rad

    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    distance = R * c
    return distance

def score_doctor(doctor: dict, relevant_specialties: list[str]) -> float:
    # 1. Proximity (40%)
    max_radius = 10.0
    distance_km = doctor.get("distance_km", 0.0)
    proximity = max(0.0, 1.0 - (distance_km / max_radius))
    proximity_score = proximity * 40.0

    # 2. Rating (20%) - OSM has no ratings, so 0 for all OSM results
    rating_score = 0.0 * 20.0

    # 3. Specialization match (30%)
    spec_score = 3.0 # Any other doctor type: 3 points
    
    doc_spec = (doctor.get("specialization", "") + " " + doctor.get("amenity_type", "")).lower()
    
    for i, spec in enumerate(relevant_specialties):
        if spec.lower() in doc_spec:
            if i == 0:
                spec_score = max(spec_score, 30.0)
            elif i == 1:
                spec_score = max(spec_score, 18.0)
            elif i == 2:
                spec_score = max(spec_score, 9.0)
            else:
                spec_score = max(spec_score, 9.0) # Assume any remaining matches are tertiary-level value

    # 4. Data completeness (10%)
    data_score = 0.0
    if doctor.get("phone"): data_score += 2.5
    if doctor.get("website"): data_score += 2.5
    if doctor.get("opening_hours") != "Hours not listed": data_score += 2.5
    if doctor.get("specialization"): data_score += 2.5
    
    total = proximity_score + rating_score + spec_score + data_score
    doctor["score_breakdown"] = {
        "proximity": round(proximity_score, 1),
        "specialization": round(spec_score, 1),
        "completeness": round(data_score, 1)
    }
    return round(total, 1)

async def find_and_rank_doctors(lat: float, lng: float, radius_m: int, syndromes: list[str]) -> dict:
    start_time = time.time()
    
    OVERPASS_URL = "https://overpass-api.de/api/interpreter"
    query = f"""
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
    
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(OVERPASS_URL, data={"data": query})
            response.raise_for_status()
            data = response.json()
        except Exception as e:
            return {"error": str(e), "source": "openstreetmap", "total_found": 0}
            
    elements = data.get("elements", [])
    
    # Calculate union of all specialties from all given syndromes, deduped
    relevant_specialties = []
    for s in syndromes:
        if s in SYNDROME_SPECIALTY_MAP:
            for spec in SYNDROME_SPECIALTY_MAP[s]:
                if spec not in relevant_specialties:
                    relevant_specialties.append(spec)
                    
    doctors = []
    for el in elements:
        tags = el.get("tags", {})
        if not tags: continue
        
        node_id = el.get("id")
        dlat = el.get("lat")
        dlng = el.get("lon")
        
        name = tags.get("name") or tags.get("operator") or "Unknown Clinic"
        amenity_type = tags.get("amenity") or tags.get("healthcare") or "unknown"
        specialization = tags.get("healthcare:speciality", "")
        
        if tags.get("addr:street") and tags.get("addr:housenumber"):
            address = f"{tags.get('addr:housenumber')} {tags.get('addr:street')}"
        else:
            address = tags.get("addr:full") or tags.get("addr:suburb") or "Address not listed"
            
        phone = tags.get("phone") or tags.get("contact:phone") or ""
        website = tags.get("website") or tags.get("contact:website") or ""
        opening_hours = tags.get("opening_hours") or "Hours not listed"
        wheelchair = tags.get("wheelchair") == "yes"
        
        distance_km = haversine(lat, lng, dlat, dlng)
        
        doc = {
            "name": name,
            "amenity_type": amenity_type,
            "specialization": specialization,
            "address": address,
            "phone": phone,
            "website": website,
            "opening_hours": opening_hours,
            "wheelchair_accessible": wheelchair,
            "lat": dlat,
            "lng": dlng,
            "osm_id": str(node_id),
            "osm_url": f"https://www.openstreetmap.org/node/{node_id}",
            "google_maps_url": f"https://www.google.com/maps?q={dlat},{dlng}",
            "distance_km": round(distance_km, 2),
            "rating": None
        }
        
        doc["score"] = score_doctor(doc, relevant_specialties)
        doctors.append(doc)
        
    doctors.sort(key=lambda x: x["score"], reverse=True)
    
    fetch_time_ms = round((time.time() - start_time) * 1000, 2)
    
    return {
        "patient_location": {"lat": lat, "lng": lng},
        "radius_m": radius_m,
        "syndromes": syndromes,
        "relevant_specialties": relevant_specialties,
        "total_found": len(doctors),
        "ranked_doctors": doctors[:10],
        "fetch_time_ms": fetch_time_ms,
        "source": "openstreetmap"
    }

if __name__ == "__main__":
    _lat = 18.9388
    _lng = 72.8354
    _radius = 5000
    _syndromes = ["SIRS_EARLY_SEPSIS"]
    
    args = sys.argv[1:]
    if len(args) >= 1: _lat = float(args[0])
    if len(args) >= 2: _lng = float(args[1])
    if len(args) >= 3: _radius = int(args[2])
    if len(args) >= 4: _syndromes = args[3:]
        
    result = asyncio.run(find_and_rank_doctors(_lat, _lng, _radius, _syndromes))
    print(json.dumps(result, indent=2))
