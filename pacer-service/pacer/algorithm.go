package pacer

import (
	"math"
	"math/rand"
)

type PacingMode string

const (
	EVEN         PacingMode = "EVEN"
	ASAP         PacingMode = "ASAP"
	FRONT_LOADED PacingMode = "FRONT_LOADED"
	ADAPTIVE     PacingMode = "ADAPTIVE"
)

type PacingAlgorithm interface {
	CalculateThrottle(status *BudgetStatus) float64
	GetMaxBid(remaining int64, target int64) int64
	ShouldBid(status *BudgetStatus) bool
}

type BudgetStatus struct {
	CampaignID       string
	DailyBudget      int64
	DailySpent       int64
	HourlyBudget     int64
	HourlySpent      int64
	RemainingHours   int
	CurrentHour      int
	PacingMode       PacingMode
	ThrottleRate     float64
	CircuitBreakerOn bool
	DegradedMode     bool   // Operating without real-time Redis data
	Warning          string // Optional warning message for degraded state
}

type BaseAlgorithm struct{}

func (b *BaseAlgorithm) GetMaxBid(remaining int64, target int64) int64 {
	if remaining <= 0 {
		return 0
	}
	maxBid := remaining / 10
	if maxBid > target {
		maxBid = target
	}
	return maxBid
}

type EvenPacing struct {
	BaseAlgorithm
}

func (e *EvenPacing) CalculateThrottle(status *BudgetStatus) float64 {
	if status.CircuitBreakerOn {
		return 1.0
	}
	
	targetSpendRate := float64(status.DailyBudget) / 24.0
	actualSpendRate := float64(status.HourlySpent)
	
	if actualSpendRate == 0 {
		return 0.0
	}
	
	throttleRate := (actualSpendRate - targetSpendRate) / targetSpendRate
	throttleRate = math.Max(0.0, math.Min(1.0, throttleRate))
	
	return throttleRate
}

func (e *EvenPacing) ShouldBid(status *BudgetStatus) bool {
	if status.CircuitBreakerOn {
		return false
	}
	
	remainingBudget := status.DailyBudget - status.DailySpent
	if remainingBudget <= 0 {
		return false
	}
	
	targetHourlySpend := status.DailyBudget / 24
	if status.HourlySpent >= targetHourlySpend {
		return rand.Float64() > status.ThrottleRate
	}
	
	return true
}

type ASAPPacing struct {
	BaseAlgorithm
}

func (a *ASAPPacing) CalculateThrottle(status *BudgetStatus) float64 {
	if status.CircuitBreakerOn {
		return 1.0
	}
	
	spendPercentage := float64(status.DailySpent) / float64(status.DailyBudget)
	
	if spendPercentage >= 0.95 {
		return 0.9
	} else if spendPercentage >= 0.9 {
		return 0.5
	} else if spendPercentage >= 0.8 {
		return 0.2
	}
	
	return 0.0
}

func (a *ASAPPacing) ShouldBid(status *BudgetStatus) bool {
	if status.CircuitBreakerOn {
		return false
	}
	
	remainingBudget := status.DailyBudget - status.DailySpent
	if remainingBudget <= 0 {
		return false
	}
	
	if status.ThrottleRate > 0 {
		return rand.Float64() > status.ThrottleRate
	}
	
	return true
}

type FrontLoadedPacing struct {
	BaseAlgorithm
}

func (f *FrontLoadedPacing) CalculateThrottle(status *BudgetStatus) float64 {
	if status.CircuitBreakerOn {
		return 1.0
	}
	
	isFirstHalf := status.CurrentHour < 12
	var targetSpend float64
	
	if isFirstHalf {
		targetSpend = float64(status.DailyBudget) * 0.7 / 12.0
	} else {
		targetSpend = float64(status.DailyBudget) * 0.3 / 12.0
	}
	
	actualSpend := float64(status.HourlySpent)
	if actualSpend <= targetSpend {
		return 0.0
	}
	
	overSpendRatio := (actualSpend - targetSpend) / targetSpend
	throttleRate := math.Min(1.0, overSpendRatio)
	
	return throttleRate
}

func (f *FrontLoadedPacing) ShouldBid(status *BudgetStatus) bool {
	if status.CircuitBreakerOn {
		return false
	}
	
	remainingBudget := status.DailyBudget - status.DailySpent
	if remainingBudget <= 0 {
		return false
	}
	
	if status.ThrottleRate > 0.8 {
		return false
	} else if status.ThrottleRate > 0 {
		return rand.Float64() > status.ThrottleRate
	}
	
	return true
}

type AdaptivePacing struct {
	BaseAlgorithm
	historicalData map[int]float64
}

func NewAdaptivePacing() *AdaptivePacing {
	return &AdaptivePacing{
		historicalData: make(map[int]float64),
	}
}

func (a *AdaptivePacing) CalculateThrottle(status *BudgetStatus) float64 {
	if status.CircuitBreakerOn {
		return 1.0
	}
	
	multiplier := a.getHistoricalMultiplier(status.CurrentHour)
	targetHourlySpend := float64(status.DailyBudget) / 24.0 * multiplier
	
	actualSpend := float64(status.HourlySpent)
	if actualSpend <= targetHourlySpend {
		return 0.0
	}
	
	overSpendRatio := (actualSpend - targetHourlySpend) / targetHourlySpend
	throttleRate := math.Min(1.0, overSpendRatio * 0.5)
	
	return throttleRate
}

func (a *AdaptivePacing) ShouldBid(status *BudgetStatus) bool {
	if status.CircuitBreakerOn {
		return false
	}
	
	remainingBudget := status.DailyBudget - status.DailySpent
	if remainingBudget <= 0 {
		return false
	}
	
	if status.ThrottleRate > 0.9 {
		return false
	} else if status.ThrottleRate > 0 {
		return rand.Float64() > status.ThrottleRate
	}
	
	return true
}

func (a *AdaptivePacing) getHistoricalMultiplier(hour int) float64 {
	defaultMultipliers := map[int]float64{
		0: 0.3, 1: 0.2, 2: 0.2, 3: 0.2, 4: 0.3, 5: 0.5,
		6: 0.8, 7: 1.0, 8: 1.2, 9: 1.5, 10: 1.8, 11: 2.0,
		12: 1.8, 13: 1.5, 14: 1.3, 15: 1.2, 16: 1.1, 17: 1.0,
		18: 1.6, 19: 1.8, 20: 1.5, 21: 1.2, 22: 0.8, 23: 0.5,
	}
	
	if mult, exists := a.historicalData[hour]; exists {
		return mult
	}
	
	return defaultMultipliers[hour]
}

func GetPacingAlgorithm(mode PacingMode) PacingAlgorithm {
	switch mode {
	case ASAP:
		return &ASAPPacing{}
	case FRONT_LOADED:
		return &FrontLoadedPacing{}
	case ADAPTIVE:
		return NewAdaptivePacing()
	default:
		return &EvenPacing{}
	}
}

// Random number generation is now handled by math/rand package