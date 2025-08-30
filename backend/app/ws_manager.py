# ws_manager.py
import asyncio, os
from collections import defaultdict, deque
from typing import Dict, Set, Optional
from fastapi import WebSocket
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()
class WebSocketManager:
    """
    WebSocket manager with idle tracking and auto-cancellation
    • Keeps {run_id → set(WebSocket)}  
    • Stores the last N messages so late joiners can catch up
    • Tracks idle time and auto-cancels after timeout
    """
    MAX_BUFFER = 2000         # keep last 2000 log msgs ≈ a few MB total
    IDLE_TIMEOUT_SECONDS = int(os.getenv("IDLE_TIMEOUT_SECONDS")) # 10 minutes = 600 seconds

    def __init__(self) -> None:
        self._conns: Dict[str, Set[WebSocket]] = defaultdict(set)
        self._buffers: Dict[str, deque] = defaultdict(lambda: deque(maxlen=self.MAX_BUFFER))
        
        # Idle tracking
        self._last_activity: Dict[str, datetime] = {}
        self._idle_check_task: Optional[asyncio.Task] = None
        self._run_manager = None  # Will be set by main.py
        
    def set_run_manager(self, run_manager):
        """Set reference to run manager for cancelling idle runs"""
        self._run_manager = run_manager
        
    async def start_idle_monitor(self):
        """Start the background task to monitor idle connections"""
        if self._idle_check_task is None or self._idle_check_task.done():
            self._idle_check_task = asyncio.create_task(self._monitor_idle_connections())
            print(f"🔍 Started idle connection monitor (timeout: {self.IDLE_TIMEOUT_SECONDS}s)")
    
    async def stop_idle_monitor(self):
        """Stop the idle monitor task"""
        if self._idle_check_task and not self._idle_check_task.done():
            self._idle_check_task.cancel()
            try:
                await self._idle_check_task
            except asyncio.CancelledError:
                pass
            print("🛑 Stopped idle connection monitor")

    async def _monitor_idle_connections(self):
        """Background task to check for idle connections and cancel them"""
        while True:
            try:
                await asyncio.sleep(30)  # Check every 30 seconds
                
                current_time = datetime.utcnow()
                idle_runs = []
                
                # Find idle runs
                for run_id, last_activity in self._last_activity.items():
                    idle_duration = (current_time - last_activity).total_seconds()
                    
                    if idle_duration > self.IDLE_TIMEOUT_SECONDS:
                        # Check if there are still active connections
                        if run_id in self._conns and self._conns[run_id]:
                            idle_runs.append((run_id, idle_duration))
                
                # Cancel idle runs
                for run_id, idle_duration in idle_runs:
                    print(f"⏰ Run {run_id[:8]} idle for {idle_duration:.0f}s, cancelling...")
                    
                    # Send idle timeout notification before cancelling
                    await self.send_log(run_id, {
                        "type": "idle_timeout",
                        "data": {
                            "message": f"Run cancelled due to inactivity ({self.IDLE_TIMEOUT_SECONDS}s timeout)",
                            "idle_duration": idle_duration,
                            "run_id": run_id
                        }
                    })
                    
                    # Cancel the run if run_manager is available
                    if self._run_manager:
                        success = await self._run_manager.cancel_run(run_id)
                        if success:
                            print(f"✅ Successfully cancelled idle run {run_id[:8]}")
                    
                    # Close all WebSocket connections for this run
                    await self.close_all_connections(run_id, reason="Idle timeout")
                    
                    # Clean up tracking
                    if run_id in self._last_activity:
                        del self._last_activity[run_id]
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error in idle monitor: {e}")
                await asyncio.sleep(60)  # Wait longer on error

    async def connect(self, run_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._conns[run_id].add(ws)
        
        # Update activity timestamp
        self._last_activity[run_id] = datetime.utcnow()

        # ① application-level confirmation
        await ws.send_json({"type": "connection_ack", "run_id": run_id})

        # ② dump any backlog (if the run already started)
        for msg in self._buffers[run_id]:
            await ws.send_json(msg)

    def disconnect(self, run_id: str, ws: WebSocket) -> None:
        self._conns[run_id].discard(ws)
        
        # If no more connections for this run, remove from activity tracking
        if run_id not in self._conns or not self._conns[run_id]:
            if run_id in self._last_activity:
                del self._last_activity[run_id]
            # Clean up buffers if no connections
            if run_id in self._buffers:
                del self._buffers[run_id]

    async def send_log(self, run_id: str, message: dict):
        """Send a log message to all connected clients for a run"""
        # Update activity timestamp when sending messages
        self._last_activity[run_id] = datetime.utcnow()
        
        # Store message in buffer for late joiners
        self._buffers[run_id].append(message)
        
        if run_id in self._conns:
            disconnected = []
            for ws in self._conns[run_id]:
                try:
                    await ws.send_json(message)
                    
                    # If this is a cancellation message, schedule the connection to close
                    if (message.get("type") == "run_cancelled" and 
                        message.get("data", {}).get("action") == "close_connection"):
                        # Don't await the close, just schedule it
                        asyncio.create_task(self._close_connection(ws))
                        disconnected.append(ws)
                        
                except Exception as e:
                    print(f"Error sending to websocket: {e}")
                    disconnected.append(ws)
            
            # Remove disconnected websockets
            for ws in disconnected:
                self.disconnect(run_id, ws)

    async def receive_activity(self, run_id: str):
        """Update activity timestamp when receiving messages from client"""
        self._last_activity[run_id] = datetime.utcnow()

    async def _close_connection(self, ws):
        """Close a WebSocket connection gracefully"""
        try:
            await ws.close(code=1001, reason="Run cancelled")
        except Exception as e:
            print(f"Error closing WebSocket: {e}")
    
    async def close_all_connections(self, run_id: str, reason: str = "Run ended"):
        """Close all WebSocket connections for a specific run"""
        if run_id in self._conns:
            connections = list(self._conns[run_id])  # Copy to avoid modification during iteration
            
            for ws in connections:
                try:
                    await ws.close(code=1001, reason=reason)
                except Exception as e:
                    print(f"Error closing WebSocket for run {run_id}: {e}")
                
                self.disconnect(run_id, ws)
            
            # Ensure the run is completely removed
            if run_id in self._conns:
                del self._conns[run_id]
    
    def get_idle_status(self) -> Dict[str, dict]:
        """Get current idle status for all runs"""
        current_time = datetime.utcnow()
        idle_status = {}
        
        for run_id, last_activity in self._last_activity.items():
            idle_duration = (current_time - last_activity).total_seconds()
            idle_status[run_id] = {
                "last_activity": last_activity.isoformat(),
                "idle_seconds": idle_duration,
                "will_timeout_in": max(0, self.IDLE_TIMEOUT_SECONDS - idle_duration),
                "connection_count": len(self._conns.get(run_id, set()))
            }
        
        return idle_status