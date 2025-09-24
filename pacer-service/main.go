package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"time"

	"github.com/ad-budget-pacer/pacer-service/pacer"
	"github.com/gorilla/mux"
	_ "github.com/lib/pq"
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	log "github.com/sirupsen/logrus"
)

var (
	requestDuration = prometheus.NewHistogramVec(
		prometheus.HistogramOpts{
			Name:    "pacer_request_duration_seconds",
			Help:    "Duration of HTTP requests",
			Buckets: prometheus.DefBuckets,
		},
		[]string{"endpoint", "method"},
	)
	
	budgetUtilization = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "pacer_budget_utilization_percentage",
			Help: "Current budget utilization percentage",
		},
		[]string{"campaign_id"},
	)
	
	circuitBreakerState = prometheus.NewGaugeVec(
		prometheus.GaugeOpts{
			Name: "pacer_circuit_breaker_state",
			Help: "Circuit breaker state (0=closed, 1=open, 2=half-open)",
		},
		[]string{"campaign_id"},
	)
)

func init() {
	prometheus.MustRegister(requestDuration)
	prometheus.MustRegister(budgetUtilization)
	prometheus.MustRegister(circuitBreakerState)
}

type Server struct {
	tracker        *pacer.BudgetTracker
	circuitBreaker *pacer.CircuitBreakerManager
	db             *sql.DB
	campaigns      map[string]*Campaign
}

type Campaign struct {
	ID          string           `json:"id"`
	Name        string           `json:"name"`
	DailyBudget int64            `json:"daily_budget_cents"`
	PacingMode  pacer.PacingMode `json:"pacing_mode"`
	Status      string           `json:"status"`
}

type PacingDecisionRequest struct {
	CampaignID string `json:"campaign_id"`
	BidCents   int64  `json:"bid_cents"`
}

type PacingDecisionResponse struct {
	AllowBid      bool    `json:"allow_bid"`
	MaxBidCents   int64   `json:"max_bid_cents"`
	ThrottleRate  float64 `json:"throttle_rate"`
	Reason        string  `json:"reason"`
	Warning       string  `json:"warning,omitempty"` // Only set in degraded mode
}

type SpendTrackRequest struct {
	CampaignID  string `json:"campaign_id"`
	SpendCents  int64  `json:"spend_cents"`
	Impressions int    `json:"impressions"`
}

func NewServer(redisAddr, dbConnStr string) (*Server, error) {
	db, err := sql.Open("postgres", dbConnStr)
	if err != nil {
		return nil, fmt.Errorf("failed to connect to database: %w", err)
	}
	
	if err := db.Ping(); err != nil {
		return nil, fmt.Errorf("failed to ping database: %w", err)
	}
	
	tracker := pacer.NewBudgetTracker(redisAddr)
	cbManager := pacer.NewCircuitBreakerManager()
	
	server := &Server{
		tracker:        tracker,
		circuitBreaker: cbManager,
		db:             db,
		campaigns:      make(map[string]*Campaign),
	}
	
	if err := server.loadCampaigns(); err != nil {
		log.WithError(err).Warn("Failed to load campaigns")
	}
	
	return server, nil
}

func (s *Server) loadCampaigns() error {
	rows, err := s.db.Query(`
		SELECT id, name, daily_budget_cents, pacing_mode, status 
		FROM campaigns 
		WHERE status = 'ACTIVE'
	`)
	if err != nil {
		return err
	}
	defer rows.Close()
	
	for rows.Next() {
		var campaign Campaign
		err := rows.Scan(&campaign.ID, &campaign.Name, &campaign.DailyBudget, 
			&campaign.PacingMode, &campaign.Status)
		if err != nil {
			log.WithError(err).Error("Failed to scan campaign")
			continue
		}
		s.campaigns[campaign.ID] = &campaign
	}
	
	return nil
}

func (s *Server) handlePacingDecision(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	defer func() {
		requestDuration.WithLabelValues("/pacing/decision", r.Method).Observe(time.Since(start).Seconds())
	}()
	
	var req PacingDecisionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}
	
	campaign, exists := s.campaigns[req.CampaignID]
	if !exists {
		response := PacingDecisionResponse{
			AllowBid: false,
			Reason:   "campaign_not_found",
		}
		json.NewEncoder(w).Encode(response)
		return
	}
	
	ctx := r.Context()
	status, err := s.tracker.GetBudgetStatus(ctx, req.CampaignID, campaign.DailyBudget)
	if err != nil {
		log.WithError(err).Error("Failed to get budget status")
		http.Error(w, "Internal error", http.StatusInternalServerError)
		return
	}
	
	status.PacingMode = campaign.PacingMode
	
	if !s.circuitBreaker.CheckAndTrip(ctx, status) {
		response := PacingDecisionResponse{
			AllowBid: false,
			Reason:   "circuit_breaker_open",
		}
		json.NewEncoder(w).Encode(response)
		return
	}
	
	algo := pacer.GetPacingAlgorithm(campaign.PacingMode)
	throttleRate := algo.CalculateThrottle(status)
	shouldBid := algo.ShouldBid(status)
	
	remaining := campaign.DailyBudget - status.DailySpent
	maxBid := algo.GetMaxBid(remaining, req.BidCents)
	
	if maxBid < req.BidCents && shouldBid {
		shouldBid = maxBid > 0
	}
	
	response := PacingDecisionResponse{
		AllowBid:     shouldBid,
		MaxBidCents:  maxBid,
		ThrottleRate: throttleRate,
		Reason:       "within_budget",
	}
	
	if !shouldBid {
		if status.CircuitBreakerOn {
			response.Reason = "circuit_breaker"
		} else if remaining <= 0 {
			response.Reason = "budget_exhausted"
		} else {
			response.Reason = "throttled"
		}
	}
	
	budgetUtilization.WithLabelValues(req.CampaignID).Set(status.GetSpendPercentage())
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *Server) handleSpendTrack(w http.ResponseWriter, r *http.Request) {
	start := time.Now()
	defer func() {
		requestDuration.WithLabelValues("/spend/track", r.Method).Observe(time.Since(start).Seconds())
	}()
	
	var req SpendTrackRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request", http.StatusBadRequest)
		return
	}
	
	ctx := r.Context()
	if err := s.tracker.TrackSpend(ctx, req.CampaignID, req.SpendCents); err != nil {
		log.WithError(err).Error("Failed to track spend")
		http.Error(w, "Failed to track spend", http.StatusInternalServerError)
		return
	}
	
	go s.logSpendAsync(req)
	
	breaker := s.circuitBreaker.GetBreaker(req.CampaignID)
	breaker.RecordSuccess()
	
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "success"})
}

