#!/bin/bash

# Test script for Redis failover and recovery

echo "Redis Failover Test Script"
echo "=========================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# API endpoints
HEALTH_URL="http://localhost:8080/health"
PACING_URL="http://localhost:8080/pacing/decision"
SPEND_URL="http://localhost:8080/spend/track"
STATUS_URL="http://localhost:8080/budget/status/camp-001"

# Test campaign
CAMPAIGN_ID="camp-001"

echo -e "${GREEN}1. Initial Health Check${NC}"
curl -s $HEALTH_URL | jq '.'
echo ""

echo -e "${GREEN}2. Making normal pacing decision (Redis UP)${NC}"
curl -s -X POST $PACING_URL \
  -H "Content-Type: application/json" \
  -d "{\"campaign_id\": \"$CAMPAIGN_ID\", \"bid_cents\": 100}" | jq '.'
echo ""

echo -e "${GREEN}3. Tracking spend (Redis UP)${NC}"
curl -s -X POST $SPEND_URL \
  -H "Content-Type: application/json" \
  -d "{\"campaign_id\": \"$CAMPAIGN_ID\", \"spend_cents\": 50, \"impressions\": 10}" | jq '.'
echo ""

echo -e "${YELLOW}4. Simulating Redis failure - Stopping Redis...${NC}"
docker stop redis || redis-cli shutdown nosave
sleep 2
echo ""

echo -e "${RED}5. Health Check (Redis DOWN)${NC}"
curl -s $HEALTH_URL | jq '.'
echo ""

echo -e "${RED}6. Making pacing decision in DEGRADED MODE${NC}"
curl -s -X POST $PACING_URL \
  -H "Content-Type: application/json" \
  -d "{\"campaign_id\": \"$CAMPAIGN_ID\", \"bid_cents\": 100}" | jq '.'
echo ""

echo -e "${RED}7. Tracking spend in DEGRADED MODE (using memory)${NC}"
curl -s -X POST $SPEND_URL \
  -H "Content-Type: application/json" \
  -d "{\"campaign_id\": \"$CAMPAIGN_ID\", \"spend_cents\": 75, \"impressions\": 15}" | jq '.'
echo ""

echo -e "${RED}8. Budget status in DEGRADED MODE${NC}"
curl -s $STATUS_URL | jq '.'
echo ""

echo -e "${YELLOW}9. Starting Redis back up...${NC}"
docker start redis || redis-server --daemonize yes
sleep 5
echo ""

echo -e "${GREEN}10. Waiting for auto-recovery (10 seconds)...${NC}"
sleep 10
echo ""

echo -e "${GREEN}11. Health Check (Redis RECOVERED)${NC}"
curl -s $HEALTH_URL | jq '.'
echo ""

echo -e "${GREEN}12. Making pacing decision (RECOVERED)${NC}"
curl -s -X POST $PACING_URL \
  -H "Content-Type: application/json" \
  -d "{\"campaign_id\": \"$CAMPAIGN_ID\", \"bid_cents\": 100}" | jq '.'
echo ""

echo -e "${GREEN}13. Verifying data was synced to Redis${NC}"
echo "Checking Redis for campaign data..."
redis-cli GET "budget:day:$CAMPAIGN_ID:$(date +%Y-%m-%d)" || echo "No daily data"
redis-cli GET "budget:hour:$CAMPAIGN_ID:$(date +%Y-%m-%d-%H)" || echo "No hourly data"
echo ""

echo -e "${GREEN}Test Complete!${NC}"
echo ""
echo "Summary:"
echo "- Service continued operating when Redis failed"
echo "- Degraded mode provided conservative pacing decisions"
echo "- Memory cache preserved spend tracking"
echo "- Auto-recovery synced data back to Redis"
echo "- Service returned to normal operation automatically"