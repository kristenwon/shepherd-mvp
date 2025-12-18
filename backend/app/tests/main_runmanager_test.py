#!/usr/bin/env python3
"""
Test suite for main.py with RunManager implementation
Tests the class-based queue management and PID tracking
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import List, Dict
import websockets

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

class RunManagerTester:
    """Test suite for RunManager-based implementation"""
    
    def __init__(self):
        self.run_ids = []
        self.ws_connections = {}
        self.test_results = {
            "passed": [],
            "failed": []
        }
    
    async def create_analysis(self, session: aiohttp.ClientSession, index: int) -> str:
        """Create a repository analysis"""
        data = {
            "repository_url": f"https://github.com/test/repo-{index}",
            "project_description": f"Test project {index}",
            "environment": "local",
            "user_id": "@0xps"
        }
        
        async with session.post(f"{BASE_URL}/api/repository-analysis", json=data) as resp:
            result = await resp.json()
            return result["run_id"]
    
    async def start_run(self, session: aiohttp.ClientSession, run_id: str) -> Dict:
        """Start a run"""
        data = {"github_url": "https://github.com/test/repo"}
        
        async with session.post(f"{BASE_URL}/runs/{run_id}", json=data) as resp:
            result = await resp.json()
            return result
    
    async def check_system_status(self, session: aiohttp.ClientSession) -> Dict:
        """Check system status"""
        async with session.get(f"{BASE_URL}/system/status") as resp:
            return await resp.json()
    
    async def check_queue_status(self, session: aiohttp.ClientSession, run_id: str) -> Dict:
        """Check queue status for a specific run"""
        async with session.get(f"{BASE_URL}/runs/{run_id}/queue-status") as resp:
            return await resp.json()
    
    async def cancel_run(self, session: aiohttp.ClientSession, run_id: str) -> Dict:
        """Cancel a specific run"""
        async with session.delete(f"{BASE_URL}/runs/{run_id}/cancel") as resp:
            return await resp.json()
    
    async def cleanup_all_runs(self, session: aiohttp.ClientSession):
        """Cancel all tracked runs for cleanup"""
        for run_id in self.run_ids:
            try:
                await self.cancel_run(session, run_id)
            except:
                pass
        self.run_ids = []
        await asyncio.sleep(1)
    
    def report_test(self, test_name: str, passed: bool, details: str = ""):
        """Report test result"""
        if passed:
            self.test_results["passed"].append(test_name)
            print(f"✅ {test_name}: PASSED {details}")
        else:
            self.test_results["failed"].append(test_name)
            print(f"❌ {test_name}: FAILED {details}")
    
    # ============= INDIVIDUAL TESTS =============
    
    async def test_1_basic_queue_management(self, session: aiohttp.ClientSession):
        """Test 1: Basic queue management with RunManager"""
        print("\n📋 Test 1: Basic Queue Management")
        print("-" * 40)
        
        # Clean state first
        await self.cleanup_all_runs(session)
        
        # Check initial state
        status = await self.check_system_status(session)
        self.report_test(
            "Initial state clean",
            status['active_runs'] == 0 and status['queued_runs'] == 0,
            f"(Active: {status['active_runs']}, Queued: {status['queued_runs']})"
        )
        
        # Create and start 5 runs
        print("\n   Creating 5 runs...")
        for i in range(5):
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            result = await self.start_run(session, run_id)
            
            if i < 3:  # First 3 should start immediately
                self.report_test(
                    f"Run {i+1} starts immediately",
                    result['status'] == 'started',
                    f"({result.get('status')})"
                )
            else:  # Runs 4-5 should be queued
                expected_position = i - 2  # Position 1 for run 4, position 2 for run 5
                self.report_test(
                    f"Run {i+1} queued at position {expected_position}",
                    result['status'] == 'queued' and result.get('queue_position') == expected_position,
                    f"(Status: {result.get('status')}, Position: {result.get('queue_position')})"
                )
        
        # Verify final system state
        await asyncio.sleep(1)
        status = await self.check_system_status(session)
        self.report_test(
            "System at capacity",
            status['active_runs'] == 3 and status['queued_runs'] == 2,
            f"(Active: {status['active_runs']}/3, Queued: {status['queued_runs']})"
        )
        
        # Cleanup
        await self.cleanup_all_runs(session)
    
    async def test_2_queue_position_tracking(self, session: aiohttp.ClientSession):
        """Test 2: Queue positions are correctly maintained"""
        print("\n📋 Test 2: Queue Position Tracking")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Fill all slots and queue 3 more
        run_ids = []
        for i in range(6):
            run_id = await self.create_analysis(session, i)
            run_ids.append(run_id)
            self.run_ids.append(run_id)
            await self.start_run(session, run_id)
        
        # Check queue positions for queued runs
        for i, run_id in enumerate(run_ids[3:], start=1):  # Runs 4-6
            status = await self.check_queue_status(session, run_id)
            self.report_test(
                f"Queued run {i+3} has correct position",
                status.get('queue_position') == i,
                f"(Expected: {i}, Got: {status.get('queue_position')})"
            )
        
        await self.cleanup_all_runs(session)
    
    async def test_3_cancellation(self, session: aiohttp.ClientSession):
        """Test 3: Cancellation of active and queued runs"""
        print("\n📋 Test 3: Run Cancellation")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Start 5 runs (3 active, 2 queued)
        for i in range(5):
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            await self.start_run(session, run_id)
        
        # Cancel an active run (run #2)
        cancel_result = await self.cancel_run(session, self.run_ids[1])
        self.report_test(
            "Cancel active run",
            cancel_result.get('success') == True,
            f"({cancel_result.get('message')})"
        )
        
        # Cancel a queued run (run #5)
        cancel_result = await self.cancel_run(session, self.run_ids[4])
        self.report_test(
            "Cancel queued run",
            cancel_result.get('success') == True,
            f"({cancel_result.get('message')})"
        )
        
        # Check system state after cancellations
        await asyncio.sleep(1)
        status = await self.check_system_status(session)
        self.report_test(
            "System state after cancellations",
            status['active_runs'] <= 3 and status['queued_runs'] <= 1,
            f"(Active: {status['active_runs']}, Queued: {status['queued_runs']})"
        )
        
        await self.cleanup_all_runs(session)
    
    async def test_4_queue_fifo_ordering(self, session: aiohttp.ClientSession):
        """Test 4: FIFO queue ordering"""
        print("\n📋 Test 4: FIFO Queue Ordering")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Create runs with identifiable order
        queue_order = []
        for i in range(6):
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            result = await self.start_run(session, run_id)
            
            if result['status'] == 'queued':
                queue_order.append({
                    'run_id': run_id,
                    'position': result.get('queue_position'),
                    'order': i + 1
                })
        
        # Verify queue maintains FIFO order
        for i, item in enumerate(queue_order):
            self.report_test(
                f"Run {item['order']} queued in FIFO order",
                item['position'] == i + 1,
                f"(Position: {item['position']})"
            )
        
        await self.cleanup_all_runs(session)
    
    async def test_5_concurrent_limits(self, session: aiohttp.ClientSession):
        """Test 5: Concurrent run limits are enforced"""
        print("\n📋 Test 5: Concurrent Run Limits")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Try to start 10 runs rapidly
        start_results = []
        for i in range(10):
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            result = await self.start_run(session, run_id)
            start_results.append(result)
        
        # Count started vs queued
        started = sum(1 for r in start_results if r['status'] == 'started')
        queued = sum(1 for r in start_results if r['status'] == 'queued')
        
        self.report_test(
            "Max concurrent limit enforced",
            started == 3,
            f"(Started: {started}/3)"
        )
        
        self.report_test(
            "Excess runs queued",
            queued == 7,
            f"(Queued: {queued}/7)"
        )
        
        await self.cleanup_all_runs(session)
    
    async def test_6_system_status_accuracy(self, session: aiohttp.ClientSession):
        """Test 6: System status endpoint accuracy"""
        print("\n📋 Test 6: System Status Accuracy")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Start exactly 3 runs
        for i in range(3):
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            await self.start_run(session, run_id)
        
        status = await self.check_system_status(session)
        self.report_test(
            "Available slots calculation",
            status['available_slots'] == 0,
            f"(Available: {status['available_slots']})"
        )
        
        self.report_test(
            "Status shows at capacity",
            status['status'] == 'at_capacity',
            f"(Status: {status['status']})"
        )
        
        # Cancel one run
        await self.cancel_run(session, self.run_ids[0])
        await asyncio.sleep(1)
        
        status = await self.check_system_status(session)
        self.report_test(
            "Available slots after cancel",
            status['available_slots'] >= 1,
            f"(Available: {status['available_slots']})"
        )
        
        await self.cleanup_all_runs(session)
    
    async def test_7_websocket_notifications(self, session: aiohttp.ClientSession):
        """Test 7: WebSocket notifications for queue events"""
        print("\n📋 Test 7: WebSocket Notifications")
        print("-" * 40)
        
        await self.cleanup_all_runs(session)
        
        # Create a run that will be queued
        for i in range(4):  # Fill slots first
            run_id = await self.create_analysis(session, i)
            self.run_ids.append(run_id)
            if i < 3:
                await self.start_run(session, run_id)
        
        # Connect WebSocket for the 4th run before starting it
        queued_run_id = self.run_ids[3]
        ws_messages = []
        
        async def monitor_ws():
            try:
                async with websockets.connect(f"{WS_URL}/ws/{queued_run_id}") as ws:
                    # Start the run after WS connects
                    await self.start_run(session, queued_run_id)
                    
                    # Collect messages for 2 seconds
                    start = time.time()
                    while time.time() - start < 2:
                        try:
                            msg = await asyncio.wait_for(ws.recv(), timeout=0.5)
                            data = json.loads(msg)
                            ws_messages.append(data)
                        except asyncio.TimeoutError:
                            continue
            except Exception as e:
                print(f"   WS Error: {e}")
        
        await monitor_ws()
        
        # Check if we got queue status notification
        has_status_change = any(
            msg.get('type') == 'status_change' 
            for msg in ws_messages
        )
        
        self.report_test(
            "WebSocket receives notifications",
            len(ws_messages) > 0,
            f"(Messages received: {len(ws_messages)})"
        )
        
        await self.cleanup_all_runs(session)
    
    # ============= MAIN TEST RUNNER =============
    
    async def run_all_tests(self):
        """Run all tests and report results"""
        print("\n" + "="*60)
        print("   RUNMANAGER TEST SUITE FOR main.py")
        print("="*60)
        
        async with aiohttp.ClientSession() as session:
            # Check if server is running
            try:
                await self.check_system_status(session)
            except Exception as e:
                print(f"\n❌ ERROR: Cannot connect to server at {BASE_URL}")
                print(f"   Make sure server is running: uvicorn backend.app.main:app")
                return
            
            # Run all tests
            await self.test_1_basic_queue_management(session)
            await self.test_2_queue_position_tracking(session)
            await self.test_3_cancellation(session)
            await self.test_4_queue_fifo_ordering(session)
            await self.test_5_concurrent_limits(session)
            await self.test_6_system_status_accuracy(session)
            await self.test_7_websocket_notifications(session)
            
            # Final cleanup
            await self.cleanup_all_runs(session)
        
        # Report summary
        print("\n" + "="*60)
        print("   TEST SUMMARY")
        print("="*60)
        print(f"\n✅ Passed: {len(self.test_results['passed'])} tests")
        print(f"❌ Failed: {len(self.test_results['failed'])} tests")
        
        if self.test_results['failed']:
            print("\nFailed tests:")
            for test in self.test_results['failed']:
                print(f"  - {test}")
        else:
            print("\n🎉 ALL TESTS PASSED!")
        
        print("\n" + "="*60 + "\n")

async def main():
    tester = RunManagerTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())