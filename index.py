from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import pandas as pd
import numpy as np
from pathlib import Path
import json

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Try sensible locations for the telemetry JSON
POSSIBLE = [
    Path(__file__).parent / "q-vercel-latency.json",
    Path(__file__).parent.parent / "data" / "q-vercel-latency.json",
    Path(__file__).parent.parent / "data" / "telemetry.json",
]
DATA_FILE = next((p for p in POSSIBLE if p.exists()), None)
if DATA_FILE is None:
    raise RuntimeError(f"Telemetry JSON not found. Tried: {POSSIBLE}")

df = pd.read_json(DATA_FILE)
df.columns = [c.lower() for c in df.columns]
if "uptime" in df.columns and "uptime_pct" not in df.columns:
    df = df.rename(columns={"uptime": "uptime_pct"})
df["latency_ms"] = pd.to_numeric(df["latency_ms"], errors="coerce")
df["uptime_pct"] = pd.to_numeric(df["uptime_pct"], errors="coerce")
df = df.dropna(subset=["region", "latency_ms", "uptime_pct"])
df["region_lower"] = df["region"].astype(str).str.lower()


@app.get("/")
async def root():
    return {"message": "Latency API running"}


@app.post("/api/latency")
async def get_latency_stats(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    regions = payload.get("regions")
    threshold = payload.get("threshold_ms")
    if not isinstance(regions, list) or not isinstance(threshold, (int, float)):
        raise HTTPException(
            status_code=400,
            detail='body must be {"regions":[...],"threshold_ms":number}',
        )

    out = {}
    thresh = float(threshold)
    for region in regions:
        rlow = str(region).lower()
        sub = df[df["region_lower"] == rlow]
        if sub.empty:
            out[region] = {
                "avg_latency": None,
                "p95_latency": None,
                "avg_uptime": None,
                "breaches": 0,
            }
            continue
        avg_latency = float(sub["latency_ms"].mean())
        p95_latency = float(np.percentile(sub["latency_ms"], 95))
        avg_uptime = float(sub["uptime_pct"].mean())
        breaches = int((sub["latency_ms"] > thresh).sum())
        out[region] = {
            "avg_latency": round(avg_latency, 3),
            "p95_latency": round(p95_latency, 3),
            "avg_uptime": round(avg_uptime, 5),
            "breaches": breaches,
        }

    return {"regions": out}

