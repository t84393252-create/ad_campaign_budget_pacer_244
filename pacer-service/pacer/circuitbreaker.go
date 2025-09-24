package pacer

import (
	"context"
	"sync"
	"time"

	log "github.com/sirupsen/logrus"
)

type CircuitBreakerState string

const (
	CLOSED     CircuitBreakerState = "CLOSED"
	OPEN       CircuitBreakerState = "OPEN"
	HALF_OPEN  CircuitBreakerState = "HALF_OPEN"
)

type CircuitBreaker struct {
	mu              sync.RWMutex
	state           CircuitBreakerState
	failureCount    int
	successCount    int
	lastFailureTime time.Time
	lastStateChange time.Time
	
	maxFailures     int
	timeout         time.Duration
	successThreshold int
	budgetThreshold float64
}

func NewCircuitBreaker() *CircuitBreaker {
	return &CircuitBreaker{
		state:            CLOSED,
		maxFailures:      3,
		timeout:          5 * time.Minute,
		successThreshold: 2,
		budgetThreshold:  0.95,
	}
}

func (cb *CircuitBreaker) Allow(status *BudgetStatus) bool {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	spendPercentage := status.GetSpendPercentage() / 100.0
	if spendPercentage >= cb.budgetThreshold {
		cb.trip("Budget threshold exceeded")
		return false
	}

	// Check if too many failures accumulated
	if cb.failureCount >= cb.maxFailures && cb.state == CLOSED {
		cb.trip("Max failures exceeded")
		return false
	}

	switch cb.state {
	case CLOSED:
		return true
		
	case OPEN:
		if time.Since(cb.lastStateChange) > cb.timeout {
			cb.state = HALF_OPEN
			cb.successCount = 0
			cb.failureCount = 0
			cb.lastStateChange = time.Now()
			log.Info("Circuit breaker entering HALF_OPEN state")
			return true
		}
		return false
		
	case HALF_OPEN:
		return cb.successCount < cb.successThreshold
		
	default:
		return false
	}
}

func (cb *CircuitBreaker) RecordSuccess() {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.failureCount = 0
	
	if cb.state == HALF_OPEN {
		cb.successCount++
		if cb.successCount >= cb.successThreshold {
			cb.state = CLOSED
			cb.lastStateChange = time.Now()
			log.Info("Circuit breaker recovered to CLOSED state")
		}
	}
}

func (cb *CircuitBreaker) RecordFailure(reason string) {
	cb.mu.Lock()
	defer cb.mu.Unlock()

	cb.failureCount++
	cb.lastFailureTime = time.Now()

	if cb.state == HALF_OPEN || cb.failureCount >= cb.maxFailures {
		cb.trip(reason)
	}
}

func (cb *CircuitBreaker) trip(reason string) {
	if cb.state != OPEN {
		cb.state = OPEN
		cb.lastStateChange = time.Now()
		cb.successCount = 0
		log.WithField("reason", reason).Warn("Circuit breaker tripped to OPEN state")
	}
}

func (cb *CircuitBreaker) GetState() CircuitBreakerState {
	cb.mu.RLock()
	defer cb.mu.RUnlock()
	return cb.state
}

func (cb *CircuitBreaker) Reset() {
	cb.mu.Lock()
	defer cb.mu.Unlock()
	
	cb.state = CLOSED
	cb.failureCount = 0
	cb.successCount = 0
	cb.lastStateChange = time.Now()
}

func (cb *CircuitBreaker) GetMetrics() map[string]interface{} {
	cb.mu.RLock()
	defer cb.mu.RUnlock()
	
	return map[string]interface{}{
		"state":            string(cb.state),
		"failure_count":    cb.failureCount,
		"success_count":    cb.successCount,
		"last_failure":     cb.lastFailureTime,
		"last_state_change": cb.lastStateChange,
	}
}

type CircuitBreakerManager struct {
	breakers map[string]*CircuitBreaker
	mu       sync.RWMutex
}

func NewCircuitBreakerManager() *CircuitBreakerManager {
	return &CircuitBreakerManager{
		breakers: make(map[string]*CircuitBreaker),
	}
}

func (cbm *CircuitBreakerManager) GetBreaker(campaignID string) *CircuitBreaker {
	cbm.mu.RLock()
	breaker, exists := cbm.breakers[campaignID]
	cbm.mu.RUnlock()
	
	if exists {
		return breaker
	}
	
	cbm.mu.Lock()
	defer cbm.mu.Unlock()
	
	if breaker, exists = cbm.breakers[campaignID]; exists {
		return breaker
	}
	
	breaker = NewCircuitBreaker()
	cbm.breakers[campaignID] = breaker
	return breaker
}

func (cbm *CircuitBreakerManager) ResetBreaker(campaignID string) {
	cbm.mu.RLock()
	breaker, exists := cbm.breakers[campaignID]
	cbm.mu.RUnlock()
	
	if exists {
		breaker.Reset()
	}
}

func (cbm *CircuitBreakerManager) GetAllStates() map[string]CircuitBreakerState {
	cbm.mu.RLock()
	defer cbm.mu.RUnlock()
	
	states := make(map[string]CircuitBreakerState)
	for id, breaker := range cbm.breakers {
		states[id] = breaker.GetState()
	}
	return states
}

func (cbm *CircuitBreakerManager) CheckAndTrip(ctx context.Context, status *BudgetStatus) bool {
	breaker := cbm.GetBreaker(status.CampaignID)
	
	if !breaker.Allow(status) {
		status.CircuitBreakerOn = true
		return false
	}
	
	return true
}