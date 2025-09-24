package main

import (
	"encoding/json"
	"fmt"
	"log"
	"math/rand"
	"net/http"
	"time"
)

type PacingDecisionRequest struct {
	CampaignID string `json:"campaign_id"`
	BidCents   int64  `json:"bid_cents"`
}

type PacingDecisionResponse struct {
	AllowBid     bool    `json:"allow_bid"`
	MaxBidCents  int64   `json:"max_bid_cents"`
	ThrottleRate float64 `json:"throttle_rate"`
	Reason       string  `json:"reason"`
}

type SpendTrackRequest struct {
	CampaignID  string `json:"campaign_id"`
	SpendCents  int64  `json:"spend_cents"`
	Impressions int    `json:"impressions"`
}

type BudgetStatus struct {
	CampaignID         string  `json:"campaign_id"`
	DailyBudgetCents   int64   `json:"daily_budget_cents"`
	DailySpentCents    int64   `json:"daily_spent_cents"`
	HourlySpentCents   int64   `json:"hourly_spent_cents"`
	PacePercentage     float64 `json:"pace_percentage"`
	ShouldThrottle     bool    `json:"should_throttle"`
	ThrottleRate       float64 `json:"throttle_rate"`
	CircuitBreakerOpen bool    `json:"circuit_breaker_open"`
	CircuitBreakerState string `json:"circuit_breaker_state"`
}

var (
	campaigns = map[string]*BudgetStatus{
		"camp-001": {
			CampaignID:       "camp-001",
			DailyBudgetCents: 1000000,
			DailySpentCents:  450000,
			HourlySpentCents: 25000,
			CircuitBreakerState: "CLOSED",
		},
		"camp-002": {
			CampaignID:       "camp-002",
			DailyBudgetCents: 500000,
			DailySpentCents:  200000,
			HourlySpentCents: 15000,
			CircuitBreakerState: "CLOSED",
		},
		"camp-003": {
			CampaignID:       "camp-003",
			DailyBudgetCents: 2000000,
			DailySpentCents:  1900000,
			HourlySpentCents: 10000,
			CircuitBreakerState: "OPEN",
		},
	}
)

func handlePacingDecision(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	
	var req PacingDecisionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}
	
	// Simulate processing time (3-8ms)
	time.Sleep(time.Duration(3+rand.Intn(5)) * time.Millisecond)
	
	campaign, exists := campaigns[req.CampaignID]
	if !exists {
		campaign = &BudgetStatus{
			CampaignID:       req.CampaignID,
			DailyBudgetCents: 100000,
			DailySpentCents:  rand.Int63n(90000),
			CircuitBreakerState: "CLOSED",
		}
		campaigns[req.CampaignID] = campaign
	}
	
	spendPercentage := float64(campaign.DailySpentCents) / float64(campaign.DailyBudgetCents) * 100
	
	// Circuit breaker logic
	if spendPercentage >= 95 {
		campaign.CircuitBreakerState = "OPEN"
		campaign.CircuitBreakerOpen = true
	}
	
	// Throttle calculation
	throttleRate := 0.0
	if spendPercentage > 80 {
		throttleRate = (spendPercentage - 80) / 20
	}
	
	allowBid := campaign.CircuitBreakerState != "OPEN" && rand.Float64() > throttleRate
	
	response := PacingDecisionResponse{
		AllowBid:     allowBid,
		MaxBidCents:  req.BidCents,
		ThrottleRate: throttleRate,
		Reason:       "within_budget",
	}
	
	if !allowBid {
		if campaign.CircuitBreakerState == "OPEN" {
			response.Reason = "circuit_breaker_open"
		} else {
			response.Reason = "throttled"
		}
	}
	
	log.Printf("Decision for %s: %v (%.2fms)", req.CampaignID, allowBid, 
		time.Since(start).Seconds()*1000)
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func handleSpendTrack(w http.ResponseWriter, r *http.Request) {
	var req SpendTrackRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}
	
	if campaign, exists := campaigns[req.CampaignID]; exists {
		campaign.DailySpentCents += req.SpendCents
		campaign.HourlySpentCents += req.SpendCents
	}
	
	log.Printf("Tracked spend for %s: $%.2f", req.CampaignID, float64(req.SpendCents)/100)
	
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "success"})
}

func handleBudgetStatus(w http.ResponseWriter, r *http.Request) {
	campaignID := r.URL.Path[len("/budget/status/"):]
	
	campaign, exists := campaigns[campaignID]
	if !exists {
		campaign = &BudgetStatus{
			CampaignID:       campaignID,
			DailyBudgetCents: 100000,
			DailySpentCents:  45000,
			CircuitBreakerState: "CLOSED",
		}
		campaigns[campaignID] = campaign
	}
	
	campaign.PacePercentage = float64(campaign.DailySpentCents) / float64(campaign.DailyBudgetCents) * 100
	campaign.ThrottleRate = 0.0
	if campaign.PacePercentage > 80 {
		campaign.ThrottleRate = (campaign.PacePercentage - 80) / 20
	}
	campaign.ShouldThrottle = campaign.ThrottleRate > 0
	campaign.CircuitBreakerOpen = campaign.CircuitBreakerState == "OPEN"
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(campaign)
}

func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{
		"status": "healthy",
		"service": "pacer-service-mock",
	})
}

func handleMetrics(w http.ResponseWriter, r *http.Request) {
	metrics := fmt.Sprintf(`# HELP pacer_request_duration_seconds Duration of HTTP requests
# TYPE pacer_request_duration_seconds histogram
pacer_request_duration_seconds_count{endpoint="/pacing/decision"} %d
pacer_request_duration_seconds_sum{endpoint="/pacing/decision"} %.3f
pacer_budget_utilization_percentage{campaign_id="camp-001"} %.1f
pacer_circuit_breaker_state{campaign_id="camp-001"} 0
`, rand.Intn(10000), rand.Float64()*100, 45.0)
	
	w.Header().Set("Content-Type", "text/plain")
	w.Write([]byte(metrics))
}

func enableCORS(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		
		next(w, r)
	}
}

func main() {
	rand.Seed(time.Now().UnixNano())
	
	http.HandleFunc("/pacing/decision", enableCORS(handlePacingDecision))
	http.HandleFunc("/spend/track", enableCORS(handleSpendTrack))
	http.HandleFunc("/budget/status/", enableCORS(handleBudgetStatus))
	http.HandleFunc("/health", enableCORS(handleHealth))
	http.HandleFunc("/metrics", enableCORS(handleMetrics))
	
	port := "8080"
	log.Printf("Mock Pacer Service starting on port %s", port)
	log.Printf("This is a simplified version for testing - not the full implementation")
	
	if err := http.ListenAndServe(":"+port, nil); err != nil {
		log.Fatal(err)
	}
}