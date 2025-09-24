from fastapi import FastAPI, HTTPException, WebSocket, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import asyncpg
import redis.asyncio as redis
import httpx
import json
import os
from datetime import datetime, timedelta
import asyncio
from contextlib import asynccontextmanager

class Campaign(BaseModel):
    id: str
    name: str
    daily_budget_cents: int
    total_budget_cents: Optional[int] = None
    start_date: datetime
    end_date: datetime
    pacing_mode: str = "EVEN"
    status: str = "ACTIVE"

class BudgetAdjustment(BaseModel):
    campaign_id: str
    new_daily_budget_cents: int
    reason: Optional[str] = None

class PacingModeUpdate(BaseModel):
    campaign_id: str
    pacing_mode: str

class BudgetStatusResponse(BaseModel):
    campaign_id: str
    daily_budget_cents: int
    daily_spent_cents: int
    hourly_spent_cents: int
    pace_percentage: float
    should_throttle: bool
    throttle_rate: float
    circuit_breaker_open: bool

class HistoricalPerformance(BaseModel):
    date: str
    hour: int
    planned_spend: int
    actual_spend: int
    pacing_accuracy: float

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db = await asyncpg.create_pool(
        os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost/budget_pacer"),
        min_size=10,
        max_size=20
    )
    app.state.redis = await redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379"),
        encoding="utf-8",
        decode_responses=True
    )
    app.state.pacer_url = os.getenv("PACER_SERVICE_URL", "http://localhost:8080")
    
    yield
    
    await app.state.db.close()
    await app.state.redis.close()

app = FastAPI(
    title="Ad Campaign Budget Pacer API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"service": "Ad Campaign Budget Pacer API", "version": "1.0.0"}

@app.post("/campaigns", response_model=Campaign)
async def create_campaign(campaign: Campaign):
    async with app.state.db.acquire() as conn:
        try:
            await conn.execute("""
                INSERT INTO campaigns (id, name, daily_budget_cents, total_budget_cents, 
                                      start_date, end_date, pacing_mode, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """, campaign.id, campaign.name, campaign.daily_budget_cents, 
                campaign.total_budget_cents, campaign.start_date, campaign.end_date,
                campaign.pacing_mode, campaign.status)
            
            await app.state.redis.delete(f"campaigns:{campaign.id}")
            
            return campaign
        except asyncpg.UniqueViolationError:
            raise HTTPException(status_code=400, detail="Campaign ID already exists")

@app.get("/campaigns", response_model=List[Campaign])
async def list_campaigns(status: Optional[str] = "ACTIVE"):
    async with app.state.db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT id, name, daily_budget_cents, total_budget_cents, 
                   start_date, end_date, pacing_mode, status
            FROM campaigns
            WHERE status = $1 OR $1 IS NULL
            ORDER BY created_at DESC
        """, status)
        
        campaigns = []
        for row in rows:
            campaigns.append(Campaign(**dict(row)))
        
        return campaigns

@app.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: str):
    cache_key = f"campaigns:{campaign_id}"
    cached = await app.state.redis.get(cache_key)
    
    if cached:
        return Campaign(**json.loads(cached))
    
    async with app.state.db.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT id, name, daily_budget_cents, total_budget_cents, 
                   start_date, end_date, pacing_mode, status
            FROM campaigns
            WHERE id = $1
        """, campaign_id)
        
        if not row:
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        campaign = Campaign(**dict(row))
        await app.state.redis.setex(cache_key, 60, campaign.model_dump_json())
        
        return campaign

@app.put("/campaigns/{campaign_id}", response_model=Campaign)
async def update_campaign(campaign_id: str, campaign: Campaign):
    async with app.state.db.acquire() as conn:
        result = await conn.execute("""
            UPDATE campaigns
            SET name = $2, daily_budget_cents = $3, total_budget_cents = $4, 
                end_date = $5, pacing_mode = $6, status = $7, 
                updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, campaign_id, campaign.name, campaign.daily_budget_cents, 
            campaign.total_budget_cents, campaign.end_date, 
            campaign.pacing_mode, campaign.status)
        
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        await app.state.redis.delete(f"campaigns:{campaign_id}")
        
        return campaign

@app.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: str):
    async with app.state.db.acquire() as conn:
        result = await conn.execute("""
            UPDATE campaigns
            SET status = 'DELETED', updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, campaign_id)
        
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        await app.state.redis.delete(f"campaigns:{campaign_id}")
        
        return {"message": "Campaign deleted successfully"}

