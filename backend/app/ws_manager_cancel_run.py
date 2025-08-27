# ws_manager.py
from collections import defaultdict, deque
from typing import Dict, Set
from fastapi import WebSocket
class WebSocketManager:
    """
    • Keeps {run_id → set(WebSocket)}  
    • Stores the last N messages so late joiners can catch up
    """
    MAX_BUFFER = 2000         # keep last 2 000 log msgs ≈ a few MB total

    def __init__(self) -> None:
        self._conns:   Dict[str, Set[WebSocket]] = defaultdict(set)
        self._buffers: Dict[str, deque]          = defaultdict(lambda: deque(maxlen=self.MAX_BUFFER))

    async def connect(self, run_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self._conns[run_id].add(ws)

        # ① application-level confirmation
        await ws.send_json({"type": "connection_ack", "run_id": run_id})

        # ② dump any backlog (if the run already started)
        for msg in self._buffers[run_id]:
            await ws.send_json(msg)

    def disconnect(self, run_id: str, ws: WebSocket) -> None:
        self._conns[run_id].discard(ws)

    # In your WebSocketManager class (ws_manager.py), update the send_log method:

    async def send_log(self, run_id: str, message: dict):
        """Send a log message to all connected clients for a run"""
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

    async def _close_connection(self, ws):
        """Close a WebSocket connection gracefully"""
        try:
            await ws.close(code=1001, reason="Run cancelled")
        except Exception as e:
            print(f"Error closing WebSocket: {e}")