# main.py
import asyncio
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, Optional, List
import json
from datetime import datetime
from enum import Enum
import os, time
import signal
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from .utils import save_email_to_firestore
from .ws_manager import WebSocketManager
from .mas_bridge_tags_output import launch_mas_interactive, create_ws_input_handler
from .models.db import create_repository_analysis, get_repository_analysis, update_analysis_status, list_user_analyses, delete_repository_analysis
from .models.waitlist import WaitlistRequest
from dotenv import load_dotenv

load_dotenv()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    print("🚀 Starting Shepherd service...")
    
    # Clean up orphaned MAS processes from previous session
    if run_manager.pid_file.exists():
        print("🧹 Cleaning up orphaned processes from previous session...")
        run_manager.load_orphaned_pids()
    
    # Set run manager reference in WebSocketManager
    ws_manager.set_run_manager(run_manager)
    
    # Start idle connection monitor
    await ws_manager.start_idle_monitor()
    
    yield  # Server runs here
    
    # === SHUTDOWN ===
    print("\n🛑 Shutting down Shepherd service...")
    
    # Stop idle monitor
    await ws_manager.stop_idle_monitor()
    
    # Kill all currently running MAS processes
    if run_manager.process_pids:
        print(f"   Killing {len(run_manager.process_pids)} active MAS processes...")
        for run_id, pid in run_manager.process_pids.items():
            run_manager.kill_process(pid)
            print(f"   ✔ Killed process {pid} for run {run_id[:8]}")
    
    # Clean up PID file
    if run_manager.pid_file.exists():
        run_manager.pid_file.unlink()
    
    print("👋 Shutdown complete!")


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Or specify your domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
ws_manager = WebSocketManager()

# Store input queues for each run
input_queues: Dict[str, asyncio.Queue] = {}

# Pydantic Models
class JobRequest(BaseModel):
    github_url: str

class RepositoryAnalysisRequest(BaseModel):
    repository_url: str
    project_description: str
    environment: str  # "local" or "testnet"
    user_id: Optional[str] = None
    reference_files: Optional[List[str]] = None

class RepositoryUpdateRequest(BaseModel):
    repository_url: Optional[str] = None
    project_description: Optional[str] = None
    environment: Optional[str] = None
    reference_files: Optional[List[str]] = None

