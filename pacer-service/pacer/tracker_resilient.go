package pacer

import (
	"context"
	"fmt"
	"strconv"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"
	log "github.com/sirupsen/logrus"
)

// MemoryBudget stores in-memory budget tracking
type MemoryBudget struct {
	DailySpent   int64
	HourlySpent  int64
	LastUpdate   time.Time
	CurrentHour  int
}

// ResilientBudgetTracker extends BudgetTracker with fallback capabilities
type ResilientBudgetTracker struct {
	redisClient    *redis.Client
	memoryCache    map[string]*MemoryBudget
	mu             sync.RWMutex
	degradedMode   bool
	lastRedisCheck time.Time
	redisHealthy   bool
	campaigns      map[string]int64 // campaign budgets for fallback
	recoveryQueue  map[string]*MemoryBudget // data pending sync to Redis
	recoveryMu     sync.Mutex
}

// NewResilientBudgetTracker creates a tracker with Redis failure handling
func NewResilientBudgetTracker(redisAddr string) *ResilientBudgetTracker {
	rdb := redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		Password:     "",
		DB:           0,
		PoolSize:     100,
		MinIdleConns: 10,
		MaxRetries:   2,
		DialTimeout:  1 * time.Second,
		ReadTimeout:  1 * time.Second,
		WriteTimeout: 1 * time.Second,
	})

	tracker := &ResilientBudgetTracker{
		redisClient:   rdb,
		memoryCache:   make(map[string]*MemoryBudget),
		campaigns:     make(map[string]int64),
		recoveryQueue: make(map[string]*MemoryBudget),
		redisHealthy:  true,
	}

	// Start recovery goroutine
	go tracker.autoRecoveryLoop()
	
	// Start Redis health checker
	go tracker.healthCheckLoop()

	return tracker
}

// SetCampaignBudgets updates known campaign budgets for fallback mode
func (bt *ResilientBudgetTracker) SetCampaignBudgets(campaigns map[string]int64) {
	bt.mu.Lock()
	defer bt.mu.Unlock()
	bt.campaigns = campaigns
}

// TrackSpend tracks spending with fallback to memory if Redis fails
func (bt *ResilientBudgetTracker) TrackSpend(ctx context.Context, campaignID string, amount int64) error {
	now := time.Now()
	
	// Always update memory cache first
	bt.updateMemoryCache(campaignID, amount, now)
	
	// Try to update Redis asynchronously
	go bt.asyncRedisUpdate(campaignID, amount, now)
	
	return nil // Never fail on tracking
}

// updateMemoryCache updates the in-memory cache
func (bt *ResilientBudgetTracker) updateMemoryCache(campaignID string, amount int64, now time.Time) {
	bt.mu.Lock()
	defer bt.mu.Unlock()
	
	budget, exists := bt.memoryCache[campaignID]
	if !exists {
		budget = &MemoryBudget{
			CurrentHour: now.Hour(),
			LastUpdate:  now,
		}
		bt.memoryCache[campaignID] = budget
	}
	
	// Reset hourly if hour changed
	if budget.CurrentHour != now.Hour() {
		budget.HourlySpent = 0
		budget.CurrentHour = now.Hour()
	}
	
	budget.DailySpent += amount
	budget.HourlySpent += amount
	budget.LastUpdate = now
	
	// Add to recovery queue if in degraded mode
	if bt.degradedMode {
		bt.recoveryMu.Lock()
		bt.recoveryQueue[campaignID] = budget
		bt.recoveryMu.Unlock()
	}
}

// asyncRedisUpdate tries to update Redis without blocking
func (bt *ResilientBudgetTracker) asyncRedisUpdate(campaignID string, amount int64, now time.Time) {
	if !bt.redisHealthy {
		return // Skip if we know Redis is down
	}
	
	ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
	defer cancel()
	
	dayKey := bt.getDayKey(campaignID, now)
	hourKey := bt.getHourKey(campaignID, now)
	totalKey := bt.getTotalKey(campaignID)
	
	pipe := bt.redisClient.Pipeline()
	pipe.IncrBy(ctx, dayKey, amount)
	pipe.Expire(ctx, dayKey, 25*time.Hour)
	pipe.IncrBy(ctx, hourKey, amount)
	pipe.Expire(ctx, hourKey, 2*time.Hour)
	pipe.IncrBy(ctx, totalKey, amount)
	pipe.Expire(ctx, totalKey, 30*24*time.Hour)
	
	if _, err := pipe.Exec(ctx); err != nil {
		bt.handleRedisFailure(err)
	}
}

