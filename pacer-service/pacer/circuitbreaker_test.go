package pacer

import (
	"testing"
	"time"
)

func TestCircuitBreaker_Normal(t *testing.T) {
	cb := NewCircuitBreaker(0.95, 30*time.Second, 2)
	
	// Test normal operation
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		PacePercentage: 50.0,
	}
	
	if !cb.Allow(status) {
		t.Error("Expected circuit breaker to allow at 50% spend")
	}
	
	if cb.State() != "CLOSED" {
		t.Errorf("Expected CLOSED state, got %s", cb.State())
	}
}

func TestCircuitBreaker_Trip(t *testing.T) {
	cb := NewCircuitBreaker(0.95, 30*time.Second, 2)
	
	// Test trip at threshold
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     9600,
		PacePercentage: 96.0,
	}
	
	if cb.Allow(status) {
		t.Error("Expected circuit breaker to deny at 96% spend")
	}
	
	if cb.State() != "OPEN" {
		t.Errorf("Expected OPEN state after trip, got %s", cb.State())
	}
}

func TestCircuitBreaker_Recovery(t *testing.T) {
	cb := NewCircuitBreaker(0.95, 100*time.Millisecond, 2)
	
	// Trip the breaker
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     9600,
		PacePercentage: 96.0,
	}
	
	cb.Allow(status)
	if cb.State() != "OPEN" {
		t.Fatal("Failed to trip circuit breaker")
	}
	
	// Wait for timeout
	time.Sleep(150 * time.Millisecond)
	
	// Update status to below threshold
	status.DailySpent = 9000
	status.PacePercentage = 90.0
	
	// First call should move to HALF_OPEN
	cb.Allow(status)
	
	// After success threshold, should be CLOSED
	cb.Allow(status)
	cb.Allow(status)
	
	if cb.State() == "OPEN" {
		t.Error("Expected circuit breaker to recover from OPEN state")
	}
}

func BenchmarkCircuitBreakerAllow(b *testing.B) {
	cb := NewCircuitBreaker(0.95, 30*time.Second, 2)
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		PacePercentage: 50.0,
	}
	
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		cb.Allow(status)
	}
}