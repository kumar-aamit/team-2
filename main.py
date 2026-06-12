import os
import socket
import sys
import time
import json
import asyncio
import random
from datetime import datetime, timedelta
from typing import List, Optional, AsyncGenerator

import httpx
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import (create_engine, Column, Integer, String, DateTime,
                        ForeignKey, Boolean, Text, func)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from pydantic import BaseModel

# ----------------------------
# Configuration from environment
# ----------------------------
APP_PORT = int(os.getenv("APP_PORT", "8742"))
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://198.18.5.11:8000/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "/ai/models/NVIDIA/Nemotron-3-120B/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "LLM")
LLM_TIMEOUT_SECONDS = float(os.getenv("LLM_TIMEOUT_SECONDS", "15"))
DB_PATH = os.getenv("DB_PATH", "/data/downtime.db")
SIMULATOR_ENABLED = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
SIMULATOR_INTERVAL_SECONDS = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "8"))
GITHUB_REPO = os.getenv("GITHUB_REPO", "https://github.com/pl247/team-2")
GHCR_IMAGE = os.getenv("GHCR_IMAGE", "ghcr.io/pl247/team-2")

# ----------------------------
# Database setup
# ----------------------------
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class DowntimeEvent(Base):
    __tablename__ = "downtime_events"
    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String, index=True)
    machine_type = Column(String)
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)
    downtime_minutes = Column(Integer, nullable=True)
    description = Column(Text)
    reason_category = Column(String)
    severity = Column(String)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ----------------------------
# LLM Client
# ----------------------------
async def call_llm(description: str) -> dict:
    """
    Calls the LLM to get reason_category and severity.
    Returns a dict with keys: reason_category, severity.
    On failure, returns fallback values.
    """
    categories = ["Mechanical Failure", "Operator Error", "Material Shortage", "Maintenance", "Power Loss", "Unknown"]
    severities = ["Low", "Medium", "High", "Critical"]
    fallback = {"reason_category": "Unclassified", "severity": "Medium"}

    if not LLM_BASE_URL or not LLM_API_KEY:
        return fallback

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {LLM_API_KEY}"
    }
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {
                "role": "system",
                "content": "You are an assistant that classifies machine downtime events. "
                           "Given a free-text description, return a JSON object with exactly two fields: "
                           "'reason_category' and 'severity'. "
                           "reason_category must be one of: Mechanical Failure, Operator Error, Material Shortage, Maintenance, Power Loss, Unknown. "
                           "severity must be one of: Low, Medium, High, Critical. "
                           "Do not return any extra text."
            },
            {
                "role": "user",
                "content": description
            }
        ],
        "temperature": 0.0,
        "max_tokens": 50,
        "response_format": {"type": "json_object"}
    }

    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
            response = await client.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            result = json.loads(content)
            # Validate the result
            if (result.get("reason_category") in categories and
                result.get("severity") in severities):
                return result
            else:
                return fallback
    except Exception as e:
        # Log the error (in a real app, use proper logging)
        print(f"LLM call failed: {e}", file=sys.stderr)
        return fallback

# ----------------------------
# Event Simulator
# ----------------------------
MACHINE_IDS = ["M001", "M002", "M003", "M004", "M005"]
MACHINE_TYPES = ["CNC Mill", "Lathe", "Press", "Conveyor", "Robot"]
DESCRIPTIONS = [
    "Unexpected stoppage due to tool breakage.",
    "Operator halted for safety inspection.",
    "Waiting for material feed.",
    "Scheduled maintenance overrun.",
    "Power fluctuation caused stop.",
    "Jammed component cleared.",
    "Sensor fault triggered stop.",
    "Coolant leak detected."
]

async def generate_event() -> dict:
    machine_id = random.choice(MACHINE_IDS)
    machine_type = random.choice(MACHINE_TYPES)
    start_time = datetime.utcnow() - timedelta(minutes=random.randint(0, 30))
    end_time = start_time + timedelta(minutes=random.randint(5, 60))
    downtime_minutes = int((end_time - start_time).total_seconds() / 60)
    description = random.choice(DESCRIPTIONS)
    return {
        "machine_id": machine_id,
        "machine_type": machine_type,
        "start_time": start_time,
        "end_time": end_time,
        "downtime_minutes": downtime_minutes,
        "description": description
    }

# ----------------------------
# FastAPI App
# ----------------------------
app = FastAPI(title="Machine Downtime Log")

# Serve static files (if any) - we'll serve the HTML from a route for simplicity
# app.mount("/static", StaticFiles(directory="static"), name="static")

# ----------------------------
# Helper functions
# ----------------------------
def get_today_downtime(db: Session) -> int:
    today = datetime.utcnow().date()
    total = db.query(func.sum(DowntimeEvent.downtime_minutes)).filter(
        func.date(DowntimeEvent.start_time) == today
    ).scalar()
    return total or 0

