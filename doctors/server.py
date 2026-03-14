import uvicorn
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fetch_doctors import find_and_rank_doctors

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/doctors")
async def get_doctors(
    lat: float = Query(18.9388),
    lng: float = Query(72.8354),
    radius_m: int = Query(5000),
    syndromes: str = Query("SIRS_EARLY_SEPSIS")
):
    syndrome_list = [s.strip() for s in syndromes.split(",") if s.strip()]
    return await find_and_rank_doctors(lat, lng, radius_m, syndrome_list)

@app.get("/")
def serve_ui():
    return FileResponse("index.html")

if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=8080, reload=True)
