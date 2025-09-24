#!/usr/bin/env python3
"""
Circuit Breaker Validation Test
Tests that the circuit breaker properly triggers at 95% budget threshold
"""

import requests
import json
import time
import os

class CircuitBreakerTester:
    def __init__(self):
        # Support Docker or localhost
        if os.getenv("IN_DOCKER"):
            self.pacer_url = "http://budget-pacer-core:8080"
            self.api_url = "http://budget-pacer-api:8000"
        else:
            self.pacer_url = "http://localhost:8080"
            self.api_url = "http://localhost:8000"
    
    def test_circuit_breaker(self):
        """Test that circuit breaker triggers at 95% of budget"""
        print("\n" + "="*60)
        print("🔍 CIRCUIT BREAKER VALIDATION TEST")
        print("="*60)
        
        # Create a test campaign with small budget for easy testing
        test_campaign_id = f"cb-test-{int(time.time())}"
        daily_budget_cents = 10000  # $100 daily budget
        threshold_cents = int(daily_budget_cents * 0.95)  # $95 (95% threshold)
        
        print(f"\n📊 Test Campaign Setup:")
        print(f"  • Campaign ID: {test_campaign_id}")
        print(f"  • Daily Budget: ${daily_budget_cents/100:.2f}")
        print(f"  • Circuit Breaker Threshold (95%): ${threshold_cents/100:.2f}")
        
        # Step 1: Check initial state
        print(f"\n🔍 Step 1: Initial State Check")
        resp = requests.get(f"{self.pacer_url}/budget/status/{test_campaign_id}")
        if resp.status_code == 200:
            status = resp.json()
            print(f"  ✅ Initial state retrieved")
            print(f"     • Spent: ${status.get('daily_spent_cents', 0)/100:.2f}")
            print(f"     • Circuit Breaker: {status.get('circuit_breaker_state', 'UNKNOWN')}")
        
        # Step 2: Track spending up to 90% (should remain CLOSED)
        print(f"\n🔍 Step 2: Spend 90% of budget (${daily_budget_cents * 0.9 / 100:.2f})")
        
        # Track $90 in chunks
        spend_chunks = [2000, 2000, 2000, 2000, 1000]  # Total $90
        total_spent = 0
        
        for i, amount in enumerate(spend_chunks):
            resp = requests.post(
                f"{self.pacer_url}/spend/track",
                json={
                    "campaign_id": test_campaign_id,
                    "spend_cents": amount,
                    "impressions": 10
                }
            )
            total_spent += amount
            print(f"  • Tracked ${amount/100:.2f} (Total: ${total_spent/100:.2f})")
        
        # Check status at 90%
        resp = requests.get(f"{self.pacer_url}/budget/status/{test_campaign_id}")
        if resp.status_code == 200:
            status = resp.json()
            print(f"\n  📊 Status at 90% spend:")
            print(f"     • Spent: ${status.get('daily_spent_cents', 0)/100:.2f}")
            print(f"     • Pace: {status.get('pace_percentage', 0):.1f}%")
            print(f"     • Circuit Breaker: {status.get('circuit_breaker_state', 'UNKNOWN')}")
            
            if status.get('circuit_breaker_state') == 'CLOSED':
                print(f"  ✅ Circuit breaker correctly CLOSED at 90%")
            else:
                print(f"  ⚠️  Circuit breaker state unexpected at 90%")
        
        # Step 3: Test pacing decision at 90% (should allow)
        print(f"\n🔍 Step 3: Test pacing decision at 90% spend")
        resp = requests.post(
            f"{self.pacer_url}/pacing/decision",
            json={"campaign_id": test_campaign_id, "bid_cents": 100}
        )
        if resp.status_code == 200:
            decision = resp.json()
            if decision.get("allow_bid"):
                print(f"  ✅ Bids still allowed at 90% spend")
            else:
                print(f"  ❌ Bids blocked prematurely at 90%")
        
        # Step 4: Push spending to 96% (should trigger circuit breaker)
        print(f"\n🔍 Step 4: Push to 96% of budget (${daily_budget_cents * 0.96 / 100:.2f})")
        
        # Track additional $600 to reach 96%
        resp = requests.post(
            f"{self.pacer_url}/spend/track",
            json={
                "campaign_id": test_campaign_id,
                "spend_cents": 600,
                "impressions": 5
            }
        )
        total_spent += 600
        print(f"  • Tracked additional ${600/100:.2f} (Total: ${total_spent/100:.2f})")
        
        # Check status at 96%
        resp = requests.get(f"{self.pacer_url}/budget/status/{test_campaign_id}")
        if resp.status_code == 200:
            status = resp.json()
            print(f"\n  📊 Status at 96% spend:")
            print(f"     • Spent: ${status.get('daily_spent_cents', 0)/100:.2f}")
            print(f"     • Pace: {status.get('pace_percentage', 0):.1f}%")
            print(f"     • Circuit Breaker: {status.get('circuit_breaker_state', 'UNKNOWN')}")
            print(f"     • Circuit Breaker Open: {status.get('circuit_breaker_open', False)}")
            
            cb_state = status.get('circuit_breaker_state', 'UNKNOWN')
            cb_open = status.get('circuit_breaker_open', False)
            
            if cb_state == 'OPEN' or cb_open:
                print(f"  ✅ Circuit breaker correctly triggered at 95%+ spend!")
            else:
                print(f"  ❌ Circuit breaker FAILED to trigger at 95%+ spend")
        
        # Step 5: Test that bids are now blocked
        print(f"\n🔍 Step 5: Verify bids are blocked when circuit breaker is open")
        
        bid_attempts = []
        for i in range(5):
            resp = requests.post(
                f"{self.pacer_url}/pacing/decision",
                json={"campaign_id": test_campaign_id, "bid_cents": 100}
            )
            if resp.status_code == 200:
                decision = resp.json()
                bid_attempts.append(decision.get("allow_bid", False))
                
        allowed_count = sum(1 for allowed in bid_attempts if allowed)
        blocked_count = len(bid_attempts) - allowed_count
        
        print(f"  📊 Bid attempts after circuit breaker:")
        print(f"     • Total attempts: {len(bid_attempts)}")
        print(f"     • Allowed: {allowed_count}")
        print(f"     • Blocked: {blocked_count}")
        
        if blocked_count == len(bid_attempts):
            print(f"  ✅ All bids correctly blocked by circuit breaker!")
        elif blocked_count > 0:
            print(f"  ⚠️  Some bids blocked, but not all")
        else:
            print(f"  ❌ Circuit breaker not blocking bids")
        
        # Step 6: Verify spend tracking is also blocked
        print(f"\n🔍 Step 6: Verify no additional spending when circuit breaker is open")
        
        initial_spent = status.get('daily_spent_cents', 0)
        
        # Try to track more spend (should be blocked or ignored)
        resp = requests.post(
            f"{self.pacer_url}/spend/track",
            json={
                "campaign_id": test_campaign_id,
                "spend_cents": 500,
                "impressions": 5
            }
        )
        
        # Check if spend increased
        resp = requests.get(f"{self.pacer_url}/budget/status/{test_campaign_id}")
        if resp.status_code == 200:
            final_status = resp.json()
            final_spent = final_status.get('daily_spent_cents', 0)
            
            if final_spent == initial_spent:
                print(f"  ✅ No additional spend tracked (protected by circuit breaker)")
            else:
                additional = final_spent - initial_spent
                print(f"  ⚠️  Additional ${additional/100:.2f} was tracked despite circuit breaker")
        
        # Summary
        print(f"\n" + "="*60)
        print("📊 CIRCUIT BREAKER TEST SUMMARY")
        print("="*60)
        
        # The key check: Is circuit breaker working?
        if cb_state == 'OPEN' or cb_open:
            if blocked_count == len(bid_attempts):
                print("\n✅ CIRCUIT BREAKER WORKING CORRECTLY!")
                print("  • Triggers at 95% threshold")
                print("  • Blocks all new bids")
                print("  • Prevents overspending")
            else:
                print("\n⚠️  CIRCUIT BREAKER PARTIALLY WORKING")
                print("  • Triggers at 95% threshold")
                print(f"  • But only blocked {blocked_count}/{len(bid_attempts)} bids")
        else:
            print("\n❌ CIRCUIT BREAKER NOT WORKING")
            print("  • Failed to trigger at 95% threshold")
            print("  • Campaign could overspend budget")
        
        print("="*60)

def main():
    tester = CircuitBreakerTester()
    tester.test_circuit_breaker()

if __name__ == "__main__":
    main()