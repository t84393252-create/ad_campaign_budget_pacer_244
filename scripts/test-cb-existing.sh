#!/bin/bash

echo "================================================="
echo "🔍 CIRCUIT BREAKER TEST ON EXISTING CAMPAIGN"
echo "================================================="

CAMPAIGN="camp-001"

# Check current status
echo -e "\n📊 Current status of $CAMPAIGN:"
STATUS=$(curl -s http://localhost:8080/budget/status/$CAMPAIGN)
echo "$STATUS" | jq -r '
    "  • Daily Budget: $" + (.daily_budget_cents/100 | tostring) +
    "\n  • Currently Spent: $" + (.daily_spent_cents/100 | tostring) +
    "\n  • Pace: " + (.pace_percentage | tostring) + "%" +
    "\n  • Circuit Breaker: " + .circuit_breaker_state'

CURRENT_SPENT=$(echo "$STATUS" | jq -r '.daily_spent_cents')
DAILY_BUDGET=$(echo "$STATUS" | jq -r '.daily_budget_cents')
THRESHOLD=$((DAILY_BUDGET * 95 / 100))
TO_SPEND=$((THRESHOLD - CURRENT_SPENT + 1000))  # Push slightly over 95%

echo -e "\n📊 Circuit breaker should trigger at: \$$(echo "scale=2; $THRESHOLD/100" | bc)"
echo "📊 Need to spend: \$$(echo "scale=2; $TO_SPEND/100" | bc) more"

# Test bid is allowed before threshold
echo -e "\n🔍 Testing bid BEFORE threshold:"
curl -s -X POST http://localhost:8080/pacing/decision \
    -H "Content-Type: application/json" \
    -d "{\"campaign_id\": \"$CAMPAIGN\", \"bid_cents\": 100}" | \
    jq -r '"  • Allow bid: " + (.allow_bid | tostring) + "\n  • Reason: " + .reason'

# Track spending to push over 95%
echo -e "\n🔍 Tracking \$$(echo "scale=2; $TO_SPEND/100" | bc) in spending..."
curl -s -X POST http://localhost:8080/spend/track \
    -H "Content-Type: application/json" \
    -d "{\"campaign_id\": \"$CAMPAIGN\", \"spend_cents\": $TO_SPEND, \"impressions\": 100}" \
    -o /dev/null

# Check status after spending
echo -e "\n📊 Status AFTER pushing to 95%+:"
STATUS=$(curl -s http://localhost:8080/budget/status/$CAMPAIGN)
echo "$STATUS" | jq -r '
    "  • Currently Spent: $" + (.daily_spent_cents/100 | tostring) +
    "\n  • Pace: " + (.pace_percentage | tostring) + "%" +
    "\n  • Circuit Breaker State: " + .circuit_breaker_state +
    "\n  • Circuit Breaker Open: " + (.circuit_breaker_open | tostring)'

# Test bid is blocked after threshold
echo -e "\n🔍 Testing bid AFTER threshold:"
for i in {1..3}; do
    echo -e "\n  Attempt $i:"
    curl -s -X POST http://localhost:8080/pacing/decision \
        -H "Content-Type: application/json" \
        -d "{\"campaign_id\": \"$CAMPAIGN\", \"bid_cents\": 100}" | \
        jq -r '"    • Allow bid: " + (.allow_bid | tostring) + "\n    • Reason: " + .reason + "\n    • Throttle: " + (.throttle_rate | tostring)'
done

echo -e "\n================================================="
echo "✅ CIRCUIT BREAKER TEST COMPLETE"
echo "================================================="