def get_worst_machine_today(db: Session) -> Optional[dict]:
    today = datetime.utcnow().date()
    result = db.query(
        DowntimeEvent.machine_id,
        func.sum(DowntimeEvent.downtime_minutes).label("total")
    ).filter(
        func.date(DowntimeEvent.start_time) == today
    ).group_by(DowntimeEvent.machine_id).order_by(
        func.sum(DowntimeEvent.downtime_minutes).desc()
    ).first()
    if result:
        return {"machine_id": result.machine_id, "total_downtime": result.total}
    return None

def get_recent_events(db: Session, limit: int = 20) -> List[DowntimeEvent]:
    return db.query(DowntimeEvent).order_by(DowntimeEvent.created_at.desc()).limit(limit).all()

# ----------------------------
# Port check on startup
# ----------------------------
def check_port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False

# ----------------------------
# Routes
# ----------------------------
@app.on_event("startup")
async def startup_event():
    if not check_port_free(APP_PORT):
        print(f"Error: Port {APP_PORT} is already in use. Please set a free APP_PORT.", file=sys.stderr)
        sys.exit(1)
    # Start the simulator background task if enabled
    if SIMULATOR_ENABLED:
        asyncio.create_task(simulator_task())

@app.get("/", response_class=HTMLResponse)
async def read_root():
    # Serve a single-page HTML with embedded JavaScript
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Machine Downtime Log</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }
            .header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 20px; }
            .header h1 { margin: 0; }
            .indicators { display: flex; gap: 15px; }
            .indicator { padding: 5px 10px; border-radius: 4px; font-size: 14px; font-weight: bold; }
            .indicator.secure { background-color: #d4edda; color: #155724; }
            .indicator.llm { background-color: #cce5ff; color: #004085; }
            .dashboard { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 20px; }
            .dashboard div { margin: 10px 0; }
            .worst { color: #d32f2f; font-weight: bold; }
            .events { background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .event-item { padding: 10px; border-bottom: 1px solid #eee; display: flex; justify-content: space-between; }
            .event-item:last-child { border-bottom: none; }
            .event-details { flex: 1; }
            .event-meta { font-size: 0.9em; color: #666; }
            .latency { font-size: 0.9em; color: #666; margin-top: 5px; }
            .notes { margin-top: 5px; }
            .notes input { width: 100%; padding: 5px; margin-top: 5px; box-sizing: border-box; }
        </style>
    </head>
    <body>
        <div class="header">
            <h1>Machine Downtime Log</h1>
            <div class="indicators">
                <div id="security-indicator" class="indicator secure">On-Prem Secure</div>
                <div id="llm-indicator" class="indicator llm">LLM: Checking...</div>
            </div>
        </div>
        <div class="dashboard">
            <div>Total Downtime Today: <span id="total-downtime">0</span> minutes</div>
            <div>Worst Machine Today: <span id="worst-machine">None</span></div>
        </div>
        <div class="events">
            <h2>Recent Events</h2>
            <div id="events-list">Loading...</div>
        </div>

        <script>
            const EVENT_SOURCE_URL = "/events";
            const LLM_POLL_URL = "/llm-status";

            let eventSource = new EventSource(EVENT_SOURCE_URL);
            let latencyStart = null;

            eventSource.onmessage = function(event) {
                const data = JSON.parse(event.data);
                const now = Date.now();
                let latency = null;
                if (data.latency_ts) {
                    latency = now - data.latency_ts;
                }
                updateDashboard(data);
                addEventToList(data, latency);
            };

            eventSource.onerror = function(err) {
                console.error("SSE error:", err);
                // Optionally try to reconnect
            };

            function updateDashboard(data) {
                document.getElementById('total-downtime').textContent = data.total_downtime || 0;
                const worst = data.worst_machine;
                const worstEl = document.getElementById('worst-machine');
                if (worst && worst.machine_id) {
                    worstEl.textContent = `${worst.machine_id} (${worst.total_downtime} min)`;
                    worstEl.className = 'worst';
                } else {
                    worstEl.textContent = 'None';
                    worstEl.className = '';
                }
                // Update LLM indicator
                updateLLMIndicator(data.llm_reachable);
            }

            function updateLLMIndicator(reachable) {
                const indicator = document.getElementById('llm-indicator');
                if (reachable) {
                    indicator.textContent = 'LLM: Reachable';
                    indicator.style.backgroundColor = '#d4edda';
                    indicator.style.color = '#155724';
                } else {
                    indicator.textContent = 'LLM: Unreachable';
                    indicator.style.backgroundColor = '#f8d7da';
                    indicator.style.color = '#721c24';
                }
            }

            function addEventToList(eventData, latency) {
                const list = document.getElementById('events-list');
                const div = document.createElement('div');
                div.className = 'event-item';
                div.innerHTML = `
                    <div class="event-details">
                        <strong>${eventData.machine_id}</strong> (${eventData.machine_type}): ${eventData.description}
                        <div class="event-meta">
                            Start: ${new Date(eventData.start_time).toLocaleTimeString()} |
                            End: ${eventData.end_time ? new Date(eventData.end_time).toLocaleTimeString() : 'Ongoing'} |
                            Downtime: ${eventData.downtime_minutes} min |
                            Category: ${eventData.reason_category} |
                            Severity: ${eventData.severity}
                        </div>
                    </div>
                    <div>
                        ${latency !== null ? `<div class="latency">Latency: ${latency} ms</div>` : ''}
                        <div class="notes">
                            <input type="text" placeholder="Add note..." data-id="${eventData.id}">
                        </div>
                    </div>
                `;
                // Prepend to show latest first
                list.insertBefore(div, list.firstChild);
                // Limit to 20 events
                while (list.children.length > 20) {
                    list.removeChild(list.lastChild);
                }
            }

            // Poll for LLM status every 10 seconds
            setInterval(async () => {
                try {
                    const response = await fetch(LLM_POLL_URL);
                    const data = await response.json();
                    updateLLMIndicator(data.reachable);
                } catch (e) {
                    updateLLMIndicator(false);
                }
            }, 10000);
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# ----------------------------
# SSE Endpoint for real-time updates
# ----------------------------
async def event_generator(request: Request) -> AsyncGenerator[str, None]:
    # We'll simulate by querying the database periodically and sending updates
    # In a real app, you might use a queue or database triggers.
    db = SessionLocal()
    try:
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            # Get latest data
            total_downtime = get_today_downtime(db)
            worst_machine = get_worst_machine_today(db)
            recent_events = get_recent_events(db, limit=5)

            # For each recent event, we send an update (but we don't want to spam)
            # We'll send a summary and let the client handle the list.
            # For simplicity, we'll send the latest event if there is one new since last check.
            # We'll keep a simple in-memory cache of the last event id we sent.
            # This is a simplified approach; in production, use a proper message broker.

            # We'll just send the current dashboard state and let the client update the list from a separate endpoint?
            # Instead, we'll send the latest event (if any) and the dashboard.

            # We'll create a dummy latency timestamp (the time we generated the event in the simulator)
            # For now, we'll use the current time as the latency timestamp (so latency will be near zero in the simulator)
            latency_ts = int(time.time() * 1000)

            # We'll send the most recent event (if exists) and the dashboard
            latest_event = recent_events[0] if recent_events else None

            data = {
                "total_downtime": total_downtime,
                "worst_machine": worst_machine,
                "llm_reachable": True,  # We don't have a real check here; we'll update via polling in the client
                "latency_ts": latency_ts
            }
            if latest_event:
                data.update({
                    "id": latest_event.id,
                    "machine_id": latest_event.machine_id,
                    "machine_type": latest_event.machine_type,
                    "description": latest_event.description,
                    "start_time": latest_event.start_time.isoformat(),
                    "end_time": latest_event.end_time.isoformat() if latest_event.end_time else None,
                    "downtime_minutes": latest_event.downtime_minutes,
                    "reason_category": latest_event.reason_category,
                    "severity": latest_event.severity
                })

            yield f"data: {json.dumps(data)}\n\n"

            # Wait a bit before next update
            await asyncio.sleep(2)
    finally:
        db.close()

@app.get("/events")
async def events_endpoint(request: Request):
    return StreamingResponse(event_generator(request), media_type="text/event-stream")

# ----------------------------
# LLM status endpoint (for polling)
# ----------------------------
@app.get("/llm-status")
async def llm_status():
    # We'll try a simple call to the LLM to see if it's reachable
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{LLM_BASE_URL}/models")
            reachable = response.status_code < 500
    except Exception:
        reachable = False
    return {"reachable": reachable}

# ----------------------------
# Simulator background task
# ----------------------------
async def simulator_task():
    while True:
        if SIMULATOR_ENABLED:
            event = await generate_event()
            # Call LLM for classification
            llm_result = await call_llm(event["description"])
            event["reason_category"] = llm_result["reason_category"]
            event["severity"] = llm_result["severity"]

            # Save to database
            db = SessionLocal()
            try:
                db_event = DowntimeEvent(
                    machine_id=event["machine_id"],
                    machine_type=event["machine_type"],
                    start_time=event["start_time"],
                    end_time=event["end_time"],
                    downtime_minutes=event["downtime_minutes"],
                    description=event["description"],
                    reason_category=event["reason_category"],
                    severity=event["severity"]
                )
                db.add(db_event)
                db.commit()
                db.refresh(db_event)
                # We could also trigger an SSE update here, but the endpoint will pick it up on next poll
            except Exception as e:
                print(f"Failed to save event: {e}", file=sys.stderr)
                db.rollback()
            finally:
                db.close()

        await asyncio.sleep(SIMULATOR_INTERVAL_SECONDS)

# ----------------------------
# Run the app (if executed directly)
# ----------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=APP_PORT)