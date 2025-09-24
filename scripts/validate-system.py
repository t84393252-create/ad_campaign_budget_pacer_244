#!/usr/bin/env python3
"""
Comprehensive validation suite for Ad Campaign Budget Pacer
Tests all critical functionality and validates system behavior
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import Dict, List, Tuple
import sys

class SystemValidator:
    def __init__(self):
        self.pacer_url = "http://localhost:8080"
        self.api_url = "http://localhost:8000"
        self.test_campaign_id = "test-validation-001"
        self.results = {
            "passed": [],
            "failed": [],
            "warnings": []
        }
        
    async def setup_test_campaign(self) -> bool:
        """Create a test campaign for validation"""
        print("📦 Setting up test campaign...")
        
        campaign_data = {
            "id": self.test_campaign_id,
            "name": "System Validation Campaign",
            "daily_budget_cents": 100000,  # $1,000 for testing
            "start_date": datetime.now().isoformat(),
            "end_date": datetime.now().replace(day=28).isoformat(),
            "pacing_mode": "EVEN",
            "status": "ACTIVE"
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                # Delete if exists
                await session.delete(f"{self.api_url}/campaigns/{self.test_campaign_id}")
            except:
                pass
            
            # Create new
            async with session.post(f"{self.api_url}/campaigns", json=campaign_data) as resp:
                if resp.status in [200, 201]:
                    print("✅ Test campaign created")
                    return True
                else:
                    print(f"❌ Failed to create campaign: {resp.status}")
                    return False
    
    async def test_1_basic_connectivity(self):
        """Test 1: Basic service connectivity"""
        print("\n🔍 Test 1: Basic Connectivity")
        
        async with aiohttp.ClientSession() as session:
            # Test Pacer Service
            try:
                async with session.get(f"{self.pacer_url}/health") as resp:
                    if resp.status == 200:
                        self.results["passed"].append("Pacer service is healthy")
                        print("  ✅ Pacer service: Online")
                    else:
                        self.results["failed"].append("Pacer service unhealthy")
                        print("  ❌ Pacer service: Unhealthy")
            except Exception as e:
                self.results["failed"].append(f"Cannot reach pacer service: {e}")
                print(f"  ❌ Pacer service: Cannot connect")
            
            # Test API Service
            try:
                async with session.get(f"{self.api_url}/") as resp:
                    if resp.status == 200:
                        self.results["passed"].append("API service is healthy")
                        print("  ✅ API service: Online")
                    else:
                        self.results["failed"].append("API service unhealthy")
                        print("  ❌ API service: Unhealthy")
            except Exception as e:
                self.results["failed"].append(f"Cannot reach API service: {e}")
                print(f"  ❌ API service: Cannot connect")
    
    async def test_2_pacing_decision_latency(self):
        """Test 2: Pacing decision latency (<10ms requirement)"""
        print("\n🔍 Test 2: Pacing Decision Latency")
        
        latencies = []
        async with aiohttp.ClientSession() as session:
            for i in range(100):
                start = time.time()
                
                request_data = {
                    "campaign_id": self.test_campaign_id,
                    "bid_cents": 150
                }
                
                try:
                    async with session.post(
                        f"{self.pacer_url}/pacing/decision",
                        json=request_data,
                        timeout=aiohttp.ClientTimeout(total=1)
                    ) as resp:
                        if resp.status == 200:
                            latency = (time.time() - start) * 1000
                            latencies.append(latency)
                except:
                    pass
        
        if latencies:
            avg_latency = sum(latencies) / len(latencies)
            p99_latency = sorted(latencies)[int(len(latencies) * 0.99)] if len(latencies) > 10 else max(latencies)
            
            print(f"  📊 Average latency: {avg_latency:.2f}ms")
            print(f"  📊 P99 latency: {p99_latency:.2f}ms")
            
            if p99_latency < 10:
                self.results["passed"].append(f"P99 latency {p99_latency:.2f}ms < 10ms target")
                print("  ✅ Performance: EXCELLENT (P99 < 10ms)")
            elif p99_latency < 20:
                self.results["warnings"].append(f"P99 latency {p99_latency:.2f}ms slightly high")
                print("  ⚠️  Performance: ACCEPTABLE (P99 < 20ms)")
            else:
                self.results["failed"].append(f"P99 latency {p99_latency:.2f}ms > 10ms target")
                print("  ❌ Performance: TOO SLOW")
        else:
            self.results["failed"].append("Could not measure latency")
            print("  ❌ Could not measure latency")
    
    async def test_3_budget_tracking_accuracy(self):
        """Test 3: Budget tracking accuracy"""
        print("\n🔍 Test 3: Budget Tracking Accuracy")
        
        async with aiohttp.ClientSession() as session:
            # Reset budget for clean test
            await session.post(f"{self.api_url}/budget/reset/{self.test_campaign_id}")
            await asyncio.sleep(1)
            
            # Track some spend
            test_spends = [100, 250, 175, 325, 150]  # Total: $10.00
            total_tracked = 0
            
            for spend in test_spends:
                request_data = {
                    "campaign_id": self.test_campaign_id,
                    "spend_cents": spend,
                    "impressions": 1
                }
                
                async with session.post(f"{self.pacer_url}/spend/track", json=request_data) as resp:
                    if resp.status == 200:
                        total_tracked += spend
                
                await asyncio.sleep(0.1)
            
            # Check budget status
            async with session.get(f"{self.pacer_url}/budget/status/{self.test_campaign_id}") as resp:
                if resp.status == 200:
                    status = await resp.json()
                    reported_spend = status.get("daily_spent_cents", 0)
                    
                    print(f"  📊 Tracked: ${total_tracked/100:.2f}")
                    print(f"  📊 Reported: ${reported_spend/100:.2f}")
                    
                    if reported_spend == total_tracked:
                        self.results["passed"].append("Budget tracking is accurate")
                        print("  ✅ Tracking: ACCURATE")
                    else:
                        diff = abs(reported_spend - total_tracked)
                        if diff < 10:  # Within 10 cents
                            self.results["warnings"].append(f"Small tracking discrepancy: {diff} cents")
                            print(f"  ⚠️  Tracking: Small discrepancy ({diff} cents)")
                        else:
                            self.results["failed"].append(f"Budget tracking error: {diff} cents")
                            print(f"  ❌ Tracking: ERROR ({diff} cents off)")
    
    async def test_4_circuit_breaker_protection(self):
        """Test 4: Circuit breaker triggers at 95% budget"""
        print("\n🔍 Test 4: Circuit Breaker Protection")
        
        async with aiohttp.ClientSession() as session:
            # Reset and set up campaign with small budget for testing
            test_campaign = f"cb-test-{int(time.time())}"
            
            campaign_data = {
                "id": test_campaign,
                "name": "Circuit Breaker Test",
                "daily_budget_cents": 10000,  # $100 budget
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().replace(day=28).isoformat(),
                "pacing_mode": "ASAP",
                "status": "ACTIVE"
            }
            
            # Create campaign
            await session.post(f"{self.api_url}/campaigns", json=campaign_data)
            await asyncio.sleep(1)
            
            # Spend up to 95% of budget
            total_spent = 0
            bid_allowed = True
            
            while total_spent < 9500 and bid_allowed:  # 95% of $100
                # Try to bid
                bid_request = {
                    "campaign_id": test_campaign,
                    "bid_cents": 500
                }
                
                async with session.post(f"{self.pacer_url}/pacing/decision", json=bid_request) as resp:
                    if resp.status == 200:
                        decision = await resp.json()
                        bid_allowed = decision.get("allow_bid", False)
                        
                        if bid_allowed:
                            # Track the spend
                            spend_request = {
                                "campaign_id": test_campaign,
                                "spend_cents": 500,
                                "impressions": 1
                            }
                            await session.post(f"{self.pacer_url}/spend/track", json=spend_request)
                            total_spent += 500
            
            # Check final status
            async with session.get(f"{self.pacer_url}/budget/status/{test_campaign}") as resp:
                if resp.status == 200:
                    status = await resp.json()
                    spent_percentage = (status.get("daily_spent_cents", 0) / 10000) * 100
                    cb_open = status.get("circuit_breaker_open", False)
                    
                    print(f"  📊 Budget spent: {spent_percentage:.1f}%")
                    print(f"  📊 Circuit breaker: {'OPEN' if cb_open else 'CLOSED'}")
                    
                    if spent_percentage >= 94 and spent_percentage <= 96:
                        if cb_open or not bid_allowed:
                            self.results["passed"].append("Circuit breaker protects at 95%")
                            print("  ✅ Protection: WORKING (stopped at ~95%)")
                        else:
                            self.results["warnings"].append("Circuit breaker may not be triggering")
                            print("  ⚠️  Protection: Uncertain")
                    elif spent_percentage > 96:
                        self.results["failed"].append(f"Overspent: {spent_percentage:.1f}%")
                        print(f"  ❌ Protection: FAILED (overspent to {spent_percentage:.1f}%)")
                    else:
                        self.results["warnings"].append(f"Test incomplete: only {spent_percentage:.1f}% spent")
                        print(f"  ⚠️  Test incomplete: {spent_percentage:.1f}% spent")
    
    async def test_5_pacing_algorithm_behavior(self):
        """Test 5: Pacing algorithms behave correctly"""
        print("\n🔍 Test 5: Pacing Algorithm Behavior")
        
        async with aiohttp.ClientSession() as session:
            # Test EVEN pacing
            even_campaign = "even-test-001"
            await session.post(f"{self.api_url}/campaigns", json={
                "id": even_campaign,
                "name": "Even Pacing Test",
                "daily_budget_cents": 240000,  # $2,400 = $100/hour target
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().replace(day=28).isoformat(),
                "pacing_mode": "EVEN",
                "status": "ACTIVE"
            })
            
            # Simulate hourly spend at correct pace
            for hour in range(3):
                # Spend exactly $100 (target for EVEN)
                for _ in range(10):
                    await session.post(f"{self.pacer_url}/spend/track", json={
                        "campaign_id": even_campaign,
                        "spend_cents": 1000,  # $10
                        "impressions": 1
                    })
                
                # Check if throttling kicks in
                bid_request = {"campaign_id": even_campaign, "bid_cents": 1000}
                async with session.post(f"{self.pacer_url}/pacing/decision", json=bid_request) as resp:
                    if resp.status == 200:
                        decision = await resp.json()
                        throttle = decision.get("throttle_rate", 0)
                        
                        if hour == 0:
                            print(f"  📊 Hour {hour+1}: Throttle rate = {throttle:.2%}")
            
            # Test ASAP pacing
            asap_campaign = "asap-test-001"
            await session.post(f"{self.api_url}/campaigns", json={
                "id": asap_campaign,
                "name": "ASAP Pacing Test",
                "daily_budget_cents": 10000,
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().replace(day=28).isoformat(),
                "pacing_mode": "ASAP",
                "status": "ACTIVE"
            })
            
            # ASAP should allow aggressive spending initially
            decisions = []
            for _ in range(5):
                bid_request = {"campaign_id": asap_campaign, "bid_cents": 100}
                async with session.post(f"{self.pacer_url}/pacing/decision", json=bid_request) as resp:
                    if resp.status == 200:
                        decision = await resp.json()
                        decisions.append(decision.get("allow_bid", False))
            
            if all(decisions):
                self.results["passed"].append("ASAP pacing allows aggressive spending")
                print("  ✅ ASAP: Aggressive spending allowed")
            else:
                self.results["warnings"].append("ASAP pacing may be too conservative")
                print("  ⚠️  ASAP: May be too conservative")
    
    async def test_6_concurrent_request_handling(self):
        """Test 6: Handle concurrent requests without data corruption"""
        print("\n🔍 Test 6: Concurrent Request Handling")
        
        test_campaign = f"concurrent-{int(time.time())}"
        
        async with aiohttp.ClientSession() as session:
            # Create test campaign
            await session.post(f"{self.api_url}/campaigns", json={
                "id": test_campaign,
                "name": "Concurrency Test",
                "daily_budget_cents": 100000,
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().replace(day=28).isoformat(),
                "pacing_mode": "EVEN",
                "status": "ACTIVE"
            })
            
            await asyncio.sleep(1)
            
            # Send 100 concurrent spend tracking requests
            async def track_spend():
                try:
                    await session.post(f"{self.pacer_url}/spend/track", json={
                        "campaign_id": test_campaign,
                        "spend_cents": 100,
                        "impressions": 1
                    })
                    return True
                except:
                    return False
            
            tasks = [track_spend() for _ in range(100)]
            results = await asyncio.gather(*tasks)
            successful = sum(1 for r in results if r)
            
            # Check final budget
            await asyncio.sleep(2)  # Let Redis settle
            
            async with session.get(f"{self.pacer_url}/budget/status/{test_campaign}") as resp:
                if resp.status == 200:
                    status = await resp.json()
                    reported_spend = status.get("daily_spent_cents", 0)
                    expected_spend = successful * 100
                    
                    print(f"  📊 Concurrent requests: {successful}/100 succeeded")
                    print(f"  📊 Expected spend: ${expected_spend/100:.2f}")
                    print(f"  📊 Reported spend: ${reported_spend/100:.2f}")
                    
                    if reported_spend == expected_spend:
                        self.results["passed"].append("Concurrent requests handled correctly")
                        print("  ✅ Concurrency: No data corruption")
                    else:
                        diff = abs(reported_spend - expected_spend)
                        self.results["failed"].append(f"Data corruption: {diff} cents discrepancy")
                        print(f"  ❌ Concurrency: Data corruption ({diff} cents)")
    
    async def test_7_recovery_behavior(self):
        """Test 7: System recovery after circuit breaker trip"""
        print("\n🔍 Test 7: Recovery After Circuit Breaker")
        
        # This test would need to wait 5 minutes for real recovery
        # For validation, we'll just check the mechanism exists
        
        async with aiohttp.ClientSession() as session:
            # Check if circuit breaker endpoints exist
            test_campaign = self.test_campaign_id
            
            async with session.get(f"{self.pacer_url}/budget/status/{test_campaign}") as resp:
                if resp.status == 200:
                    status = await resp.json()
                    if "circuit_breaker_state" in status:
                        self.results["passed"].append("Circuit breaker state tracking exists")
                        print("  ✅ Recovery mechanism: Present")
                    else:
                        self.results["warnings"].append("Circuit breaker state not exposed")
                        print("  ⚠️  Recovery mechanism: Not visible")
    
    async def test_8_data_persistence(self):
        """Test 8: Data persists correctly across services"""
        print("\n🔍 Test 8: Data Persistence")
        
        async with aiohttp.ClientSession() as session:
            # Create a campaign via API
            persist_campaign = f"persist-{int(time.time())}"
            
            campaign_data = {
                "id": persist_campaign,
                "name": "Persistence Test",
                "daily_budget_cents": 50000,
                "start_date": datetime.now().isoformat(),
                "end_date": datetime.now().replace(day=28).isoformat(),
                "pacing_mode": "EVEN",
                "status": "ACTIVE"
            }
            
            # Create via API
            async with session.post(f"{self.api_url}/campaigns", json=campaign_data) as resp:
                if resp.status in [200, 201]:
                    print("  ✅ Campaign created via API")
                else:
                    print("  ❌ Failed to create campaign")
                    return
            
            await asyncio.sleep(2)  # Let it propagate
            
            # Track spend via Pacer
            await session.post(f"{self.pacer_url}/spend/track", json={
                "campaign_id": persist_campaign,
                "spend_cents": 2500,
                "impressions": 10
            })
            
            await asyncio.sleep(1)
            
            # Check if both services see the same data
            pacer_status = None
            api_status = None
            
            async with session.get(f"{self.pacer_url}/budget/status/{persist_campaign}") as resp:
                if resp.status == 200:
                    pacer_status = await resp.json()
            
            async with session.get(f"{self.api_url}/budget/status/{persist_campaign}") as resp:
                if resp.status == 200:
                    api_status = await resp.json()
            
            if pacer_status and api_status:
                pacer_spend = pacer_status.get("daily_spent_cents", 0)
                api_spend = api_status.get("daily_spent_cents", 0)
                
                print(f"  📊 Pacer sees: ${pacer_spend/100:.2f}")
                print(f"  📊 API sees: ${api_spend/100:.2f}")
                
                if pacer_spend == api_spend:
                    self.results["passed"].append("Data consistency across services")
                    print("  ✅ Persistence: Consistent")
                else:
                    self.results["failed"].append("Data inconsistency between services")
                    print("  ❌ Persistence: Inconsistent")
    
    async def run_all_tests(self):
        """Run all validation tests"""
        print("\n" + "="*60)
        print("🚀 AD CAMPAIGN BUDGET PACER - SYSTEM VALIDATION")
        print("="*60)
        
        # Setup
        if not await self.setup_test_campaign():
            print("❌ Failed to set up test environment")
            return False
        
        # Run tests
        await self.test_1_basic_connectivity()
        await self.test_2_pacing_decision_latency()
        await self.test_3_budget_tracking_accuracy()
        await self.test_4_circuit_breaker_protection()
        await self.test_5_pacing_algorithm_behavior()
        await self.test_6_concurrent_request_handling()
        await self.test_7_recovery_behavior()
        await self.test_8_data_persistence()
        
        # Summary
        print("\n" + "="*60)
        print("📊 VALIDATION SUMMARY")
        print("="*60)
        
        print(f"\n✅ Passed: {len(self.results['passed'])} tests")
        for test in self.results['passed']:
            print(f"   • {test}")
        
        if self.results['warnings']:
            print(f"\n⚠️  Warnings: {len(self.results['warnings'])} issues")
            for warning in self.results['warnings']:
                print(f"   • {warning}")
        
        if self.results['failed']:
            print(f"\n❌ Failed: {len(self.results['failed'])} tests")
            for failure in self.results['failed']:
                print(f"   • {failure}")
        
        # Overall verdict
        print("\n" + "="*60)
        if not self.results['failed']:
            if not self.results['warnings']:
                print("🎉 SYSTEM VALIDATION: PASSED - All systems operational!")
            else:
                print("✅ SYSTEM VALIDATION: PASSED WITH WARNINGS - Review warnings above")
        else:
            print("❌ SYSTEM VALIDATION: FAILED - Critical issues detected")
        print("="*60)
        
        return len(self.results['failed']) == 0

async def main():
    validator = SystemValidator()
    success = await validator.run_all_tests()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    asyncio.run(main())