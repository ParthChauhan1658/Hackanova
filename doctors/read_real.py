import json
with open('output_real.json', 'r', encoding='utf-16le') as f:
    data = json.loads(f.read())
print("TOTAL FOUND:", data["total_found"])
print("SPECS:", data["relevant_specialties"])
from pprint import pprint
print("TOP 3:")
pprint(data["ranked_doctors"][:3])
