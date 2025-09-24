#!/bin/bash

echo "================================================="
echo "📊 AD CAMPAIGN BUDGET PACER - LATENCY TEST"
echo "================================================="

# Test 1: Single request latency
echo -e "\n🔍 Test 1: Single Request Latency (10 requests)"
for i in {1..10}; do
    time=$(curl -s -o /dev/null -w "%{time_total}" -X POST http://localhost:8080/pacing/decision \
        -H "Content-Type: application/json" \
        -d '{"campaign_id": "camp-001", "bid_cents": 150}')
    echo "  Request $i: $(echo "$time * 1000" | bc -l | cut -d. -f1,2)ms"
done

# Test 2: Concurrent requests
echo -e "\n🔍 Test 2: 100 Concurrent Requests"
start=$(date +%s%N)
for i in {1..100}; do
    curl -s -X POST http://localhost:8080/pacing/decision \
        -H "Content-Type: application/json" \
        -d "{\"campaign_id\": \"camp-00$((i%3+1))\", \"bid_cents\": $((50 + i))}" \
        -o /dev/null &
done
wait
end=$(date +%s%N)
total_ms=$(( ($end - $start) / 1000000 ))
avg_ms=$(( $total_ms / 100 ))
echo "  Total time: ${total_ms}ms"
echo "  Average per request: ${avg_ms}ms"

# Test 3: Check current budget status
echo -e "\n🔍 Test 3: Current Budget Status"
for camp in camp-001 camp-002 camp-003; do
    echo -e "\n  $camp:"
    curl -s http://localhost:8080/budget/status/$camp | jq -r '
        "    • Daily Budget: $" + (.daily_budget_cents/100 | tostring) +
        "\n    • Spent: $" + (.daily_spent_cents/100 | tostring) +
        "\n    • Pace: " + (.pace_percentage | tostring) + "%" +
        "\n    • Throttle: " + (.throttle_rate | tostring) +
        "\n    • Circuit Breaker: " + .circuit_breaker_state'
done

echo -e "\n================================================="
echo "✅ LATENCY TEST COMPLETE"
echo "================================================="