# Enums and Classes for Run Management
class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RunManager:
    """Simplified run manager - only tracks active runs, no queuing"""
    def __init__(self):
        self.max_concurrent = int(os.getenv("MAX_CONCURRENT_RUNS"))
        self.active_runs: Dict[str, dict] = {}
        self.completed_runs: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self.process_pids: Dict[str, int] = {}
        self.pid_file = Path("./backend/logs/active_pids.json")
        self.load_orphaned_pids()  # Call cleanup on init
        
    async def can_start_run(self) -> bool:
        """Check if we can start a new run"""
        async with self._lock:
            return len(self.active_runs) < self.max_concurrent
    
    async def add_run(self, run_id: str, job_data: dict) -> dict:
        """Add a new run if capacity is available"""
        async with self._lock:
            if len(self.active_runs) < self.max_concurrent:
                # Start immediately
                self.active_runs[run_id] = {
                    "run_id": run_id,
                    "status": RunStatus.RUNNING,
                    "started_at": datetime.utcnow().isoformat(),
                    "job_data": job_data
                }
                return {"status": "started", "run_id": run_id}
            else:
                # At capacity
                return {
                    "status": "at_capacity",
                    "message": "At capacity, please come back and try again."
                }
    
    async def complete_run(self, run_id: str, success: bool = True):
        """Mark a run as completed"""
        async with self._lock:
            if run_id in self.active_runs:
                run_data = self.active_runs.pop(run_id)
                run_data["status"] = RunStatus.COMPLETED if success else RunStatus.FAILED
                run_data["completed_at"] = datetime.utcnow().isoformat()
                self.completed_runs[run_id] = run_data
    
    async def cancel_run(self, run_id: str) -> bool:
        """Cancel an active run"""
        async with self._lock:
            if run_id in self.process_pids:
                pid = self.process_pids[run_id]
                if self.kill_process(pid):
                    print(f"Killed process {pid} for run {run_id[:8]}")
                self.unregister_process(run_id)
            
            # Check if it's an active run
            if run_id in self.active_runs:
                run_data = self.active_runs.pop(run_id)
                run_data["status"] = RunStatus.CANCELLED
                run_data["cancelled_at"] = datetime.utcnow().isoformat()
                self.completed_runs[run_id] = run_data
                return True
            
            return False
    
    async def get_system_status(self) -> dict:
        """Get current system status with active runs information"""
        async with self._lock:
            # Get active runs with details
            active_runs_info = []
            for run_id, run_data in self.active_runs.items():
                active_runs_info.append({
                    "run_id": run_id,
                    "status": run_data["status"],
                    "started_at": run_data["started_at"],
                    "github_url": run_data["job_data"].get("github_url") if "job_data" in run_data else None
                })
            
            # Get recently completed runs (optional - last 5)
            recent_completed = []
            # Sort completed runs by completed_at timestamp and get last 5
            sorted_completed = sorted(
                self.completed_runs.items(),
                key=lambda x: x[1].get("completed_at", ""),
                reverse=True
            )[:5]
            
            for run_id, run_data in sorted_completed:
                recent_completed.append({
                    "run_id": run_id,
                    "status": run_data["status"],
                    "completed_at": run_data.get("completed_at"),
                    "github_url": run_data["job_data"].get("github_url") if "job_data" in run_data else None
                })
            
            return {
                "max_concurrent": self.max_concurrent,
                "active_runs_count": len(self.active_runs),
                "available_slots": self.max_concurrent - len(self.active_runs),
                "system_status": "at_capacity" if len(self.active_runs) >= self.max_concurrent else "available",
                "active_runs": active_runs_info,
                "recent_completed": recent_completed
            }
    
    async def get_run_status(self, run_id: str) -> dict:
        """Get status of a specific run"""
        async with self._lock:
            # Check active runs
            if run_id in self.active_runs:
                return {"run_id": run_id, "status": "running"}
            
            # Check completed runs
            if run_id in self.completed_runs:
                return {
                    "run_id": run_id,
                    "status": self.completed_runs[run_id]["status"]
                }
            
            return {"run_id": run_id, "status": "not_found"}

    def load_orphaned_pids(self):
        """Load PIDs from previous session and clean them up"""
        if self.pid_file.exists():
            try:
                with open(self.pid_file, 'r') as f:
                    orphaned_pids = json.load(f)
                
                print(f"🧹 Found {len(orphaned_pids)} potentially orphaned processes")
                
                for run_id, pid in orphaned_pids.items():
                    if self.is_process_running(pid):
                        print(f"   Killing orphaned process {pid} from run {run_id[:8]}...")
                        self.kill_process(pid)
                    else:
                        print(f"   Process {pid} already dead")
                
                # Clear the file after cleanup
                self.pid_file.unlink()
                
            except Exception as e:
                print(f"   Could not load orphaned PIDs: {e}")

    def save_active_pids(self):
        """Save current PIDs to file for recovery after crash"""
        try:
            self.pid_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.pid_file, 'w') as f:
                json.dump(self.process_pids, f)
        except Exception as e:
            print(f"Could not save PIDs: {e}")
    
    def register_process(self, run_id: str, pid: int):
        """Register a new MAS process"""
        self.process_pids[run_id] = pid
        self.save_active_pids()
        
    def unregister_process(self, run_id: str):
        """Remove a process from tracking"""
        if run_id in self.process_pids:
            del self.process_pids[run_id]
            self.save_active_pids()
            
    @staticmethod
    def is_process_running(pid: int) -> bool:
        """Check if a process is still running"""
        try:
            # Send signal 0 (doesn't actually kill, just checks)
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False

    @staticmethod
    def kill_process(pid: int, timeout: int = 5):
        """Kill a process gracefully, then forcefully if needed"""
        try:
            # First try graceful shutdown (SIGTERM)
            os.kill(pid, signal.SIGTERM)
            
            # Wait up to timeout seconds
            for _ in range(timeout * 10):
                if not RunManager.is_process_running(pid):
                    return True
                time.sleep(0.1)
            
            # Force kill if still running (SIGKILL)
            os.kill(pid, signal.SIGKILL)
            return True
            
        except (OSError, ProcessLookupError):
            # Process already dead
            return True

# Initialize the run manager
run_manager = RunManager()

# System Status Endpoints
@app.get("/system/status")
async def get_system_status():
    """Get current system status including active runs"""
    status = await run_manager.get_system_status()
    return status

