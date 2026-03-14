## Doctor Finder — OSM Experiment
  
### Setup
pip install -r requirements.txt

### Run backend
python server.py
Then open http://localhost:8080 in browser

### Run fetch script only (no UI)
python fetch_doctors.py
python fetch_doctors.py 19.0760 72.8777 3000 SIRS_EARLY_SEPSIS RESPIRATORY_FAILURE

### What this tests
- OSM Overpass API response structure
- Haversine distance calculation
- Scoring algorithm with no ratings data
- Which specializations OSM actually has in your area
- UI rendering of ranked results
