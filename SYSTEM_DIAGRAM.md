# 🏗️ Ad Campaign Budget Pacer - Complete System Diagram

## 📊 Full System Flow

```mermaid
graph TB
    subgraph "🌐 External Systems"
        RTB[Real-Time Bidding Platform<br/>100ms auction window]
        ADV[Advertisers<br/>Campaign Setup]
    end

    subgraph "🎯 User Interface Layer"
        DASH[Dashboard<br/>HTML/JS/Chart.js]
        API_CLIENT[API Clients<br/>curl/SDK]
    end

    subgraph "🔄 Load Balancer"
        NGINX[Nginx Reverse Proxy<br/>Port 80<br/>- Routes /api → FastAPI<br/>- Routes / → Dashboard<br/>- Routes /pacing → Go Service]
    end

    subgraph "🐍 Management Layer"
        FASTAPI[FastAPI Service<br/>Port 8000<br/>- Campaign CRUD<br/>- Budget Management<br/>- Historical Analytics]
    end

    subgraph "⚡ Core Pacing Engine"
        PACER[Go Pacer Service<br/>Port 8080<br/>- Sub-10ms decisions<br/>- Circuit Breakers<br/>- Pacing Algorithms]
        
        subgraph "Algorithms"
            EVEN[EVEN Pacing]
            ASAP[ASAP Pacing]
            FRONT[FRONT_LOADED]
            ADAPT[ADAPTIVE]
        end
        
        CB[Circuit Breaker<br/>- CLOSED: Normal<br/>- OPEN: @ 95% spent<br/>- HALF_OPEN: Recovery]
    end

    subgraph "💾 Data Layer"
        REDIS[(Redis<br/>Port 6379<br/>Real-time Counters<br/>TTL: 24 hours)]
        PG[(PostgreSQL<br/>Port 5432<br/>Campaigns<br/>Historical Data)]
        MEMORY[In-Memory Cache<br/>Fallback during<br/>Redis failure]
    end

    %% User flows
    ADV -->|Create Campaign| DASH
    DASH -->|HTTP| NGINX
    API_CLIENT -->|HTTP| NGINX
    
    %% Nginx routing
    NGINX -->|/api/*| FASTAPI
    NGINX -->|Static Files| DASH
    NGINX -->|/pacing/*<br/>/spend/*<br/>/budget/*| PACER
    
    %% FastAPI operations
    FASTAPI -->|Campaign Config| PG
    FASTAPI -->|Budget Status| PACER
    
    %% RTB flow
    RTB -->|Bid Request<br/>campaign_id<br/>bid_cents| PACER
    PACER -->|Allow/Deny<br/>< 10ms| RTB
    
    %% Pacer internal flow
    PACER --> CB
    CB --> EVEN
    CB --> ASAP
    CB --> FRONT
    CB --> ADAPT
    
    %% Data flows
    PACER -->|Increment Spend| REDIS
    PACER -->|Read Counters| REDIS
    PACER -->|Fallback| MEMORY
    MEMORY -->|Sync on Recovery| REDIS
    PACER -->|Load Campaigns| PG
    PACER -->|Store History| PG

    style RTB fill:#ff9999,color:#000
    style PACER fill:#99ff99,color:#000
    style CB fill:#ffcc99,color:#000
    style REDIS fill:#99ccff,color:#000
    style PG fill:#cc99ff,color:#000
    style NGINX fill:#f9f9f9,color:#000
    style FASTAPI fill:#f0f0f0,color:#000
    style DASH fill:#f5f5f5,color:#000
    style MEMORY fill:#ffffcc,color:#000
```

## 🔄 Request Flow Sequences

### 1️⃣ Bid Decision Flow (< 10ms)

