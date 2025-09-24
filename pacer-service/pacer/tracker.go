package pacer

import (
	"context"
	"encoding/json"
	"fmt"
	"strconv"
	"sync"
	"time"

	"github.com/go-redis/redis/v8"
	log "github.com/sirupsen/logrus"
)

type BudgetTracker struct {
	redisClient *redis.Client
	mu          sync.RWMutex
	cache       map[string]*BudgetStatus
	cacheTTL    time.Duration
}

func NewBudgetTracker(redisAddr string) *BudgetTracker {
	rdb := redis.NewClient(&redis.Options{
		Addr:         redisAddr,
		Password:     "",
		DB:           0,
		PoolSize:     100,
		MinIdleConns: 10,
	})

	return &BudgetTracker{
		redisClient: rdb,
		cache:       make(map[string]*BudgetStatus),
		cacheTTL:    5 * time.Second,
	}
}

func (bt *BudgetTracker) TrackSpend(ctx context.Context, campaignID string, amount int64) error {
	now := time.Now()
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

	_, err := pipe.Exec(ctx)
	if err != nil {
		log.WithError(err).Error("Failed to track spend in Redis")
		return err
	}

	bt.invalidateCache(campaignID)

	return nil
}

func (bt *BudgetTracker) GetBudgetStatus(ctx context.Context, campaignID string, dailyBudget int64) (*BudgetStatus, error) {
	bt.mu.RLock()
	if cached, exists := bt.cache[campaignID]; exists {
		if time.Since(cached.LastUpdate()) < bt.cacheTTL {
			bt.mu.RUnlock()
			return cached, nil
		}
	}
	bt.mu.RUnlock()

	now := time.Now()
	dayKey := bt.getDayKey(campaignID, now)
	hourKey := bt.getHourKey(campaignID, now)

	pipe := bt.redisClient.Pipeline()
	dayCmd := pipe.Get(ctx, dayKey)
	hourCmd := pipe.Get(ctx, hourKey)
	_, err := pipe.Exec(ctx)

	var dailySpent, hourlySpent int64

	if err != nil && err != redis.Nil {
		log.WithError(err).Error("Failed to get budget status from Redis")
		return nil, err
	}

	if dayCmd.Val() != "" {
		dailySpent, _ = strconv.ParseInt(dayCmd.Val(), 10, 64)
	}

	if hourCmd.Val() != "" {
		hourlySpent, _ = strconv.ParseInt(hourCmd.Val(), 10, 64)
	}

	status := &BudgetStatus{
		CampaignID:     campaignID,
		DailyBudget:    dailyBudget,
		DailySpent:     dailySpent,
		HourlyBudget:   dailyBudget / 24,
		HourlySpent:    hourlySpent,
		RemainingHours: 24 - now.Hour(),
		CurrentHour:    now.Hour(),
		PacingMode:     EVEN,
	}

	bt.mu.Lock()
	bt.cache[campaignID] = status
	bt.mu.Unlock()

	return status, nil
}

func (bt *BudgetTracker) BatchTrackSpend(ctx context.Context, spends map[string]int64) error {
	if len(spends) == 0 {
		return nil
	}

	now := time.Now()
	pipe := bt.redisClient.Pipeline()

	for campaignID, amount := range spends {
		dayKey := bt.getDayKey(campaignID, now)
		hourKey := bt.getHourKey(campaignID, now)
		totalKey := bt.getTotalKey(campaignID)

		pipe.IncrBy(ctx, dayKey, amount)
		pipe.Expire(ctx, dayKey, 25*time.Hour)
		
		pipe.IncrBy(ctx, hourKey, amount)
		pipe.Expire(ctx, hourKey, 2*time.Hour)
		
		pipe.IncrBy(ctx, totalKey, amount)
		pipe.Expire(ctx, totalKey, 30*24*time.Hour)
	}

	_, err := pipe.Exec(ctx)
	if err != nil {
		log.WithError(err).Error("Failed to batch track spend")
		return err
	}

	for campaignID := range spends {
		bt.invalidateCache(campaignID)
	}

	return nil
}

func (bt *BudgetTracker) ResetDailyBudget(ctx context.Context, campaignID string) error {
	now := time.Now()
	dayKey := bt.getDayKey(campaignID, now)
	
	err := bt.redisClient.Del(ctx, dayKey).Err()
	if err != nil {
		log.WithError(err).Error("Failed to reset daily budget")
		return err
	}

	bt.invalidateCache(campaignID)
	return nil
}

func (bt *BudgetTracker) GetMultipleStatuses(ctx context.Context, campaigns map[string]int64) (map[string]*BudgetStatus, error) {
	results := make(map[string]*BudgetStatus)
	now := time.Now()
	
	pipe := bt.redisClient.Pipeline()
	cmds := make(map[string]*redis.StringCmd)
	
	for campaignID := range campaigns {
		dayKey := bt.getDayKey(campaignID, now)
		hourKey := bt.getHourKey(campaignID, now)
		
		cmds[dayKey] = pipe.Get(ctx, dayKey)
		cmds[hourKey] = pipe.Get(ctx, hourKey)
	}
	
	_, err := pipe.Exec(ctx)
	if err != nil && err != redis.Nil {
		return nil, err
	}
	
	for campaignID, budget := range campaigns {
		dayKey := bt.getDayKey(campaignID, now)
		hourKey := bt.getHourKey(campaignID, now)
		
		var dailySpent, hourlySpent int64
		
		if val := cmds[dayKey].Val(); val != "" {
			dailySpent, _ = strconv.ParseInt(val, 10, 64)
		}
		
		if val := cmds[hourKey].Val(); val != "" {
			hourlySpent, _ = strconv.ParseInt(val, 10, 64)
		}
		
		results[campaignID] = &BudgetStatus{
			CampaignID:     campaignID,
			DailyBudget:    budget,
			DailySpent:     dailySpent,
			HourlyBudget:   budget / 24,
			HourlySpent:    hourlySpent,
			RemainingHours: 24 - now.Hour(),
			CurrentHour:    now.Hour(),
		}
	}
	
	return results, nil
}

func (bt *BudgetTracker) getDayKey(campaignID string, t time.Time) string {
	return fmt.Sprintf("budget:day:%s:%s", campaignID, t.Format("2006-01-02"))
}

func (bt *BudgetTracker) getHourKey(campaignID string, t time.Time) string {
	return fmt.Sprintf("budget:hour:%s:%s", campaignID, t.Format("2006-01-02-15"))
}

func (bt *BudgetTracker) getTotalKey(campaignID string) string {
	return fmt.Sprintf("budget:total:%s", campaignID)
}

func (bt *BudgetTracker) invalidateCache(campaignID string) {
	bt.mu.Lock()
	delete(bt.cache, campaignID)
	bt.mu.Unlock()
}

func (status *BudgetStatus) LastUpdate() time.Time {
	return time.Now()
}

func (status *BudgetStatus) ToJSON() ([]byte, error) {
	return json.Marshal(status)
}

func (status *BudgetStatus) GetSpendPercentage() float64 {
	if status.DailyBudget == 0 {
		return 0
	}
	return float64(status.DailySpent) / float64(status.DailyBudget) * 100
}