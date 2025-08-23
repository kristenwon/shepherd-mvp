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

from .ws_manager import WebSocketManager
from .mas_bridge_tags_output import launch_mas_interactive, create_ws_input_handler
from .models.db import create_repository_analysis, get_repository_analysis, update_analysis_status, list_user_analyses, delete_repository_analysis

@asynccontextmanager
async def lifespan(app: FastAPI):
    # === STARTUP ===
    print("🚀 Starting Shepherd service...")
    
    # Clean up orphaned MAS processes from previous session
    if run_manager.pid_file.exists():
        print("🧹 Cleaning up orphaned processes from previous session...")
        run_manager.load_orphaned_pids()
    
    yield  # Server runs here
    
    # === SHUTDOWN ===
    print("\n🛑 Shutting down Shepherd service...")
    
    # Kill all currently running MAS processes
    if run_manager.process_pids:
        print(f"   Killing {len(run_manager.process_pids)} active MAS processes...")
        for run_id, pid in run_manager.process_pids.items():
            run_manager.kill_process(pid)
            print(f"   ✓ Killed process {pid} for run {run_id[:8]}")
    
    # Clean up PID file
    if run_manager.pid_file.exists():
        run_manager.pid_file.unlink()
    
    print("👋 Shutdown complete!")

app = FastAPI(lifespan=lifespan)
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