// GetBudgetStatus gets status with fallback to memory cache
func (bt *ResilientBudgetTracker) GetBudgetStatus(ctx context.Context, campaignID string, dailyBudget int64) (*BudgetStatus, error) {
	now := time.Now()
	
	// Try Redis first if healthy
	if bt.redisHealthy {
		status, err := bt.getFromRedis(ctx, campaignID, dailyBudget, now)
		if err == nil {
			// Update memory cache with Redis data
			bt.syncToMemory(campaignID, status)
			return status, nil
		}
		bt.handleRedisFailure(err)
	}
	
	// Fallback to memory cache
	return bt.getFromMemory(campaignID, dailyBudget, now), nil
}

// getFromRedis attempts to get budget status from Redis
func (bt *ResilientBudgetTracker) getFromRedis(ctx context.Context, campaignID string, dailyBudget int64, now time.Time) (*BudgetStatus, error) {
	dayKey := bt.getDayKey(campaignID, now)
	hourKey := bt.getHourKey(campaignID, now)
	
	pipe := bt.redisClient.Pipeline()
	dayCmd := pipe.Get(ctx, dayKey)
	hourCmd := pipe.Get(ctx, hourKey)
	
	if _, err := pipe.Exec(ctx); err != nil && err != redis.Nil {
		return nil, err
	}
	
	var dailySpent, hourlySpent int64
	if dayCmd.Val() != "" {
		dailySpent, _ = strconv.ParseInt(dayCmd.Val(), 10, 64)
	}
	if hourCmd.Val() != "" {
		hourlySpent, _ = strconv.ParseInt(hourCmd.Val(), 10, 64)
	}
	
	return &BudgetStatus{
		CampaignID:     campaignID,
		DailyBudget:    dailyBudget,
		DailySpent:     dailySpent,
		HourlyBudget:   dailyBudget / 24,
		HourlySpent:    hourlySpent,
		RemainingHours: 24 - now.Hour(),
		CurrentHour:    now.Hour(),
		ThrottleRate:   0.0,
		DegradedMode:   false,
	}, nil
}

// getFromMemory creates budget status from memory cache
func (bt *ResilientBudgetTracker) getFromMemory(campaignID string, dailyBudget int64, now time.Time) *BudgetStatus {
	bt.mu.RLock()
	defer bt.mu.RUnlock()
	
	// Get from memory cache
	if budget, exists := bt.memoryCache[campaignID]; exists {
		// Reset hourly if hour changed
		hourlySpent := budget.HourlySpent
		if budget.CurrentHour != now.Hour() {
			hourlySpent = 0
		}
		
		return &BudgetStatus{
			CampaignID:     campaignID,
			DailyBudget:    dailyBudget,
			DailySpent:     budget.DailySpent,
			HourlyBudget:   dailyBudget / 24,
			HourlySpent:    hourlySpent,
			RemainingHours: 24 - now.Hour(),
			CurrentHour:    now.Hour(),
			ThrottleRate:   0.5, // Conservative throttle in degraded mode
			DegradedMode:   true,
		}
	}
	
	// No cache - return conservative estimate
	hoursPassed := now.Hour()
	assumedSpent := (dailyBudget * int64(hoursPassed)) / 24
	
	return &BudgetStatus{
		CampaignID:     campaignID,
		DailyBudget:    dailyBudget,
		DailySpent:     assumedSpent,
		HourlyBudget:   dailyBudget / 24,
		HourlySpent:    0,
		RemainingHours: 24 - now.Hour(),
		CurrentHour:    now.Hour(),
		ThrottleRate:   0.7, // Heavy throttle when no data
		DegradedMode:   true,
	}
}

// syncToMemory updates memory cache from Redis data
func (bt *ResilientBudgetTracker) syncToMemory(campaignID string, status *BudgetStatus) {
	bt.mu.Lock()
	defer bt.mu.Unlock()
	
	bt.memoryCache[campaignID] = &MemoryBudget{
		DailySpent:  status.DailySpent,
		HourlySpent: status.HourlySpent,
		LastUpdate:  time.Now(),
		CurrentHour: status.CurrentHour,
	}
}

// handleRedisFailure marks Redis as unhealthy
func (bt *ResilientBudgetTracker) handleRedisFailure(err error) {
	log.WithError(err).Warn("Redis operation failed, entering degraded mode")
	bt.mu.Lock()
	bt.degradedMode = true
	bt.redisHealthy = false
	bt.mu.Unlock()
}

// healthCheckLoop periodically checks Redis health
func (bt *ResilientBudgetTracker) healthCheckLoop() {
	ticker := time.NewTicker(5 * time.Second)
	defer ticker.Stop()
	
	for range ticker.C {
		ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
		err := bt.redisClient.Ping(ctx).Err()
		cancel()
		
		bt.mu.Lock()
		wasUnhealthy := !bt.redisHealthy
		bt.redisHealthy = (err == nil)
		bt.mu.Unlock()
		
		if wasUnhealthy && bt.redisHealthy {
			log.Info("Redis connection restored")
		}
	}
}