@app.post("/budget/adjust")
async def adjust_budget(adjustment: BudgetAdjustment):
    async with app.state.db.acquire() as conn:
        result = await conn.execute("""
            UPDATE campaigns
            SET daily_budget_cents = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, adjustment.campaign_id, adjustment.new_daily_budget_cents)
        
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        await conn.execute("""
            INSERT INTO budget_alerts (campaign_id, alert_type, message)
            VALUES ($1, 'BUDGET_ADJUSTMENT', $2)
        """, adjustment.campaign_id, adjustment.reason or "Manual adjustment")
        
        await app.state.redis.delete(f"campaigns:{adjustment.campaign_id}")
        
        return {"message": "Budget adjusted successfully"}

@app.post("/pacing/mode")
async def update_pacing_mode(update: PacingModeUpdate):
    valid_modes = ["EVEN", "ASAP", "FRONT_LOADED", "ADAPTIVE"]
    if update.pacing_mode not in valid_modes:
        raise HTTPException(status_code=400, detail=f"Invalid pacing mode. Must be one of {valid_modes}")
    
    async with app.state.db.acquire() as conn:
        result = await conn.execute("""
            UPDATE campaigns
            SET pacing_mode = $2, updated_at = CURRENT_TIMESTAMP
            WHERE id = $1
        """, update.campaign_id, update.pacing_mode)
        
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Campaign not found")
        
        await app.state.redis.delete(f"campaigns:{update.campaign_id}")
        
        return {"message": "Pacing mode updated successfully"}

@app.get("/budget/status/{campaign_id}", response_model=BudgetStatusResponse)
async def get_budget_status(campaign_id: str):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{app.state.pacer_url}/budget/status/{campaign_id}")
            response.raise_for_status()
            return BudgetStatusResponse(**response.json())
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                raise HTTPException(status_code=404, detail="Campaign not found")
            raise HTTPException(status_code=500, detail="Failed to get budget status")

@app.get("/performance/{campaign_id}")
async def get_historical_performance(
    campaign_id: str,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
):
    if not start_date:
        start_date = datetime.now() - timedelta(days=7)
    if not end_date:
        end_date = datetime.now()
    
    async with app.state.db.acquire() as conn:
        rows = await conn.fetch("""
            SELECT date, hour, planned_spend_cents, actual_spend_cents, 
                   pacing_accuracy, impressions, clicks
            FROM pacing_history
            WHERE campaign_id = $1 AND date BETWEEN $2 AND $3
            ORDER BY date DESC, hour DESC
        """, campaign_id, start_date.date(), end_date.date())
        
        if not rows:
            return []
        
        performance = []
        for row in rows:
            performance.append({
                "date": row["date"].isoformat(),
                "hour": row["hour"],
                "planned_spend": row["planned_spend_cents"],
                "actual_spend": row["actual_spend_cents"],
                "pacing_accuracy": row["pacing_accuracy"],
                "impressions": row["impressions"],
                "clicks": row["clicks"]
            })
        
        return performance

@app.get("/alerts/{campaign_id}")
async def get_alerts(campaign_id: str, unresolved_only: bool = True):
    async with app.state.db.acquire() as conn:
        if unresolved_only:
            rows = await conn.fetch("""
                SELECT id, alert_type, threshold_percentage, message, 
                       circuit_breaker_state, created_at
                FROM budget_alerts
                WHERE campaign_id = $1 AND resolved_at IS NULL
                ORDER BY created_at DESC
                LIMIT 50
            """, campaign_id)
        else:
            rows = await conn.fetch("""
                SELECT id, alert_type, threshold_percentage, message, 
                       circuit_breaker_state, created_at, resolved_at
                FROM budget_alerts
                WHERE campaign_id = $1
                ORDER BY created_at DESC
                LIMIT 100
            """, campaign_id)
        
        alerts = []
        for row in rows:
            alert = dict(row)
            alert["created_at"] = alert["created_at"].isoformat()
            if "resolved_at" in alert and alert["resolved_at"]:
                alert["resolved_at"] = alert["resolved_at"].isoformat()
            alerts.append(alert)
        
        return alerts

@app.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: int):
    async with app.state.db.acquire() as conn:
        result = await conn.execute("""
            UPDATE budget_alerts
            SET resolved_at = CURRENT_TIMESTAMP
            WHERE id = $1 AND resolved_at IS NULL
        """, alert_id)
        
        if result == "UPDATE 0":
            raise HTTPException(status_code=404, detail="Alert not found or already resolved")
        
        return {"message": "Alert resolved successfully"}

@app.post("/pacing/simulate")
async def simulate_pacing(
    campaign_id: str,
    hours_ahead: int = 24,
    traffic_pattern: Optional[List[float]] = None
):
    campaign = await get_campaign(campaign_id)
    
    if not traffic_pattern:
        traffic_pattern = [1.0] * hours_ahead
    
    simulation_results = []
    remaining_budget = campaign.daily_budget_cents
    
    for hour in range(hours_ahead):
        traffic_multiplier = traffic_pattern[hour] if hour < len(traffic_pattern) else 1.0
        hourly_budget = campaign.daily_budget_cents / 24 * traffic_multiplier
        
        spend = min(hourly_budget, remaining_budget)
        remaining_budget -= spend
        
        simulation_results.append({
            "hour": hour,
            "projected_spend": int(spend),
            "remaining_budget": int(remaining_budget),
            "traffic_multiplier": traffic_multiplier
        })
    
    return {
        "campaign_id": campaign_id,
        "pacing_mode": campaign.pacing_mode,
        "simulation": simulation_results,
        "total_projected_spend": campaign.daily_budget_cents - int(remaining_budget)
    }

@app.websocket("/ws/budget-updates")
async def websocket_budget_updates(websocket: WebSocket):
    await websocket.accept()
    
    try:
        pubsub = app.state.redis.pubsub()
        await pubsub.subscribe("budget_updates")
        
        while True:
            message = await asyncio.wait_for(
                pubsub.get_message(ignore_subscribe_messages=True),
                timeout=30.0
            )
            
            if message and message["type"] == "message":
                await websocket.send_text(message["data"])
            
    except asyncio.TimeoutError:
        await websocket.send_text(json.dumps({"type": "ping"}))
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

@app.get("/metrics/summary")
async def get_metrics_summary():
    async with app.state.db.acquire() as conn:
        summary = await conn.fetchrow("""
            SELECT 
                COUNT(DISTINCT campaign_id) as active_campaigns,
                SUM(total_spend_cents) as total_spend_today,
                AVG(pacing_accuracy) as avg_pacing_accuracy,
                SUM(circuit_breaker_trips) as total_circuit_trips
            FROM daily_metrics
            WHERE date = CURRENT_DATE
        """)
        
        return dict(summary) if summary else {
            "active_campaigns": 0,
            "total_spend_today": 0,
            "avg_pacing_accuracy": 0,
            "total_circuit_trips": 0
        }

@app.post("/budget/reset/{campaign_id}")
async def reset_campaign_budget(campaign_id: str, background_tasks: BackgroundTasks):
    async with httpx.AsyncClient() as client:
        try:
            await app.state.redis.delete(
                f"budget:day:{campaign_id}:*",
                f"budget:hour:{campaign_id}:*"
            )
            
            background_tasks.add_task(log_budget_reset, campaign_id)
            
            return {"message": "Budget reset successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to reset budget: {str(e)}")

async def log_budget_reset(campaign_id: str):
    async with app.state.db.acquire() as conn:
        await conn.execute("""
            INSERT INTO budget_alerts (campaign_id, alert_type, message)
            VALUES ($1, 'BUDGET_RESET', 'Manual budget reset performed')
        """, campaign_id)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)