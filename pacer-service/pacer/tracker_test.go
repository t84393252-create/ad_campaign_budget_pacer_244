package pacer

import (
	"context"
	"testing"
	"time"
)

func TestBudgetTracker_InMemory(t *testing.T) {
	tracker := NewBudgetTracker(nil, nil)
	ctx := context.Background()
	
	// Test tracking spend
	err := tracker.TrackSpend(ctx, "test-campaign", 1000, 10)
	if err != nil {
		t.Fatalf("Failed to track spend: %v", err)
	}
	
	// Test getting status
	status, err := tracker.GetStatus(ctx, "test-campaign")
	if err != nil {
		t.Fatalf("Failed to get status: %v", err)
	}
	
	if status.DailySpent != 1000 {
		t.Errorf("Expected daily spent 1000, got %d", status.DailySpent)
	}
}

func TestBudgetTracker_RateLimit(t *testing.T) {
	tracker := NewBudgetTracker(nil, nil)
	
	// Initialize rate limiter for campaign
	tracker.rateLimiters["test-campaign"] = &RateLimiter{
		tokens:       10,
		maxTokens:    100,
		refillRate:   10,
		lastRefill:   time.Now(),
	}
	
	allowed := tracker.CheckRateLimit("test-campaign", 5)
	if !allowed {
		t.Error("Expected rate limit to allow 5 tokens")
	}
	
	allowed = tracker.CheckRateLimit("test-campaign", 20)
	if allowed {
		t.Error("Expected rate limit to deny 20 tokens")
	}
}

func TestBudgetStatus_Calculations(t *testing.T) {
	status := &BudgetStatus{
		DailyBudget:  10000,
		DailySpent:   5000,
		HourlyBudget: 1000,
		HourlySpent:  300,
	}
	
	// Update pace percentage
	status.PacePercentage = float64(status.DailySpent) / float64(status.DailyBudget) * 100
	
	if status.PacePercentage != 50.0 {
		t.Errorf("Expected pace percentage 50.0, got %f", status.PacePercentage)
	}
	
	remaining := status.DailyBudget - status.DailySpent
	if remaining != 5000 {
		t.Errorf("Expected remaining budget 5000, got %d", remaining)
	}
}

func BenchmarkTrackSpend(b *testing.B) {
	tracker := NewBudgetTracker(nil, nil)
	ctx := context.Background()
	
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		tracker.TrackSpend(ctx, "bench-campaign", 100, 1)
	}
}