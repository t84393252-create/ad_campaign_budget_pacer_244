import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
from datetime import datetime
import asyncpg

# Mock the database connection
@pytest.fixture
def mock_db():
    with patch('asyncpg.create_pool') as mock_pool:
        mock_conn = MagicMock()
        mock_pool.return_value = mock_conn
        yield mock_conn

@pytest.fixture
def client(mock_db):
    from main import app
    return TestClient(app)

def test_root_endpoint(client):
    """Test the root endpoint"""
    response = client.get("/")
    assert response.status_code == 200
    assert "Ad Campaign Budget Pacer API" in response.json()["message"]

def test_list_campaigns(client, mock_db):
    """Test listing campaigns"""
    # Mock database response
    mock_db.fetch.return_value = [
        {
            'id': 'camp-001',
            'name': 'Test Campaign',
            'daily_budget_cents': 10000,
            'total_budget_cents': 100000,
            'pacing_algorithm': 'EVEN',
            'start_date': datetime.now().date(),
            'end_date': datetime.now().date(),
            'status': 'ACTIVE'
        }
    ]
    
    response = client.get("/campaigns")
    assert response.status_code == 200
    campaigns = response.json()
    assert isinstance(campaigns, list)

def test_create_campaign(client, mock_db):
    """Test creating a new campaign"""
    campaign_data = {
        "id": "test-campaign",
        "name": "Test Campaign",
        "daily_budget_cents": 50000,
        "total_budget_cents": 500000,
        "pacing_algorithm": "EVEN"
    }
    
    mock_db.execute.return_value = None
    
    response = client.post("/campaigns", json=campaign_data)
    assert response.status_code == 200
    result = response.json()
    assert result["message"] == "Campaign created successfully"

def test_update_campaign(client, mock_db):
    """Test updating a campaign"""
    update_data = {
        "daily_budget_cents": 60000,
        "pacing_algorithm": "ASAP"
    }
    
    mock_db.execute.return_value = None
    
    response = client.put("/campaigns/camp-001", json=update_data)
    assert response.status_code == 200
    result = response.json()
    assert result["message"] == "Campaign updated successfully"

def test_delete_campaign(client, mock_db):
    """Test deleting a campaign"""
    mock_db.execute.return_value = None
    
    response = client.delete("/campaigns/camp-001")
    assert response.status_code == 200
    result = response.json()
    assert result["message"] == "Campaign deleted successfully"

def test_get_budget_status(client):
    """Test getting budget status"""
    with patch('httpx.AsyncClient') as mock_http:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "daily_budget_cents": 10000,
            "daily_spent_cents": 5000,
            "pace_percentage": 50.0,
            "circuit_breaker_open": False
        }
        mock_http.return_value.get.return_value = mock_response
        
        response = client.get("/budget/status/camp-001")
        assert response.status_code == 200
        status = response.json()
        assert "daily_spent_cents" in status

def test_get_performance_analytics(client, mock_db):
    """Test getting performance analytics"""
    mock_db.fetch.return_value = [
        {
            'campaign_id': 'camp-001',
            'hour': datetime.now(),
            'impressions': 1000,
            'spend_cents': 5000,
            'avg_latency_ms': 8.5,
            'throttle_rate': 0.1
        }
    ]
    
    response = client.get("/analytics/performance?campaign_id=camp-001&period=24h")
    assert response.status_code == 200
    analytics = response.json()
    assert isinstance(analytics, list)

def test_campaign_validation(client, mock_db):
    """Test campaign validation"""
    invalid_campaign = {
        "id": "test",
        "name": "Test",
        "daily_budget_cents": -1000,  # Invalid negative budget
        "total_budget_cents": 1000,
        "pacing_algorithm": "INVALID"  # Invalid algorithm
    }
    
    response = client.post("/campaigns", json=invalid_campaign)
    assert response.status_code == 422  # Validation error

def test_health_endpoint(client):
    """Test health check endpoint"""
    response = client.get("/health")
    assert response.status_code == 200
    health = response.json()
    assert health["status"] == "healthy"

@pytest.mark.asyncio
async def test_database_connection_error():
    """Test handling of database connection errors"""
    with patch('asyncpg.create_pool', side_effect=Exception("Connection failed")):
        from main import app
        client = TestClient(app)
        response = client.get("/campaigns")
        assert response.status_code == 500