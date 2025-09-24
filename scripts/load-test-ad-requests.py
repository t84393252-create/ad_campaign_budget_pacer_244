#!/usr/bin/env python3
"""
Load testing script for Ad Campaign Budget Pacer
Simulates real-world ad request patterns and measures latency
"""

import time
import requests
import json
import random
import statistics
import concurrent.futures
from datetime import datetime
from collections import defaultdict

class AdRequestSimulator:
    def __init__(self, pacer_url="http://localhost:8080", api_url="http://localhost:8000"):
        self.pacer_url = pacer_url
        self.api_url = api_url
        self.campaigns = ["camp-001", "camp-002", "camp-003"]
        self.results = defaultdict(list)
        
    def simulate_single_ad_request(self):
        """Simulate a single ad request through the entire flow"""
        campaign_id = random.choice(self.campaigns)
        bid_cents = random.randint(50, 500)  # Random bid between $0.50 and $5.00
        
        # Step 1: Make pacing decision
        start_time = time.perf_counter()
        
        try:
            response = requests.post(
                f"{self.pacer_url}/pacing/decision",
                json={
                    "campaign_id": campaign_id,
                    "bid_cents": bid_cents
                },
                timeout=0.1  # 100ms timeout (RTB requirement)
            )
            
            decision_latency = (time.perf_counter() - start_time) * 1000  # Convert to ms
            
            if response.status_code == 200:
                decision = response.json()
                
                # Step 2: If bid is allowed, track the spend
                if decision.get("allow_bid", False):
                    # Simulate winning the auction (20% win rate)
                    if random.random() < 0.2:
                        track_start = time.perf_counter()
                        
                        spend_response = requests.post(
                            f"{self.pacer_url}/spend/track",
                            json={
                                "campaign_id": campaign_id,
                                "spend_cents": bid_cents,
                                "impressions": 1
                            },
                            timeout=0.1
                        )
                        
                        track_latency = (time.perf_counter() - track_start) * 1000
                        
                        return {
                            "success": True,
                            "campaign_id": campaign_id,
                            "bid_cents": bid_cents,
                            "decision_latency": decision_latency,
                            "track_latency": track_latency,
                            "total_latency": decision_latency + track_latency,
                            "bid_allowed": True,
                            "won_auction": True,
                            "throttle_rate": decision.get("throttle_rate", 0)
                        }
                    else:
                        return {
                            "success": True,
                            "campaign_id": campaign_id,
                            "bid_cents": bid_cents,
                            "decision_latency": decision_latency,
                            "total_latency": decision_latency,
                            "bid_allowed": True,
                            "won_auction": False,
                            "throttle_rate": decision.get("throttle_rate", 0)
                        }
                else:
                    return {
                        "success": True,
                        "campaign_id": campaign_id,
                        "bid_cents": bid_cents,
                        "decision_latency": decision_latency,
                        "total_latency": decision_latency,
                        "bid_allowed": False,
                        "throttle_rate": decision.get("throttle_rate", 0)
                    }
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}
                
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    def run_burst_test(self, requests_per_second=1000, duration_seconds=10):
        """Simulate burst traffic pattern"""
        print(f"\n📊 Running burst test: {requests_per_second} req/s for {duration_seconds}s")
        
        total_requests = requests_per_second * duration_seconds
        batch_size = min(100, requests_per_second // 10)  # Process in batches
        
        all_results = []
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=50) as executor:
            for second in range(duration_seconds):
                second_start = time.time()
                
                # Submit requests for this second
                futures = []
                for _ in range(requests_per_second):
                    futures.append(executor.submit(self.simulate_single_ad_request))
                
                # Collect results
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result and result.get("success"):
                        all_results.append(result)
                
                # Sleep to maintain rate
                elapsed = time.time() - second_start
                if elapsed < 1.0:
                    time.sleep(1.0 - elapsed)
                
                print(f"  Second {second + 1}/{duration_seconds}: Processed {len(futures)} requests")
        
        total_time = time.time() - start_time
        return self.analyze_results(all_results, total_time)
    
    def run_realistic_traffic(self, duration_seconds=60):
        """Simulate realistic traffic patterns with varying load"""
        print(f"\n📊 Running realistic traffic simulation for {duration_seconds}s")
        
        all_results = []
        start_time = time.time()
        
        # Traffic pattern: varies throughout the "day"
        traffic_pattern = [
            500,   # Low traffic
            1000,  # Morning ramp up
            2000,  # Peak hours
            3000,  # Maximum load
            2000,  # Afternoon
            1000,  # Evening decline
            500,   # Night time
        ]
        
        seconds_per_phase = max(1, duration_seconds // len(traffic_pattern))
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
            for phase_idx, requests_per_second in enumerate(traffic_pattern):
                if time.time() - start_time >= duration_seconds:
                    break
                    
                print(f"\n  Phase {phase_idx + 1}: {requests_per_second} req/s")
                
                for second in range(seconds_per_phase):
                    if time.time() - start_time >= duration_seconds:
                        break
                        
                    second_start = time.time()
                    
                    # Submit requests
                    futures = []
                    for _ in range(requests_per_second):
                        futures.append(executor.submit(self.simulate_single_ad_request))
                    
                    # Collect results
                    for future in concurrent.futures.as_completed(futures):
                        result = future.result()
                        if result and result.get("success"):
                            all_results.append(result)
                    
                    # Maintain rate
                    elapsed = time.time() - second_start
                    if elapsed < 1.0:
                        time.sleep(1.0 - elapsed)
        
        total_time = time.time() - start_time
        return self.analyze_results(all_results, total_time)
    
    def analyze_results(self, results, total_time):
        """Analyze test results and calculate metrics"""
        if not results:
            return {"error": "No successful requests"}
        
        # Extract latencies
        decision_latencies = [r["decision_latency"] for r in results]
        total_latencies = [r["total_latency"] for r in results]
        
        # Calculate percentiles
        decision_p50 = statistics.median(decision_latencies)
        decision_p95 = sorted(decision_latencies)[int(len(decision_latencies) * 0.95)]
        decision_p99 = sorted(decision_latencies)[int(len(decision_latencies) * 0.99)]
        
        total_p50 = statistics.median(total_latencies)
        total_p95 = sorted(total_latencies)[int(len(total_latencies) * 0.95)]
        total_p99 = sorted(total_latencies)[int(len(total_latencies) * 0.99)]
        
        # Campaign statistics
        campaign_stats = defaultdict(lambda: {
            "requests": 0,
            "bids_allowed": 0,
            "auctions_won": 0,
            "total_spend": 0,
            "avg_throttle": []
        })
        
        for r in results:
            stats = campaign_stats[r["campaign_id"]]
            stats["requests"] += 1
            if r.get("bid_allowed"):
                stats["bids_allowed"] += 1
                stats["avg_throttle"].append(r.get("throttle_rate", 0))
                if r.get("won_auction"):
                    stats["auctions_won"] += 1
                    stats["total_spend"] += r.get("bid_cents", 0)
        
        # Calculate aggregates
        total_requests = len(results)
        total_allowed = sum(1 for r in results if r.get("bid_allowed"))
        total_won = sum(1 for r in results if r.get("won_auction"))
        
        return {
            "summary": {
                "total_requests": total_requests,
                "duration_seconds": total_time,
                "requests_per_second": total_requests / total_time,
                "total_bids_allowed": total_allowed,
                "total_auctions_won": total_won,
                "bid_rate": (total_allowed / total_requests * 100) if total_requests > 0 else 0,
                "win_rate": (total_won / total_allowed * 100) if total_allowed > 0 else 0
            },
            "latency_metrics": {
                "decision_latency_ms": {
                    "min": min(decision_latencies),
                    "p50": decision_p50,
                    "p95": decision_p95,
                    "p99": decision_p99,
                    "max": max(decision_latencies),
                    "avg": statistics.mean(decision_latencies)
                },
                "total_latency_ms": {
                    "min": min(total_latencies),
                    "p50": total_p50,
                    "p95": total_p95,
                    "p99": total_p99,
                    "max": max(total_latencies),
                    "avg": statistics.mean(total_latencies)
                }
            },
            "campaign_breakdown": {
                cid: {
                    "requests": stats["requests"],
                    "bids_allowed": stats["bids_allowed"],
                    "auctions_won": stats["auctions_won"],
                    "total_spend_dollars": stats["total_spend"] / 100,
                    "bid_rate": (stats["bids_allowed"] / stats["requests"] * 100) if stats["requests"] > 0 else 0,
                    "avg_throttle_rate": statistics.mean(stats["avg_throttle"]) if stats["avg_throttle"] else 0
                }
                for cid, stats in campaign_stats.items()
            }
        }
    
    def print_results(self, results):
        """Pretty print test results"""
        print("\n" + "="*60)
        print("📊 LOAD TEST RESULTS")
        print("="*60)
        
        # Summary
        summary = results["summary"]
        print(f"\n🎯 Test Summary:")
        print(f"  • Total Requests: {summary['total_requests']:,}")
        print(f"  • Duration: {summary['duration_seconds']:.1f}s")
        print(f"  • Throughput: {summary['requests_per_second']:.1f} req/s")
        print(f"  • Bids Allowed: {summary['total_bids_allowed']:,} ({summary['bid_rate']:.1f}%)")
        print(f"  • Auctions Won: {summary['total_auctions_won']:,} ({summary['win_rate']:.1f}% of allowed)")
        
        # Latency metrics
        decision = results["latency_metrics"]["decision_latency_ms"]
        total = results["latency_metrics"]["total_latency_ms"]
        
        print(f"\n⚡ Latency Metrics (Pacing Decision):")
        print(f"  • Min: {decision['min']:.2f}ms")
        print(f"  • P50: {decision['p50']:.2f}ms")
        print(f"  • P95: {decision['p95']:.2f}ms")
        print(f"  • P99: {decision['p99']:.2f}ms ⭐")
        print(f"  • Max: {decision['max']:.2f}ms")
        print(f"  • Avg: {decision['avg']:.2f}ms")
        
        # Check against SLA
        if decision['p99'] < 10:
            print(f"  ✅ P99 < 10ms SLA: PASSED")
        else:
            print(f"  ❌ P99 < 10ms SLA: FAILED")
        
        print(f"\n⚡ Total Latency (Decision + Tracking):")
        print(f"  • P50: {total['p50']:.2f}ms")
        print(f"  • P95: {total['p95']:.2f}ms")
        print(f"  • P99: {total['p99']:.2f}ms")
        
        # Campaign breakdown
        print(f"\n📈 Campaign Performance:")
        for cid, stats in results["campaign_breakdown"].items():
            print(f"\n  {cid}:")
            print(f"    • Requests: {stats['requests']:,}")
            print(f"    • Bid Rate: {stats['bid_rate']:.1f}%")
            print(f"    • Auctions Won: {stats['auctions_won']:,}")
            print(f"    • Total Spend: ${stats['total_spend_dollars']:.2f}")
            print(f"    • Avg Throttle: {stats['avg_throttle_rate']:.2f}")

def main():
    import os
    
    # Support Docker environment
    if os.getenv("IN_DOCKER"):
        pacer_url = "http://budget-pacer-core:8080"
        api_url = "http://budget-pacer-api:8000"
    else:
        pacer_url = os.getenv("PACER_URL", "http://localhost:8080")
        api_url = os.getenv("API_URL", "http://localhost:8000")
    
    simulator = AdRequestSimulator(pacer_url, api_url)
    
    print("\n" + "="*60)
    print("🚀 AD CAMPAIGN BUDGET PACER - LOAD TEST")
    print("="*60)
    
    # Test 1: Warm up with light load
    print("\n📍 Test 1: Warm-up (100 req/s for 5s)")
    warmup_results = simulator.run_burst_test(100, 5)
    simulator.print_results(warmup_results)
    
    # Test 2: Target load (1000 req/s)
    print("\n📍 Test 2: Target Load (1000 req/s for 10s)")
    target_results = simulator.run_burst_test(1000, 10)
    simulator.print_results(target_results)
    
    # Test 3: Peak load (5000 req/s)
    print("\n📍 Test 3: Peak Load (5000 req/s for 5s)")
    peak_results = simulator.run_burst_test(5000, 5)
    simulator.print_results(peak_results)
    
    # Test 4: Realistic traffic pattern
    print("\n📍 Test 4: Realistic Traffic Pattern (30s)")
    realistic_results = simulator.run_realistic_traffic(30)
    simulator.print_results(realistic_results)
    
    print("\n" + "="*60)
    print("✅ LOAD TESTING COMPLETE")
    print("="*60)

if __name__ == "__main__":
    main()