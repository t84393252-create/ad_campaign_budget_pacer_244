#!/usr/bin/env python3
"""
Load testing script for Ad Campaign Budget Pacer
Tests the system under various traffic patterns and loads
"""

import asyncio
import aiohttp
import time
import random
import json
import argparse
from datetime import datetime
from typing import List, Dict, Any
import statistics

class LoadTester:
    def __init__(self, base_url: str = "http://localhost:8080", num_campaigns: int = 10):
        self.base_url = base_url
        self.num_campaigns = num_campaigns
        self.campaign_ids = [f"test-camp-{i:03d}" for i in range(num_campaigns)]
        self.results = {
            "pacing_decisions": [],
            "spend_tracks": [],
            "errors": []
        }
        
    async def setup_campaigns(self):
        """Create test campaigns via the API"""
        async with aiohttp.ClientSession() as session:
            for campaign_id in self.campaign_ids:
                campaign_data = {
                    "id": campaign_id,
                    "name": f"Test Campaign {campaign_id}",
                    "daily_budget_cents": random.choice([100000, 500000, 1000000, 2000000]),
                    "start_date": datetime.now().isoformat(),
                    "end_date": datetime.now().replace(day=28).isoformat(),
                    "pacing_mode": random.choice(["EVEN", "ASAP", "FRONT_LOADED", "ADAPTIVE"]),
                    "status": "ACTIVE"
                }
                
                try:
                    async with session.post(
                        "http://localhost:8000/campaigns",
                        json=campaign_data
                    ) as response:
                        if response.status == 200:
                            print(f"✓ Created campaign: {campaign_id}")
                        else:
                            print(f"✗ Failed to create campaign: {campaign_id}")
                except Exception as e:
                    print(f"Error creating campaign {campaign_id}: {e}")
    
    async def make_pacing_decision(self, session: aiohttp.ClientSession, campaign_id: str):
        """Make a single pacing decision request"""
        start_time = time.time()
        
        request_data = {
            "campaign_id": campaign_id,
            "bid_cents": random.randint(50, 500)
        }
        
        try:
            async with session.post(
                f"{self.base_url}/pacing/decision",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=1)
            ) as response:
                latency = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    result = await response.json()
                    self.results["pacing_decisions"].append({
                        "latency_ms": latency,
                        "success": True,
                        "allow_bid": result.get("allow_bid", False)
                    })
                else:
                    self.results["errors"].append({
                        "type": "pacing_decision",
                        "status": response.status,
                        "latency_ms": latency
                    })
                    
        except asyncio.TimeoutError:
            self.results["errors"].append({
                "type": "pacing_decision",
                "error": "timeout",
                "campaign_id": campaign_id
            })
        except Exception as e:
            self.results["errors"].append({
                "type": "pacing_decision",
                "error": str(e),
                "campaign_id": campaign_id
            })
    
    async def track_spend(self, session: aiohttp.ClientSession, campaign_id: str):
        """Track spend for a campaign"""
        start_time = time.time()
        
        request_data = {
            "campaign_id": campaign_id,
            "spend_cents": random.randint(10, 200),
            "impressions": random.randint(1, 5)
        }
        
        try:
            async with session.post(
                f"{self.base_url}/spend/track",
                json=request_data,
                timeout=aiohttp.ClientTimeout(total=1)
            ) as response:
                latency = (time.time() - start_time) * 1000
                
                if response.status == 200:
                    self.results["spend_tracks"].append({
                        "latency_ms": latency,
                        "success": True
                    })
                else:
                    self.results["errors"].append({
                        "type": "spend_track",
                        "status": response.status,
                        "latency_ms": latency
                    })
                    
        except asyncio.TimeoutError:
            self.results["errors"].append({
                "type": "spend_track",
                "error": "timeout",
                "campaign_id": campaign_id
            })
        except Exception as e:
            self.results["errors"].append({
                "type": "spend_track",
                "error": str(e),
                "campaign_id": campaign_id
            })
    
    async def run_traffic_pattern(self, pattern: str, duration_seconds: int, qps: int):
        """Run a specific traffic pattern"""
        print(f"\n🚀 Running {pattern} pattern for {duration_seconds}s at {qps} QPS")
        
        async with aiohttp.ClientSession() as session:
            start_time = time.time()
            request_count = 0
            
            while time.time() - start_time < duration_seconds:
                tasks = []
                
                # Create batch of requests
                for _ in range(qps):
                    campaign_id = random.choice(self.campaign_ids)
                    
                    if pattern == "normal":
                        # 80% pacing decisions, 20% spend tracking
                        if random.random() < 0.8:
                            tasks.append(self.make_pacing_decision(session, campaign_id))
                        else:
                            tasks.append(self.track_spend(session, campaign_id))
                    
                    elif pattern == "surge":
                        # Simulate traffic surge - all pacing decisions
                        tasks.append(self.make_pacing_decision(session, campaign_id))
                    
                    elif pattern == "mixed":
                        # 50/50 split
                        if random.random() < 0.5:
                            tasks.append(self.make_pacing_decision(session, campaign_id))
                        else:
                            tasks.append(self.track_spend(session, campaign_id))
                    
                    elif pattern == "circuit_breaker_test":
                        # Heavy spend tracking to trigger circuit breakers
                        if random.random() < 0.3:
                            tasks.append(self.make_pacing_decision(session, campaign_id))
                        else:
                            # Multiple spend tracks for same campaign
                            for _ in range(3):
                                tasks.append(self.track_spend(session, campaign_id))
                
                # Execute batch
                await asyncio.gather(*tasks, return_exceptions=True)
                request_count += len(tasks)
                
                # Wait for next second
                await asyncio.sleep(1)
            
            print(f"✓ Completed {request_count} requests")
    
    def print_results(self):
        """Print test results summary"""
        print("\n" + "="*60)
        print("📊 LOAD TEST RESULTS")
        print("="*60)
        
        # Pacing decisions analysis
        if self.results["pacing_decisions"]:
            latencies = [r["latency_ms"] for r in self.results["pacing_decisions"]]
            allow_rate = sum(1 for r in self.results["pacing_decisions"] if r.get("allow_bid")) / len(self.results["pacing_decisions"])
            
            print("\n📍 Pacing Decisions:")
            print(f"  Total requests: {len(self.results['pacing_decisions'])}")
            print(f"  Avg latency: {statistics.mean(latencies):.2f}ms")
            print(f"  P50 latency: {statistics.median(latencies):.2f}ms")
            print(f"  P95 latency: {sorted(latencies)[int(len(latencies) * 0.95)]:.2f}ms" if len(latencies) > 20 else "N/A")
            print(f"  P99 latency: {sorted(latencies)[int(len(latencies) * 0.99)]:.2f}ms" if len(latencies) > 100 else "N/A")
            print(f"  Min latency: {min(latencies):.2f}ms")
            print(f"  Max latency: {max(latencies):.2f}ms")
            print(f"  Allow bid rate: {allow_rate:.1%}")
        
        # Spend tracking analysis
        if self.results["spend_tracks"]:
            latencies = [r["latency_ms"] for r in self.results["spend_tracks"]]
            
            print("\n💰 Spend Tracking:")
            print(f"  Total requests: {len(self.results['spend_tracks'])}")
            print(f"  Avg latency: {statistics.mean(latencies):.2f}ms")
            print(f"  P50 latency: {statistics.median(latencies):.2f}ms")
            print(f"  P95 latency: {sorted(latencies)[int(len(latencies) * 0.95)]:.2f}ms" if len(latencies) > 20 else "N/A")
            print(f"  Min latency: {min(latencies):.2f}ms")
            print(f"  Max latency: {max(latencies):.2f}ms")
        
        # Errors analysis
        if self.results["errors"]:
            print(f"\n❌ Errors: {len(self.results['errors'])}")
            error_types = {}
            for error in self.results["errors"]:
                error_type = error.get("error", error.get("status", "unknown"))
                error_types[error_type] = error_types.get(error_type, 0) + 1
            
            for error_type, count in error_types.items():
                print(f"  {error_type}: {count}")
        else:
            print("\n✅ No errors detected")
        
        # Performance verdict
        print("\n🏆 Performance Verdict:")
        all_latencies = []
        all_latencies.extend([r["latency_ms"] for r in self.results["pacing_decisions"]])
        all_latencies.extend([r["latency_ms"] for r in self.results["spend_tracks"]])
        
        if all_latencies:
            p99 = sorted(all_latencies)[int(len(all_latencies) * 0.99)] if len(all_latencies) > 100 else max(all_latencies)
            
            if p99 < 10:
                print("  ⭐⭐⭐⭐⭐ EXCELLENT - P99 < 10ms target achieved!")
            elif p99 < 20:
                print("  ⭐⭐⭐⭐ GOOD - Close to 10ms target")
            elif p99 < 50:
                print("  ⭐⭐⭐ ACCEPTABLE - Some optimization needed")
            else:
                print("  ⭐⭐ NEEDS IMPROVEMENT - Significant optimization required")
            
            total_requests = len(self.results["pacing_decisions"]) + len(self.results["spend_tracks"])
            error_rate = len(self.results["errors"]) / max(total_requests, 1)
            
            if error_rate < 0.01:
                print(f"  ✅ Error rate: {error_rate:.2%} - Excellent reliability")
            elif error_rate < 0.05:
                print(f"  ⚠️  Error rate: {error_rate:.2%} - Acceptable reliability")
            else:
                print(f"  ❌ Error rate: {error_rate:.2%} - Poor reliability")

async def main():
    parser = argparse.ArgumentParser(description="Load test for Ad Campaign Budget Pacer")
    parser.add_argument("--qps", type=int, default=100, help="Queries per second")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--campaigns", type=int, default=10, help="Number of test campaigns")
    parser.add_argument("--pattern", choices=["normal", "surge", "mixed", "circuit_breaker_test", "all"], 
                       default="normal", help="Traffic pattern to test")
    parser.add_argument("--setup", action="store_true", help="Setup test campaigns first")
    
    args = parser.parse_args()
    
    tester = LoadTester(num_campaigns=args.campaigns)
    
    if args.setup:
        print("📦 Setting up test campaigns...")
        await tester.setup_campaigns()
        print("✓ Campaign setup complete\n")
    
    patterns = [args.pattern] if args.pattern != "all" else ["normal", "surge", "mixed", "circuit_breaker_test"]
    
    for pattern in patterns:
        await tester.run_traffic_pattern(pattern, args.duration, args.qps)
    
    tester.print_results()

if __name__ == "__main__":
    asyncio.run(main())