func (s *Server) handleBudgetStatus(w http.ResponseWriter, r *http.Request) {
	vars := mux.Vars(r)
	campaignID := vars["campaign_id"]
	
	campaign, exists := s.campaigns[campaignID]
	if !exists {
		http.Error(w, "Campaign not found", http.StatusNotFound)
		return
	}
	
	ctx := r.Context()
	status, err := s.tracker.GetBudgetStatus(ctx, campaignID, campaign.DailyBudget)
	if err != nil {
		log.WithError(err).Error("Failed to get budget status")
		http.Error(w, "Internal error", http.StatusInternalServerError)
		return
	}
	
	breaker := s.circuitBreaker.GetBreaker(campaignID)
	cbState := breaker.GetState()
	
	response := map[string]interface{}{
		"campaign_id":          campaignID,
		"daily_budget_cents":   campaign.DailyBudget,
		"daily_spent_cents":    status.DailySpent,
		"hourly_spent_cents":   status.HourlySpent,
		"pace_percentage":      status.GetSpendPercentage(),
		"should_throttle":      status.ThrottleRate > 0,
		"throttle_rate":        status.ThrottleRate,
		"circuit_breaker_open": cbState == pacer.OPEN,
		"circuit_breaker_state": string(cbState),
	}
	
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

func (s *Server) handleHealthCheck(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func (s *Server) logSpendAsync(req SpendTrackRequest) {
	_, err := s.db.Exec(`
		INSERT INTO spend_log (campaign_id, amount_cents, impressions, hour_bucket, day_bucket)
		VALUES ($1, $2, $3, $4, $5)
	`, req.CampaignID, req.SpendCents, req.Impressions, 
		time.Now().Truncate(time.Hour), time.Now().Truncate(24*time.Hour))
	
	if err != nil {
		log.WithError(err).Error("Failed to log spend to database")
	}
}

func (s *Server) refreshCampaigns() {
	ticker := time.NewTicker(1 * time.Minute)
	defer ticker.Stop()
	
	for range ticker.C {
		if err := s.loadCampaigns(); err != nil {
			log.WithError(err).Error("Failed to refresh campaigns")
		}
	}
}

func main() {
	redisAddr := getEnv("REDIS_ADDR", "localhost:6379")
	dbConnStr := getEnv("DATABASE_URL", "postgres://postgres:postgres@localhost/budget_pacer?sslmode=disable")
	port := getEnv("PORT", "8080")
	
	log.SetFormatter(&log.JSONFormatter{})
	log.SetLevel(log.InfoLevel)
	
	server, err := NewServer(redisAddr, dbConnStr)
	if err != nil {
		log.Fatal(err)
	}
	
	go server.refreshCampaigns()
	
	router := mux.NewRouter()
	
	router.HandleFunc("/pacing/decision", server.handlePacingDecision).Methods("POST")
	router.HandleFunc("/spend/track", server.handleSpendTrack).Methods("POST")
	router.HandleFunc("/budget/status/{campaign_id}", server.handleBudgetStatus).Methods("GET")
	router.HandleFunc("/health", server.handleHealthCheck).Methods("GET")
	router.Handle("/metrics", promhttp.Handler())
	
	router.Use(loggingMiddleware)
	router.Use(corsMiddleware)
	
	log.Infof("Starting pacer service on port %s", port)
	if err := http.ListenAndServe(":"+port, router); err != nil {
		log.Fatal(err)
	}
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		next.ServeHTTP(w, r)
		log.WithFields(log.Fields{
			"method":   r.Method,
			"path":     r.URL.Path,
			"duration": time.Since(start),
		}).Debug("Request processed")
	})
}

func corsMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		
		if r.Method == "OPTIONS" {
			w.WriteHeader(http.StatusOK)
			return
		}
		
		next.ServeHTTP(w, r)
	})
}

func getEnv(key, defaultValue string) string {
	if value, exists := os.LookupEnv(key); exists {
		return value
	}
	return defaultValue
}