```
RTB Platform                  Pacer Service              Redis              Circuit Breaker
     |                             |                       |                      |
     |------ Bid Request --------->|                       |                      |
     |   {campaign_id, bid_cents}  |                       |                      |
     |                             |                       |                      |
     |                             |---Get Spent Today---->|                      |
     |                             |<------$4,500----------|                      |
     |                             |                       |                      |
     |                             |---Check Threshold---->|                      |
     |                             |                       |---Is 45% < 95%?----->|
     |                             |                       |<-----CLOSED----------|
     |                             |                       |                      |
     |                             |--Calculate Throttle-->|                      |
     |                             |  (EVEN: 0% throttle)  |                      |
     |                             |                       |                      |
     |<------ALLOW BID-------------|                       |                      |
     |      (< 10ms total)         |                       |                      |
```

### 2️⃣ Spend Tracking Flow

```
Winner Notification           Pacer Service              Redis              PostgreSQL
     |                             |                       |                      |
     |------Spend Update---------->|                       |                      |
     |  {campaign_id, spend_cents} |                       |                      |
     |                             |                       |                      |
     |                             |---INCR daily:camp-001->|                      |
     |                             |---INCR hourly:camp-001>|                      |
     |                             |                       |                      |
     |                             |----Store for History------------------------>|
     |                             |                       |                      |
     |<---------ACK----------------|                       |                      |
```

### 3️⃣ Circuit Breaker Trip Flow (at 95% threshold)

```
High Spending Period         Pacer Service          Circuit Breaker         Redis
     |                             |                      |                   |
     |------Bid Request----------->|                      |                   |
     |                             |--Get Spent---------->|                   |
     |                             |<----$9,501-----------|                   |
     |                             |                      |                   |
     |                             |--Check: 95.01% > 95%->|                   |
     |                             |<-------TRIP!---------|                   |
     |                             |   State → OPEN       |                   |
     |                             |                      |                   |
     |<------DENY BID--------------|                      |                   |
     |   "Circuit breaker open"    |                      |                   |
     |                             |                      |                   |
     === 30 seconds later ===      |                      |                   |
     |                             |--Timer Expired------>|                   |
     |                             |<--State → HALF_OPEN--|                   |
     |                             |                      |                   |
     |------Test Request---------->|                      |                   |
     |                             |--Allow 1 test bid--->|                   |
     |<------ALLOW (throttled)-----|                      |                   |
     |                             |                      |                   |
     |------Another Request------->|                      |                   |
     |                             |--Success count = 2--->|                   |
     |                             |<--State → CLOSED-----|                   |
     |<------ALLOW (90% throttle)--|                      |                   |
```

### 4️⃣ Redis Failover Flow

```
Normal Operation            Redis Fails              Degraded Mode           Redis Recovers
     |                          |                         |                        |
     |---Bid Request-->        |                         |                        |
     |<--Use Redis Data--       |                         |                        |
     |                          |                         |                        |
     |                     [Redis Down]                   |                        |
     |                          |                         |                        |
     |                          |---Bid Request---------->|                        |
     |                          |--Redis Timeout (100ms)->|                        |
     |                          |<--Switch to Memory------|                        |
     |                          |<--Conservative Decision-|                        |
     |                          |   (50% throttle)        |                        |
     |                          |                         |                        |
     |                          |---Track in Memory------>|                        |
     |                          |   {camp-001: $500}      |                        |
     |                          |                         |                        |
     |                          |                    [Redis Back Up]               |
     |                          |                         |----Health Check OK---->|
     |                          |                         |<---Sync Memory Data--->|
     |                          |                         |    MSET operations     |
     |                          |                         |<---Normal Mode-------->|
```

## 🎯 Component Responsibilities

### Pacer Service (Go) - Core Engine
```
Responsibilities:
├── Make bid decisions in < 10ms
├── Track spending in real-time
├── Enforce budget limits via circuit breaker
├── Implement 4 pacing algorithms
├── Handle 10,000+ QPS
└── Gracefully degrade during failures

Key Files:
├── /pacer-service/pacer/algorithm.go     - Pacing algorithms
├── /pacer-service/pacer/circuitbreaker.go - Circuit breaker logic
├── /pacer-service/pacer/tracker.go        - Spend tracking
└── /pacer-service/pacer/service.go        - HTTP handlers
```

