from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import random

app = FastAPI(title="Ad Campaign Budget Pacer API - Mock")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Campaign(BaseModel):
    id: str
    name: str
    daily_budget_cents: int
    total_budget_cents: Optional[int] = None
    start_date: datetime
    end_date: datetime
    pacing_mode: str = "EVEN"
    status: str = "ACTIVE"

# Mock data
campaigns_db = {
    "camp-001": {
        "id": "camp-001",
        "name": "Test Campaign 1",
        "daily_budget_cents": 1000000,
        "total_budget_cents": 30000000,
        "start_date": datetime.now().isoformat(),
        "end_date": datetime.now().replace(day=28).isoformat(),
        "pacing_mode": "EVEN",
        "status": "ACTIVE"
    },
    "camp-002": {
        "id": "camp-002",
        "name": "Test Campaign 2",
        "daily_budget_cents": 500000,
        "total_budget_cents": 15000000,
        "start_date": datetime.now().isoformat(),
        "end_date": datetime.now().replace(day=28).isoformat(),
        "pacing_mode": "ASAP",
        "status": "ACTIVE"
    }
}

@app.get("/")
async def root():
    return {"service": "Ad Campaign Budget Pacer API - Mock", "version": "1.0.0"}

@app.post("/campaigns", response_model=Campaign)
async def create_campaign(campaign: Campaign):
    campaigns_db[campaign.id] = campaign.dict()
    return campaign

@app.get("/campaigns", response_model=List[Campaign])
async def list_campaigns(status: Optional[str] = "ACTIVE"):
    campaigns = []
    for camp in campaigns_db.values():
        if status is None or camp.get("status") == status:
            campaigns.append(Campaign(**camp))
    return campaigns

@app.get("/campaigns/{campaign_id}", response_model=Campaign)
async def get_campaign(campaign_id: str):
    if campaign_id not in campaigns_db:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return Campaign(**campaigns_db[campaign_id])

@app.get("/budget/status/{campaign_id}")
async def get_budget_status(campaign_id: str):
    if campaign_id not in campaigns_db:
        # Create mock campaign
        campaigns_db[campaign_id] = {
            "id": campaign_id,
            "name": f"Campaign {campaign_id}",
            "daily_budget_cents": 100000,
            "status": "ACTIVE"
        }
    
    campaign = campaigns_db[campaign_id]
    spent = random.randint(30000, 90000)
    
    return {
        "campaign_id": campaign_id,
        "daily_budget_cents": campaign.get("daily_budget_cents", 100000),
        "daily_spent_cents": spent,
        "hourly_spent_cents": spent // 24,
        "pace_percentage": (spent / campaign.get("daily_budget_cents", 100000)) * 100,
        "should_throttle": spent > campaign.get("daily_budget_cents", 100000) * 0.8,
        "throttle_rate": max(0, (spent / campaign.get("daily_budget_cents", 100000) - 0.8) / 0.2),
        "circuit_breaker_open": spent > campaign.get("daily_budget_cents", 100000) * 0.95
    }

@app.get("/metrics/summary")
async def get_metrics_summary():
    return {
        "active_campaigns": len(campaigns_db),
        "total_spend_today": sum(random.randint(30000, 90000) for _ in campaigns_db),
        "avg_pacing_accuracy": 95.5,
        "total_circuit_trips": random.randint(0, 3)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)