# Enums and Classes for Queue Management
class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class RunManager:
    """Manages concurrent runs and queuing"""
    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self.active_runs: Dict[str, dict] = {}
        self.queued_runs: List[dict] = []
        self.completed_runs: Dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self.process_pids: Dict[str, int] = {}
        self.pid_file = Path("./backend/logs/active_pids.json")
        self.load_orphaned_pids()  # Call cleanup on init
    async def add_run(self, run_id: str, job_data: dict) -> dict:
        """Add a new run, either starting it or queuing it"""
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
                # Queue the run
                queue_position = len(self.queued_runs) + 1
                queued_run = {
                    "run_id": run_id,
                    "status": RunStatus.QUEUED,
                    "queued_at": datetime.utcnow().isoformat(),
                    "queue_position": queue_position,
                    "job_data": job_data
                }
                self.queued_runs.append(queued_run)
                return {"status": "queued", "run_id": run_id, "queue_position": queue_position}
    
    async def complete_run(self, run_id: str, success: bool = True):
        """Mark a run as completed and start next queued run if any"""
        async with self._lock:
            if run_id in self.active_runs:
                run_data = self.active_runs.pop(run_id)
                run_data["status"] = RunStatus.COMPLETED if success else RunStatus.FAILED
                run_data["completed_at"] = datetime.utcnow().isoformat()
                self.completed_runs[run_id] = run_data
                
                # Start next queued run if any
                if self.queued_runs:
                    next_run = self.queued_runs.pop(0)
                    next_run_id = next_run["run_id"]
                    
                    # Update queue positions for remaining queued runs
                    for i, run in enumerate(self.queued_runs):
                        run["queue_position"] = i + 1
                    
                    # Start the next run
                    self.active_runs[next_run_id] = {
                        "run_id": next_run_id,
                        "status": RunStatus.RUNNING,
                        "started_at": datetime.utcnow().isoformat(),
                        "job_data": next_run["job_data"]
                    }
                    
                    # Notify via WebSocket that the run has started
                    if ws_manager:
                        await ws_manager.send_log(next_run_id, {
                            "type": "status_change",
                            "data": {"status": "started", "message": "Run started from queue"}
                        })
                    
                    # Return the next run to be started
                    return next_run
        return None
    
    async def cancel_run(self, run_id: str) -> bool:
        """Cancel a run (either active or queued)"""
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
                
                # Start next queued run if any
                if self.queued_runs:
                    next_run = self.queued_runs.pop(0)
                    if next_run:
                        next_run_id = next_run["run_id"]
                        # Update queue positions
                        for i, run in enumerate(self.queued_runs):
                            run["queue_position"] = i + 1
                        # Start the next run
                        self.active_runs[next_run_id] = {
                            "run_id": next_run_id,
                            "status": RunStatus.RUNNING,
                            "started_at": datetime.utcnow().isoformat(),
                            "job_data": next_run["job_data"]
                        }
                        # Schedule the queued run to start
                        asyncio.create_task(start_queued_run(next_run))
                return True
            
            # Check if it's a queued run
            for i, run in enumerate(self.queued_runs):
                if run["run_id"] == run_id:
                    self.queued_runs.pop(i)
                    # Update queue positions
                    for j, remaining_run in enumerate(self.queued_runs[i:], start=i):
                        remaining_run["queue_position"] = j + 1
                    return True
            
            return False
    
    async def get_system_status(self) -> dict:
        """Get current system status with detailed run information"""
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
            
            # Get queued runs with details
            queued_runs_info = []
            for run in self.queued_runs:
                queued_runs_info.append({
                    "run_id": run["run_id"],
                    "status": run["status"],
                    "queued_at": run["queued_at"],
                    "queue_position": run["queue_position"],
                    "github_url": run["job_data"].get("github_url") if "job_data" in run else None
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
                "queued_runs_count": len(self.queued_runs),
                "available_slots": self.max_concurrent - len(self.active_runs),
                "system_status": "at_capacity" if len(self.active_runs) >= self.max_concurrent else "available",
                "active_runs": active_runs_info,
                "queued_runs": queued_runs_info,
                "recent_completed": recent_completed
            }
    
    async def get_queue_status(self, run_id: str) -> dict:
        """Get status of a specific run"""
        async with self._lock:
            # Check active runs
            if run_id in self.active_runs:
                return {"run_id": run_id, "status": "running"}
            
            # Check queued runs
            for run in self.queued_runs:
                if run["run_id"] == run_id:
                    return {
                        "run_id": run_id,
                        "status": "queued",
                        "queue_position": run["queue_position"]
                    }
            
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
run_manager = RunManager(max_concurrent=3)

# Helper function for starting queued runs
async def start_queued_run(queued_run: dict):
    """Start a previously queued run"""
    run_id = queued_run["run_id"]
    job_data = queued_run["job_data"]
    
    # Create input queue for this run
    input_queues[run_id] = asyncio.Queue()
    
    # Create the WebSocket-based input handler
    input_handler = create_ws_input_handler(run_id, input_queues[run_id])
    
    # Start the run
    try:
        result = await launch_mas_interactive(
            run_id=run_id,
            job=job_data,
            input_handler=input_handler,
            ws_manager=ws_manager,
            log_dir="./backend/logs"
        )
        success = result.get("success", False)
    except Exception as e:
        print(f"Error in queued run {run_id}: {e}")
        success = False
    finally:
        # Mark as complete and potentially start next queued run
        next_run = await run_manager.complete_run(run_id, success)
        
        # Clean up input queue
        if run_id in input_queues:
            del input_queues[run_id]
        
        # If there's another queued run, start it
        if next_run:
            await start_queued_run(next_run)

# System Status Endpoints
@app.get("/system/status")
async def get_system_status():
    """Get current system status including active and queued runs"""
    status = await run_manager.get_system_status()
    return status

@app.get("/runs/{run_id}/queue-status")
async def get_queue_status(run_id: str):
    """Get queue status for a specific run"""
    status = await run_manager.get_queue_status(run_id)
    if status["status"] == "not_found":
        raise HTTPException(status_code=404, detail="Run not found")
    return status

@app.delete("/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel a run (either active or queued)"""
    success = await run_manager.cancel_run(run_id)
    if success:
        # Also clean up input queue if exists
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

# Run Management Endpoint (WITH QUEUE SUPPORT)
@app.post("/runs/{run_id}")
async def start_run(run_id: str, job: JobRequest, tasks: BackgroundTasks):
    """Kick off MAS in the background with WebSocket-based interaction and queue management."""
    
    # Add run to manager (will either start or queue it)
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
                    log_dir="./backend/logs"
                )
                if 'pid' in result:
                    run_manager.register_process(run_id, result['pid'])
                success = result.get("success", False)
            except Exception as e:
                print(f"Error in run {run_id}: {e}")
                success = False
            finally:
                run_manager.unregister_process(run_id)
                # Mark as complete and potentially start next queued run
                next_run = await run_manager.complete_run(run_id, success)
                
                # Clean up input queue
                if run_id in input_queues:
                    del input_queues[run_id]
                
                # If there's a next run to start, do it
                if next_run:
                    await start_queued_run(next_run)
        
        # Start MAS in background
        tasks.add_task(run_with_completion)
        
        return JSONResponse({
            "status": "started",
            "run_id": run_id
        }, status_code=202)
    
    elif result["status"] == "queued":
        return JSONResponse({
            "status": "queued",
            "run_id": run_id,
            "queue_position": result["queue_position"],
            "message": f"Run queued at position {result['queue_position']}"
        }, status_code=202)
    
    else:
        raise HTTPException(status_code=500, detail="Unexpected status from run manager")

@app.get("/runs/{run_id}/status")
async def get_run_status(run_id: str):
    """Check if a run is active and ready for input."""
    is_active = run_id in input_queues
    queue_status = await run_manager.get_queue_status(run_id)
    
    return JSONResponse({
        "run_id": run_id,
        "active": is_active,
        "ready_for_input": is_active,
        "status": queue_status["status"],
        "queue_position": queue_status.get("queue_position")
    })

# WebSocket Endpoints
@app.websocket("/ws/{run_id}")
async def run_logs_ws(ws: WebSocket, run_id: str):
    """
    WebSocket endpoint for bidirectional communication with MAS.
    - Sends MAS output and prompts to client
    - Receives user input from client
    """
    await ws_manager.connect(run_id, ws)
    
    try:
        while True:
            # Wait for messages from client
            data = await ws.receive_text()
            
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
                
                # Handle other message types if needed
                elif message.get("type") == "ping":
                    await ws.send_json({"type": "pong"})
                    
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


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)