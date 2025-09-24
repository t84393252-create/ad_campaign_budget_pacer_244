#!/bin/bash

# Health Check Script for Ad Campaign Budget Pacer
# Performs quick system health verification

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "========================================="
echo "🏥 SYSTEM HEALTH CHECK"
echo "========================================="

# Function to check service health
check_service() {
    local name=$1
    local url=$2
    local expected=$3
    
    printf "Checking %-20s" "$name..."
    
    response=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>/dev/null || echo "000")
    
    if [ "$response" = "$expected" ]; then
        echo -e "${GREEN}✓ Healthy${NC} (HTTP $response)"
        return 0
    else
        echo -e "${RED}✗ Unhealthy${NC} (HTTP $response)"
        return 1
    fi
}

# Function to check Redis
check_redis() {
    printf "Checking %-20s" "Redis..."
    
    if docker exec budget-pacer-redis redis-cli ping > /dev/null 2>&1; then
        memory=$(docker exec budget-pacer-redis redis-cli INFO memory | grep used_memory_human | cut -d: -f2 | tr -d '\r')
        echo -e "${GREEN}✓ Healthy${NC} (Memory: $memory)"
        return 0
    else
        echo -e "${RED}✗ Unhealthy${NC}"
        return 1
    fi
}

# Function to check PostgreSQL
check_postgres() {
    printf "Checking %-20s" "PostgreSQL..."
    
    if docker exec budget-pacer-postgres pg_isready -U postgres > /dev/null 2>&1; then
        count=$(docker exec budget-pacer-postgres psql -U postgres -d budget_pacer -t -c "SELECT COUNT(*) FROM campaigns;" 2>/dev/null | tr -d ' \n')
        echo -e "${GREEN}✓ Healthy${NC} (Campaigns: $count)"
        return 0
    else
        echo -e "${RED}✗ Unhealthy${NC}"
        return 1
    fi
}

# Function to test latency
test_latency() {
    printf "Testing response latency..."
    
    total=0
    count=10
    
    for i in $(seq 1 $count); do
        start=$(date +%s%N)
        curl -s -X POST http://localhost:8080/pacing/decision \
            -H "Content-Type: application/json" \
            -d '{"campaign_id":"camp-001","bid_cents":100}' > /dev/null 2>&1
        end=$(date +%s%N)
        
        latency=$(( ($end - $start) / 1000000 ))
        total=$(( $total + $latency ))
    done
    
    avg=$(( $total / $count ))
    
    if [ $avg -lt 10 ]; then
        echo -e "${GREEN}✓ Excellent${NC} (Avg: ${avg}ms)"
    elif [ $avg -lt 20 ]; then
        echo -e "${YELLOW}⚠ Acceptable${NC} (Avg: ${avg}ms)"
    else
        echo -e "${RED}✗ Too Slow${NC} (Avg: ${avg}ms)"
    fi
}

# Function to check circuit breakers
check_circuit_breakers() {
    printf "Checking circuit breakers..."
    
    response=$(curl -s http://localhost:8080/metrics 2>/dev/null | grep circuit_breaker_state | head -1 || echo "")
    
    if [ -n "$response" ]; then
        echo -e "${GREEN}✓ Active${NC}"
    else
        echo -e "${YELLOW}⚠ Not visible${NC}"
    fi
}

# Start checks
echo ""
echo "📡 Service Health:"
echo "-----------------"

services_healthy=true

check_service "Pacer Service" "http://localhost:8080/health" "200" || services_healthy=false
check_service "API Service" "http://localhost:8000/" "200" || services_healthy=false
check_service "Dashboard" "http://localhost/" "200" || services_healthy=false
check_service "Prometheus" "http://localhost:9090/-/healthy" "200" || services_healthy=false
check_service "Grafana" "http://localhost:3000/api/health" "200" || services_healthy=false

echo ""
echo "💾 Data Stores:"
echo "--------------"

check_redis || services_healthy=false
check_postgres || services_healthy=false

echo ""
echo "⚡ Performance:"
echo "--------------"

test_latency
check_circuit_breakers

echo ""
echo "📊 Quick Metrics:"
echo "----------------"

# Get some quick metrics
requests=$(curl -s http://localhost:8080/metrics 2>/dev/null | grep 'pacer_request_duration_seconds_count' | grep decision | awk '{print $2}' | cut -d'.' -f1 || echo "0")
echo "Total requests processed: $requests"

# Memory usage
pacer_mem=$(docker stats --no-stream --format "{{.MemUsage}}" budget-pacer-core 2>/dev/null | cut -d'/' -f1 || echo "N/A")
echo "Pacer memory usage: $pacer_mem"

# Check for errors in logs
errors=$(docker logs budget-pacer-core 2>&1 | grep -c ERROR || echo "0")
warnings=$(docker logs budget-pacer-core 2>&1 | grep -c WARN || echo "0")
echo "Errors in logs: $errors"
echo "Warnings in logs: $warnings"

echo ""
echo "========================================="

if [ "$services_healthy" = true ] && [ "$errors" = "0" ]; then
    echo -e "${GREEN}✅ SYSTEM STATUS: HEALTHY${NC}"
    echo "All systems operational!"
    exit 0
elif [ "$services_healthy" = true ] && [ "$errors" -gt "0" ]; then
    echo -e "${YELLOW}⚠️  SYSTEM STATUS: DEGRADED${NC}"
    echo "Services running but errors detected in logs"
    exit 1
else
    echo -e "${RED}❌ SYSTEM STATUS: UNHEALTHY${NC}"
    echo "Critical services are down!"
    exit 2
fi