### FastAPI (Python) - Management Layer
```
Responsibilities:
├── Campaign CRUD operations
├── Budget configuration
├── Historical analytics
├── Dashboard data API
└── Administrative functions

Endpoints:
├── GET    /campaigns              - List all campaigns
├── POST   /campaigns              - Create campaign
├── PUT    /campaigns/{id}         - Update campaign
├── DELETE /campaigns/{id}         - Delete campaign
└── GET    /budget/status/{id}     - Get budget status
└── GET    /analytics/performance  - Performance metrics
```

### Redis - Real-time State
```
Data Structure:
├── budget:day:camp-001:2024-01-15    → 450000 (cents spent today)
├── budget:hour:camp-001:2024-01-15-14 → 25000 (cents this hour)
├── throttle:camp-001                  → 0.25 (current throttle rate)
└── cb:state:camp-001                  → "OPEN" (circuit breaker state)

TTL Strategy:
├── Daily keys:  24 hours
├── Hourly keys: 2 hours
└── State keys:  1 hour
```

### PostgreSQL - Persistent Storage
```
Tables:
├── campaigns
│   ├── id (UUID)
│   ├── name
│   ├── daily_budget_cents
│   ├── total_budget_cents
│   ├── pacing_algorithm
│   ├── start_date
│   └── end_date
│
├── spend_history
│   ├── campaign_id
│   ├── timestamp
│   ├── spend_cents
│   └── impressions
│
└── performance_metrics
    ├── campaign_id
    ├── date
    ├── total_spent_cents
    ├── impressions
    ├── avg_latency_ms
    └── throttle_rate
```

## 📈 Performance Characteristics

### Latency Breakdown (P99 < 10ms requirement)
```
Operation                Time Budget
─────────────────────────────────────
Redis GET                    1ms
Circuit Breaker Check        0.1ms
Algorithm Calculation        0.5ms
JSON Parse/Response          0.5ms
Network RTT                  2ms
Buffer/Overhead             5.9ms
─────────────────────────────────────
TOTAL P99                   <10ms ✓
```

### Throughput Capacity
```
Component            Capacity    Bottleneck
─────────────────────────────────────────
Pacer Service        50,000 QPS  CPU
Redis               100,000 QPS  Network I/O
PostgreSQL           5,000 QPS   Disk I/O
Nginx               75,000 QPS   CPU
─────────────────────────────────────────
System Max          ~50,000 QPS  (Pacer CPU)
```

## 🔒 Failure Scenarios & Recovery

### Scenario 1: Redis Failure
```
Detection: Health check timeout (100ms)
Action:    Switch to in-memory cache
Impact:    Conservative pacing (50% throttle)
Recovery:  Auto-sync when Redis returns
Data Loss: None (memory preserved)
```

### Scenario 2: Circuit Breaker Trip
```
Trigger:   95% of daily budget spent
Action:    DENY all bids for 30 seconds
Recovery:  HALF_OPEN → test 2 bids → CLOSED
Impact:    Temporary bid blocking
Purpose:   Prevent budget overrun
```

### Scenario 3: PostgreSQL Failure
```
Detection: Connection timeout
Impact:    Cannot load new campaigns
Fallback:  Use cached campaign data
Recovery:  Reconnect and reload
Critical:  Existing campaigns continue
```

### Scenario 4: High Load Spike
```
Detection: Latency > 10ms
Action:    Increase throttle rate
Method:    Adaptive algorithm adjusts
Recovery:  Reduce throttle as load drops
Protection: Circuit breaker as last resort
```

## 🚀 Scaling Strategy

### Horizontal Scaling
```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Pacer #1   │     │  Pacer #2   │     │  Pacer #3   │
│  Port 8080  │     │  Port 8081  │     │  Port 8082  │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────┬───┴───────────────────┘
                       │
              ┌────────▼────────┐
              │   Shared Redis  │
              │   Cluster       │
              └─────────────────┘
```

### Sharding Strategy
```
Campaign ID Hash → Shard Selection
├── Shard 1: Campaigns 0-33%
├── Shard 2: Campaigns 34-66%
└── Shard 3: Campaigns 67-100%
```

This comprehensive diagram shows how all components interact to deliver sub-10ms bid decisions while preventing budget overspending through circuit breakers and intelligent pacing algorithms.