import urllib.request
import json

url = "http://localhost:8080/doctors?lat=18.9388&lng=72.8354&radius_m=3000&syndromes=SIRS_EARLY_SEPSIS"
try:
    with urllib.request.urlopen(url) as response:
        data = json.loads(response.read().decode())
        print("TOTAL FOUND:", data.get("total_found"))
        print("SPECS:", data.get("relevant_specialties"))
        print("TOP 3:", json.dumps(data.get("ranked_doctors", [])[:3], indent=2))
except Exception as e:
    print("Error:", e)
