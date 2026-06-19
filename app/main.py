"""
Main FastAPI application for the Machine Downtime Log.
"""
import os
import socket
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
import asyncio

from . import models, database, llm_client, event_simulator
from .database import Base, engine, get_db_session, get_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="Machine Downtime Log",
    description="Real-time tracker for manufacturing-floor machine stoppages",
    version="1.0.0"
)

# Templates configuration
templates = Jinja2Templates(directory="app/templates")

# Global LLM client instance
llm_client_instance: Optional[llm_client.LLMClient] = None

# Track application start time for health checks
app_start_time = datetime.utcnow()


def check_port_availability(port: int) -> bool:
    """
    Check if a port is available for binding.
    
    Args:
        port: Port number to check
        
    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(('0.0.0.0', port))
            return True
    except OSError:
        return False


def initialize_app():
    """Initialize the application on startup."""
    global llm_client_instance
    
    logger.info("Initializing Machine Downtime Log application...")
    
    # Check if APP_PORT is available
    app_port = int(os.getenv("APP_PORT", "8742"))
    if not check_port_availability(app_port):
        error_msg = (
            f"ERROR: Port {app_port} is already in use. "
            f"Please set APP_PORT to a different port or stop the service using this port."
        )
        logger.error(error_msg)
        print(error_msg, file=sys.stderr)
        sys.exit(1)
    
    logger.info(f"Port {app_port} is available")
    
    # Initialize database
    try:
        database.create_tables()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}")
        sys.exit(1)
    
    # Initialize LLM client if configuration is available
    try:
        llm_client_instance = llm_client.create_llm_client()
        if llm_client_instance:
            logger.info("LLM client initialized successfully")
        else:
            logger.warning("LLM client not initialized due to missing configuration")
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        llm_client_instance = None
    
    # Start event simulator if enabled
    simulator_enabled = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
    if simulator_enabled:
        try:
            interval_seconds = int(os.getenv("SIMULATOR_INTERVAL_SECONDS", "8"))
            event_simulator.simulator.interval_seconds = interval_seconds
            # Note: In a production setup, you'd start this as a background task
            # For simplicity in this example, we note that it should be started
            logger.info(f"Event simulator configured (interval: {interval_seconds}s)")
            logger.info("To start simulator: call event_simulator.simulator.start()")
        except Exception as e:
            logger.error(f"Failed to configure event simulator: {e}")
    
    logger.info("Application initialization complete")


# Startup event handler
@app.on_event("startup")
async def startup_event():
    """Handle application startup."""
    initialize_app()
    
    # Start event simulator if enabled
    simulator_enabled = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
    if simulator_enabled:
        try:
            await event_simulator.simulator.start()
            logger.info("Event simulator started")
        except Exception as e:
            logger.error(f"Failed to start event simulator: {e}")


# Shutdown event handler
@app.on_event("shutdown")
async def shutdown_event():
    """Handle application shutdown."""
    logger.info("Shutting down Machine Downtime Log application...")
    
    # Stop event simulator if running
    simulator_enabled = os.getenv("SIMULATOR_ENABLED", "true").lower() == "true"
    if simulator_enabled:
        try:
            await event_simulator.simulator.stop()
            logger.info("Event simulator stopped")
        except Exception as e:
            logger.error(f"Error stopping event simulator: {e}")


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    db_status = "unknown"
    llm_status = "unknown"
    
    # Check database connectivity
    try:
        with get_db_session() as db:
            db.execute(text("SELECT 1"))
            db_status = "healthy"
    except Exception as e:
        db_status = f"unhealthy: {str(e)}"
        logger.error(f"Database health check failed: {e}")
    
    # Check LLM connectivity
    if llm_client_instance:
        try:
            is_healthy = llm_client_instance.health_check()
            llm_status = "healthy" if is_healthy else "unhealthy"
        except Exception as e:
            llm_status = f"unhealthy: {str(e)}"
            logger.error(f"LLM health check failed: {e}")
    else:
        llm_status = "not_configured"
    
    uptime = (datetime.utcnow() - app_start_time).total_seconds()
    
    return JSONResponse({
        "status": "healthy" if db_status == "healthy" else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "uptime_seconds": uptime,
        "checks": {
            "database": db_status,
            "llm": llm_status,
            "port": int(os.getenv("APP_PORT", "8742"))
        }
    })


# Root endpoint - serve the main dashboard
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Serve the main dashboard page."""
    return templates.TemplateResponse("index.html", {"request": request})


# API endpoints for dashboard data
@app.get("/api/dashboard")
async def get_dashboard_data(db: Session = Depends(get_db)):
    """Get dashboard summary data."""
    try:
        # Get today's date range
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + timedelta(days=1)
        
        # Query downtime events for today
        today_events = db.query(models.DowntimeEvent).filter(
            models.DowntimeEvent.start_time >= today_start,
            models.DowntimeEvent.start_time < today_end
        ).all()
        
        # Calculate total downtime
        total_downtime = sum(
            event.downtime_minutes or 0 
            for event in today_events 
            if event.downtime_minutes is not None
        )
        
        # Find machine with most downtime today
        machine_downtime = {}
        for event in today_events:
            if event.downtime_minutes is not None:
                machine_id = event.machine_id
                if machine_id not in machine_downtime:
                    machine_downtime[machine_id] = 0
                machine_downtime[machine_id] += event.downtime_minutes
        
        worst_machine_id = None
        worst_machine_downtime = 0
        if machine_downtime:
            worst_machine_id = max(machine_downtime, key=machine_downtime.get)
            worst_machine_downtime = machine_downtime[worst_machine_id]
        
        # Get recent events (last 20)
        recent_events = db.query(models.DowntimeEvent).order_by(
            desc(models.DowntimeEvent.created_at)
        ).limit(20).all()
        
        return JSONResponse({
            "total_downtime_minutes": total_downtime,
            "worst_machine": {
                "machine_id": worst_machine_id,
                "downtime_minutes": worst_machine_downtime
            } if worst_machine_id else None,
            "recent_events": [event.to_dict() for event in recent_events],
            "timestamp": datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        logger.error(f"Error fetching dashboard data: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")


# API endpoint for raw event stream (for frontend SSE)
@app.get("/api/events/stream")
async def get_event_stream(request: Request, db: Session = Depends(get_db)):
    """Server-Sent Events endpoint for real-time event streaming."""
    async def event_generator():
        last_event_id = 0
        
        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break
                
            try:
                # Get new events since last check
                new_events = db.query(models.EventStream).filter(
                    models.EventStream.id > last_event_id
                ).order_by(models.EventStream.id).all()
                
                for event in new_events:
                    last_event_id = event.id
                    yield f"data: {json.dumps(event.to_dict())}\n\n"
                    
                # Wait before checking again
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"Error in event stream: {e}")
                yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
                await asyncio.sleep(5)  # Wait longer on error
    
    return event_generator()


# API endpoint to get LLM status
@app.get("/api/llm/status")
async def get_llm_status():
    """Get LLM service status."""
    if llm_client_instance is None:
        return JSONResponse({
            "available": False,
            "reason": "not_configured"
        })
    
    try:
        is_healthy = llm_client_instance.health_check()
        return JSONResponse({
            "available": is_healthy,
            "reason": "healthy" if is_healthy else "unhealthy"
        })
    except Exception as e:
        return JSONResponse({
            "available": False,
            "reason": f"error: {str(e)}"
        })


if __name__ == "__main__":
    import uvicorn
    import sys
    
    # Get port from environment
    port = int(os.getenv("APP_PORT", "8742"))
    
    # Run the application
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True
    )
