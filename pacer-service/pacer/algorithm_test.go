package pacer

import (
	"testing"
)

func TestEvenPacingAlgorithm(t *testing.T) {
	algo := &EvenPacingAlgorithm{}
	
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		HourlyBudget:   1000,
		HourlySpent:    500,
		PacePercentage: 50.0,
	}
	
	throttle := algo.CalculateThrottle(status)
	if throttle != 0.0 {
		t.Errorf("Expected throttle 0.0 for even pacing at 50%%, got %f", throttle)
	}
	
	if !algo.ShouldBid(status) {
		t.Error("Expected bid to be allowed for even pacing at 50%")
	}
	
	maxBid := algo.GetMaxBid(5000, 10000)
	if maxBid != 500 {
		t.Errorf("Expected max bid 500, got %d", maxBid)
	}
}

func TestASAPPacingAlgorithm(t *testing.T) {
	algo := &ASAPPacingAlgorithm{}
	
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		PacePercentage: 50.0,
	}
	
	throttle := algo.CalculateThrottle(status)
	if throttle != 0.0 {
		t.Errorf("Expected throttle 0.0 for ASAP pacing at 50%%, got %f", throttle)
	}
	
	// Test high spend scenario
	status.PacePercentage = 90.0
	throttle = algo.CalculateThrottle(status)
	if throttle <= 0.0 {
		t.Error("Expected positive throttle for ASAP at 90% pace")
	}
}

func TestFrontLoadedPacingAlgorithm(t *testing.T) {
	algo := &FrontLoadedPacingAlgorithm{}
	
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     2000,
		PacePercentage: 20.0,
	}
	
	throttle := algo.CalculateThrottle(status)
	if throttle != 0.0 {
		t.Errorf("Expected no throttle for front-loaded at 20%%, got %f", throttle)
	}
	
	if !algo.ShouldBid(status) {
		t.Error("Expected bid to be allowed for front-loaded pacing at 20%")
	}
}

func TestAdaptivePacingAlgorithm(t *testing.T) {
	algo := &AdaptivePacingAlgorithm{}
	
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		HourlyBudget:   1000,
		HourlySpent:    800,
		PacePercentage: 50.0,
	}
	
	// Test adaptation to high hourly spend
	throttle := algo.CalculateThrottle(status)
	if throttle <= 0.0 {
		t.Error("Expected throttle for adaptive pacing with high hourly spend")
	}
}

func BenchmarkEvenPacingCalculation(b *testing.B) {
	algo := &EvenPacingAlgorithm{}
	status := &BudgetStatus{
		DailyBudget:    10000,
		DailySpent:     5000,
		PacePercentage: 50.0,
	}
	
	b.ResetTimer()
	for i := 0; i < b.N; i++ {
		algo.CalculateThrottle(status)
	}
}