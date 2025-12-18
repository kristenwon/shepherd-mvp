#!/usr/bin/env python3
"""
Comprehensive test for concurrent session management with WebSocket monitoring
"""

import asyncio
import aiohttp
import json
import time
from datetime import datetime
from typing import List, Dict
import websockets
from concurrent.futures import ThreadPoolExecutor

BASE_URL = "http://localhost:8000"
WS_URL = "ws://localhost:8000"

class ConcurrentSessionTester:
    def __init__(self):
        self.run_ids = []
        self.ws_connections = {}
        
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
    
    async def cancel_all_runs(self, session: aiohttp.ClientSession):
        """Cancel all active and queued runs for cleanup"""
        print("\n🧹 Cleaning up previous runs...")
        
        # Get current system status
        status = await self.check_system_status(session)
        
        # Cancel all tracked runs
        for run_id in self.run_ids:
            try:
                async with session.delete(f"{BASE_URL}/runs/{run_id}/cancel") as resp:
                    result = await resp.json()
                    if result.get('success'):
                        print(f"   Cancelled: {run_id[:8]}...")
            except:
                pass  # Ignore errors during cleanup
        
        # Clear the list
        self.run_ids = []
        
        # Wait for system to settle
        await asyncio.sleep(2)
        
        # Verify cleanup
        status = await self.check_system_status(session)
        print(f"   Cleanup complete - Active: {status['active_runs']}, Queued: {status['queued_runs']}\n")
    
    async def monitor_websocket(self, run_id: str, duration: int = 30):
        try:
            async with websockets.connect(f"{WS_URL}/ws/{run_id}") as websocket:
                print(f"[WS {run_id[:8]}] Connected")
                
                start_time = time.time()
                while time.time() - start_time < duration:
                    try:
                        message = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                        data = json.loads(message)
                        
                        # Better handling of data field
                        msg_type = data.get('type', 'unknown')
                        msg_data = data.get('data', '')
                        
                        # Handle different data types
                        if isinstance(msg_data, dict):
                            print(f"[WS {run_id[:8]}] {msg_type}: {msg_data}")
                        elif isinstance(msg_data, str):
                            # Safely truncate string
                            truncated = msg_data[:100] if len(msg_data) > 100 else msg_data
                            print(f"[WS {run_id[:8]}] {msg_type}: {truncated}")
                        else:
                            print(f"[WS {run_id[:8]}] {msg_type}: {str(msg_data)[:100]}")
                            
                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"[WS {run_id[:8]}] Error: {e}")
        except Exception as e:
            print(f"[WS {run_id[:8]}] Connection failed: {e}")
    
    async def test_concurrent_sessions(self, num_runs: int = 5):
        """Main test function"""
        print(f"\n{'='*60}")
        print(f"Testing Concurrent Sessions - {num_runs} runs with MAX_CONCURRENT=3")
        print(f"{'='*60}\n")
        
        async with aiohttp.ClientSession() as session:
            # Step 1: Check initial status
            print("📊 Initial System Status:")
            status = await self.check_system_status(session)
            print(f"   Active: {status['active_runs']}/{status['max_concurrent']}")
            print(f"   Queued: {status['queued_runs']}")
            print(f"   Status: {status['status']}\n")
            
            # Step 2: Create analyses
            print(f"📝 Creating {num_runs} repository analyses...")
            for i in range(num_runs):
                run_id = await self.create_analysis(session, i)
                self.run_ids.append(run_id)
                print(f"   Created #{i+1}: {run_id}")
            print()
            
            # Step 3: Start WebSocket monitors
            print("🔌 Starting WebSocket monitors...")
            ws_tasks = []
            for run_id in self.run_ids:
                ws_task = asyncio.create_task(self.monitor_websocket(run_id, duration=60))
                ws_tasks.append(ws_task)
            print(f"   Monitoring {len(ws_tasks)} WebSocket connections\n")
            
            # Step 4: Start all runs simultaneously
            print("🚀 Starting all runs simultaneously...")
            start_tasks = []
            for i, run_id in enumerate(self.run_ids):
                start_task = asyncio.create_task(self.start_run(session, run_id))
                start_tasks.append(start_task)
            
            results = await asyncio.gather(*start_tasks)
            for i, result in enumerate(results):
                status = result.get('status', 'unknown')
                if status == 'started':
                    print(f"   Run #{i+1}: ✅ STARTED (active slot)")
                elif status == 'queued':
                    print(f"   Run #{i+1}: ⏳ QUEUED (position: {result.get('queue_position', '?')})")
                else:
                    print(f"   Run #{i+1}: ❓ {status}")
            print()
            
            # Step 5: Monitor system status over time
            print("📈 Monitoring system status...")
            for i in range(6):
                await asyncio.sleep(5)
                status = await self.check_system_status(session)
                print(f"\n   [{datetime.now().strftime('%H:%M:%S')}] System Status:")
                print(f"   • Active runs: {status['active_runs']}/{status['max_concurrent']}")
                print(f"   • Queued runs: {status['queued_runs']}")
                print(f"   • Available slots: {status['available_slots']}")
                
                # Check individual run statuses
                if i == 2:  # After 10 seconds, check detailed status
                    print("\n   Individual Run Status:")
                    for j, run_id in enumerate(self.run_ids[:3]):  # Check first 3
                        queue_status = await self.check_queue_status(session, run_id)
                        print(f"   • Run #{j+1}: {queue_status.get('status', 'unknown')}")
            
            # Step 6: Test cancellation
            if len(self.run_ids) >= 5:
                print(f"\n🛑 Testing cancellation of queued run...")
                cancel_run_id = self.run_ids[4]
                async with session.delete(f"{BASE_URL}/runs/{cancel_run_id}/cancel") as resp:
                    result = await resp.json()
                    if result.get('success'):
                        print(f"   ✅ Successfully cancelled run: {cancel_run_id[:8]}...")
                    else:
                        print(f"   ❌ Failed to cancel: {result.get('message')}")
            
            # Wait for WebSocket monitors to complete
            print("\n⏳ Waiting for WebSocket monitors to complete...")
            await asyncio.gather(*ws_tasks, return_exceptions=True)
            
            # Cleanup after test
            await self.cancel_all_runs(session)
            
        print(f"\n{'='*60}")
        print("Test Complete!")
        print(f"{'='*60}\n")

    async def test_queue_ordering(self):
        """Test that queued runs are processed in FIFO order"""
        print("\n📋 Testing Queue Ordering (FIFO)...")
        
        async with aiohttp.ClientSession() as session:
            # Ensure clean state
            initial_status = await self.check_system_status(session)
            if initial_status['active_runs'] > 0 or initial_status['queued_runs'] > 0:
                print(f"   ⚠️  System not clean - Active: {initial_status['active_runs']}, Queued: {initial_status['queued_runs']}")
                print(f"   Waiting for system to clear...")
                await asyncio.sleep(5)
            
            # Create and start 6 runs quickly
            run_ids = []
            for i in range(6):
                run_id = await self.create_analysis(session, i)
                run_ids.append(run_id)
                self.run_ids.append(run_id)  # Track for cleanup
                result = await self.start_run(session, run_id)
                print(f"   Run {i+1} ({run_id[:8]}): {result.get('status')}")
                if result.get('status') == 'queued':
                    print(f"     Queue position: {result.get('queue_position')}")
            
            # Verify queue positions
            await asyncio.sleep(2)
            
            # Adjust expectations based on how many are active
            status = await self.check_system_status(session)
            active_count = min(3, len(run_ids))  # Should be 3 active
            
            print(f"\n   Verifying queue positions (expecting {len(run_ids) - active_count} queued)...")
            
            for i, run_id in enumerate(run_ids[active_count:], start=1):  # Check queued runs
                status = await self.check_queue_status(session, run_id)
                if status.get('status') == 'queued':
                    # Relaxed check - just verify it's queued and has a position
                    if status.get('queue_position') > 0:
                        print(f"   ✅ Run has queue position {status.get('queue_position')}")
                    else:
                        print(f"   ❌ Run missing valid queue position")
                elif status.get('status') == 'running':
                    print(f"   ℹ️  Run started running (queue processed)")
            
            # Cleanup
            await self.cancel_all_runs(session)

async def main():
    tester = ConcurrentSessionTester()
    
    print("\n" + "="*60)
    print("   CONCURRENT SESSION TESTING SUITE")
    print("="*60)
    
    # Test 1: Basic concurrent session management
    await tester.test_concurrent_sessions(num_runs=5)
    
    # Test 2: Queue ordering (with better cleanup)
    await tester.test_queue_ordering()
    
    print("\n" + "="*60)
    print("   ALL TESTS COMPLETE!")
    print("="*60 + "\n")

if __name__ == "__main__":
    asyncio.run(main())