// autoRecoveryLoop attempts to sync memory data back to Redis
func (bt *ResilientBudgetTracker) autoRecoveryLoop() {
	ticker := time.NewTicker(10 * time.Second)
	defer ticker.Stop()
	
	for range ticker.C {
		if !bt.degradedMode || !bt.redisHealthy {
			continue
		}
		
		log.Info("Attempting to recover from degraded mode...")
		if err := bt.syncMemoryToRedis(); err != nil {
			log.WithError(err).Warn("Recovery failed, will retry")
		} else {
			bt.mu.Lock()
			bt.degradedMode = false
			bt.mu.Unlock()
			log.Info("Successfully recovered from degraded mode!")
		}
	}
}

// syncMemoryToRedis syncs accumulated memory data back to Redis
func (bt *ResilientBudgetTracker) syncMemoryToRedis() error {
	bt.recoveryMu.Lock()
	queue := bt.recoveryQueue
	bt.recoveryQueue = make(map[string]*MemoryBudget)
	bt.recoveryMu.Unlock()
	
	if len(queue) == 0 {
		return nil
	}
	
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	
	now := time.Now()
	pipe := bt.redisClient.Pipeline()
	
	for campaignID, budget := range queue {
		dayKey := bt.getDayKey(campaignID, now)
		hourKey := bt.getHourKey(campaignID, now)
		totalKey := bt.getTotalKey(campaignID)
		
		// Set absolute values instead of incrementing
		pipe.Set(ctx, dayKey, budget.DailySpent, 25*time.Hour)
		pipe.Set(ctx, hourKey, budget.HourlySpent, 2*time.Hour)
		pipe.IncrBy(ctx, totalKey, budget.DailySpent)
	}
	
	_, err := pipe.Exec(ctx)
	if err != nil {
		// Put items back in queue
		bt.recoveryMu.Lock()
		for k, v := range queue {
			bt.recoveryQueue[k] = v
		}
		bt.recoveryMu.Unlock()
		return fmt.Errorf("failed to sync to Redis: %w", err)
	}
	
	log.WithField("campaigns_synced", len(queue)).Info("Successfully synced memory cache to Redis")
	return nil
}

// IsHealthy returns true if not in degraded mode
func (bt *ResilientBudgetTracker) IsHealthy() bool {
	bt.mu.RLock()
	defer bt.mu.RUnlock()
	return !bt.degradedMode
}

// GetHealthStatus returns detailed health information
func (bt *ResilientBudgetTracker) GetHealthStatus() map[string]interface{} {
	bt.mu.RLock()
	defer bt.mu.RUnlock()
	
	return map[string]interface{}{
		"redis_healthy":    bt.redisHealthy,
		"degraded_mode":    bt.degradedMode,
		"memory_cache_size": len(bt.memoryCache),
		"recovery_queue":   len(bt.recoveryQueue),
		"last_redis_check": bt.lastRedisCheck,
	}
}

// Helper methods for Redis keys
func (bt *ResilientBudgetTracker) getDayKey(campaignID string, t time.Time) string {
	return fmt.Sprintf("budget:day:%s:%s", campaignID, t.Format("2006-01-02"))
}

func (bt *ResilientBudgetTracker) getHourKey(campaignID string, t time.Time) string {
	return fmt.Sprintf("budget:hour:%s:%s", campaignID, t.Format("2006-01-02-15"))
}

func (bt *ResilientBudgetTracker) getTotalKey(campaignID string) string {
	return fmt.Sprintf("budget:total:%s", campaignID)
}

// GetDegradedDecision makes conservative pacing decisions when in degraded mode
// Note: This function is commented out as the Campaign and PacingDecisionResponse types
// are defined in the main package, not the pacer package. The degraded mode logic
// is handled in the main package's makePacingDecision function.
/*
func GetDegradedDecision(campaign *Campaign, bidCents int64) PacingDecisionResponse {
	hour := time.Now().Hour()
	hoursRemaining := 24 - hour
	
	// Base throttle rate depends on time of day
	var throttleRate float64
	switch {
	case hour < 6 || hour > 22:
		throttleRate = 0.8 // Heavy throttle during off-peak
	case hour >= 9 && hour <= 17:
		throttleRate = 0.4 // Moderate during business hours
	default:
		throttleRate = 0.6
	}
	
	// Conservative max bid
	safeMaxBid := campaign.DailyBudget / int64(hoursRemaining*100)
	if safeMaxBid > bidCents/2 {
		safeMaxBid = bidCents / 2
	}
	
	// Random throttling
	allowBid := rand.Float64() > throttleRate
	
	return PacingDecisionResponse{
		AllowBid:     allowBid,
		MaxBidCents:  safeMaxBid,
		ThrottleRate: throttleRate,
		Reason:       "degraded_mode",
		Warning:      "Operating in degraded mode without real-time spend data",
	}
}
*/