@app.get("/runs/{run_id}/status")
async def get_run_status(run_id: str):
    """Check status for a specific run"""
    status = await run_manager.get_run_status(run_id)
    if status["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    return status

@app.delete("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel an active run and notify WebSocket connections to close"""
    success = await run_manager.cancel_run(run_id)
    
    if success:
        # Send cancellation message to connected WebSocket clients
        # They should close themselves upon receiving this message
        try:
            await ws_manager.send_log(run_id, {
                "type": "run_cancelled",
                "data": {
                    "message": "Run has been cancelled",
                    "run_id": run_id,
                    "action": "close_connection"  # Signal to close
                }
            })
        except Exception as e:
            print(f"Error sending cancellation message: {e}")
        
        # Clean up WebSocket connections from the manager without awaiting close
        if run_id in ws_manager._conns:
            # Just remove the connections from tracking without trying to close them
            del ws_manager._conns[run_id]
        
        # Clean up input queue if exists
        if run_id in input_queues:
            del input_queues[run_id]
            
        return {"success": True, "message": f"Run {run_id} cancelled"}
    else:
        return {"success": False, "message": "Run not found or already completed"}

# Repository Analysis Endpoints
@app.post("/api/repository-analysis")
async def create_repository_analysis_endpoint(request: RepositoryAnalysisRequest):
    """Create a new repository analysis request and store in Supabase"""
    try:
        # Validate environment
        if request.environment not in ["local", "testnet"]:
            raise HTTPException(status_code=400, detail="Environment must be 'local' or 'testnet'")
        
        # Create the analysis record in Supabase
        analysis_record = create_repository_analysis(
            repository_url=request.repository_url,
            project_description=request.project_description,
            environment=request.environment,
            user_id=request.user_id,
            reference_files=request.reference_files
        )
        
        return JSONResponse({
            "success": True,
            "run_id": analysis_record["run_id"],
            "message": "Repository analysis created successfully",
            "data": analysis_record
        }, status_code=201)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create repository analysis: {str(e)}")

@app.get("/api/repository-analysis/{run_id}")
async def get_repository_analysis_endpoint(run_id: str):
    """Get a repository analysis by run_id"""
    try:
        analysis = get_repository_analysis(run_id)
        
        if not analysis:
            raise HTTPException(status_code=404, detail="Repository analysis not found")
        
        return JSONResponse({
            "success": True,
            "data": analysis
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch repository analysis: {str(e)}")

@app.get("/api/my-repositories")
async def get_my_repositories(user_id: str = "@0xps", limit: int = 50):
    """Get all repository analyses for a user (My Repositories)"""
    try:
        repositories = list_user_analyses(user_id, limit)
        
        # Format the response to match the UI
        formatted_repos = []
        for repo in repositories:
            # Extract repository name from URL for display
            repo_name = repo["repository_url"].split("/")[-1] if repo["repository_url"] else "Unknown"
            
            formatted_repos.append({
                "run_id": repo["run_id"],
                "repository_url": repo["repository_url"],
                "repository_name": repo_name,
                "environment": repo["environment"],
                "status": repo["status"],
                "created_at": repo["created_at"],
                "updated_at": repo["updated_at"]
            })
        
        return JSONResponse({
            "success": True,
            "data": formatted_repos
        })
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch repositories: {str(e)}")

@app.put("/api/repository-analysis/{run_id}")
async def update_repository_analysis_endpoint(run_id: str, request: RepositoryUpdateRequest):
    """Update a repository analysis"""
    try:
        # Get existing analysis
        existing_analysis = get_repository_analysis(run_id)
        
        if not existing_analysis:
            raise HTTPException(status_code=404, detail="Repository analysis not found")
        
        # Prepare update data
        update_data = {}
        
        if request.repository_url is not None:
            update_data["repository_url"] = request.repository_url
        if request.project_description is not None:
            update_data["project_description"] = request.project_description
        if request.environment is not None:
            if request.environment not in ["local", "testnet"]:
                raise HTTPException(status_code=400, detail="Environment must be 'local' or 'testnet'")
            update_data["environment"] = request.environment
        if request.reference_files is not None:
            update_data["reference_files"] = request.reference_files
        
        # Update the analysis
        update_analysis_status(run_id, existing_analysis["status"], update_data)
        
        # Get updated analysis
        updated_analysis = get_repository_analysis(run_id)
        
        return JSONResponse({
            "success": True,
            "message": "Repository analysis updated successfully",
            "data": updated_analysis
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update repository analysis: {str(e)}")

@app.delete("/api/repository-analysis/{run_id}")
async def delete_repository_analysis_endpoint(run_id: str):
    """Delete a repository analysis"""
    try:
        # Get existing analysis
        existing_analysis = get_repository_analysis(run_id)
        
        if not existing_analysis:
            raise HTTPException(status_code=404, detail="Repository analysis not found")
        
        # Delete from Supabase
        success = delete_repository_analysis(run_id)
        
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete repository analysis")
        
        return JSONResponse({
            "success": True,
            "message": "Repository analysis deleted successfully"
        })
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete repository analysis: {str(e)}")

# Run Management Endpoint (WITHOUT QUEUE - JUST CAPACITY CHECK)
@app.post("/runs/{run_id}")
async def start_run(run_id: str, job: JobRequest, tasks: BackgroundTasks):
    """Kick off MAS in the background with WebSocket-based interaction - no queuing."""
    
    # Add run to manager (will either start or return at_capacity)
    result = await run_manager.add_run(run_id, job.dict())
    
    if result["status"] == "started":
        # Create input queue for this run
        input_queues[run_id] = asyncio.Queue()
        
        # Create the WebSocket-based input handler
        input_handler = create_ws_input_handler(run_id, input_queues[run_id])
        
        # Wrapper to handle completion
        async def run_with_completion():
            try:
                result = await launch_mas_interactive(
                    run_id=run_id,
                    job=job.dict(),
                    input_handler=input_handler,
                    ws_manager=ws_manager,
                    log_dir="./backend/logs",
                    input_queues=input_queues
                )
                if 'pid' in result:
                    run_manager.register_process(run_id, result['pid'])
                success = result.get("success", False)
            except Exception as e:
                print(f"Error in run {run_id}: {e}")
                success = False
            finally:
                run_manager.unregister_process(run_id)
                # Mark as complete
                await run_manager.complete_run(run_id, success)
                
                # Clean up input queue
                if run_id in input_queues:
                    del input_queues[run_id]
        
        # Start MAS in background
        tasks.add_task(run_with_completion)
        
        return JSONResponse({
            "status": "started",
            "run_id": run_id
        }, status_code=202)
    
    elif result["status"] == "at_capacity":
        return JSONResponse({
            "status": "at_capacity",
            "message": result["message"]
        }, status_code=503)  # 503 Service Unavailable
    
    else:
        raise HTTPException(status_code=500, detail="Unexpected status from run manager")

# Update the WebSocket endpoint to track activity
@app.websocket("/ws/{run_id}")
async def run_logs_ws(ws: WebSocket, run_id: str):
    """
    WebSocket endpoint for bidirectional communication with MAS.
    - Sends MAS output and prompts to client
    - Receives user input from client
    - Tracks activity for idle timeout
    - Closes itself when run is cancelled
    """
    await ws_manager.connect(run_id, ws)
    
    try:
        while True:
            # Wait for messages from client
            data = await ws.receive_text()
            
            # Update activity timestamp when receiving data
            await ws_manager.receive_activity(run_id)
            
            try:
                message = json.loads(data)
                
                # Handle input messages from client
                if message.get("type") == "input":
                    user_input = message.get("data", "")
                    
                    # Put input in the queue for MAS to consume
                    if run_id in input_queues:
                        await input_queues[run_id].put(user_input)
                    else:
                        # Send error if run not found
                        await ws.send_json({
                            "type": "error",
                            "data": "Run not found or not ready for input"
                        })
                
                # Handle ping messages (keep-alive)
                elif message.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                    # Ping counts as activity
                    await ws_manager.receive_activity(run_id)
                    
            except json.JSONDecodeError:
                await ws.send_json({
                    "type": "error",
                    "data": "Invalid JSON message"
                })
                
    except WebSocketDisconnect:
        ws_manager.disconnect(run_id, ws)
        # Clean up the input queue if no more connections
        if run_id in input_queues and not ws_manager._conns.get(run_id):
            del input_queues[run_id]
    except Exception as e:
        print(f"WebSocket error for run {run_id}: {e}")
        ws_manager.disconnect(run_id, ws)

# Add a new endpoint to check idle status
@app.get("/system/idle-status")
async def get_idle_status():
    """Get idle status for all active WebSocket connections"""
    idle_status = ws_manager.get_idle_status()
    return {
        "idle_timeout_seconds": ws_manager.IDLE_TIMEOUT_SECONDS,
        "runs": idle_status
    }

@app.websocket("/echo/{run_id}")
async def _echo(ws: WebSocket, run_id: str):
    """Simple echo endpoint for testing WebSocket connectivity."""
    await ws.accept()
    await ws.send_text(f"hello {run_id}")
    
    try:
        while True:
            data = await ws.receive_text()
            await ws.send_text(f"echo: {data}")
    except WebSocketDisconnect:
        pass

# Health check endpoint
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "shepherd-mvp"}

@app.get("/settings")
async def settings():
    return {"MAX_CONCURRENT_RUNS": os.getenv("MAX_CONCURRENT_RUNS"), 
            "IDLE_TIMEOUT_SECONDS": os.getenv("IDLE_TIMEOUT_SECONDS")}

@app.post("/save-waitlist-email")
async def save_waitlist_email(payload: WaitlistRequest):
    try:
        save_email_to_firestore(payload.email)
        return {"success": True, "message": "Email saved to waitlist"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save email: {str(e)}")
    
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)