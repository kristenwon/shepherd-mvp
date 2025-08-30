# models/db.py
import os
from typing import Optional, Dict, Any, List
from datetime import datetime
import uuid
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("Missing Supabase credentials in environment variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def create_repository_analysis(
    repository_url: str,
    project_description: str,
    environment: str,
    user_id: Optional[str] = None,
    reference_files: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Create a new repository analysis record in Supabase
    """
    run_id = str(uuid.uuid4())
    
    data = {
        "run_id": run_id,
        "repository_url": repository_url,
        "project_description": project_description,
        "environment": environment,
        "user_id": user_id or "@0xps",  # Default user
        "reference_files": reference_files or [],
        "status": "pending",  # Initial status
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat()
    }
    
    try:
        response = supabase.table("repository_analyses").insert(data).execute()
        return response.data[0] if response.data else data
    except Exception as e:
        print(f"Error creating repository analysis: {e}")
        # Return the data anyway for local development
        return data

def get_repository_analysis(run_id: str) -> Optional[Dict[str, Any]]:
    """
    Get a repository analysis by run_id
    """
    try:
        response = supabase.table("repository_analyses").select("*").eq("run_id", run_id).execute()
        return response.data[0] if response.data else None
    except Exception as e:
        print(f"Error fetching repository analysis: {e}")
        return None

def update_analysis_status(
    run_id: str, 
    status: str, 
    additional_data: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Update the status of a repository analysis
    
    Status can be: pending, queued, running, completed, failed, cancelled
    """
    update_data = {
        "status": status,
        "updated_at": datetime.utcnow().isoformat()
    }
    
    # Add status-specific fields
    if status == "running":
        update_data["started_at"] = datetime.utcnow().isoformat()
    elif status == "completed":
        update_data["completed_at"] = datetime.utcnow().isoformat()
    elif status == "failed" and additional_data:
        update_data["error"] = additional_data.get("error", "Unknown error")
        update_data["failed_at"] = datetime.utcnow().isoformat()
    elif status == "queued" and additional_data:
        update_data["queue_position"] = additional_data.get("queue_position", 0)
        update_data["estimated_wait"] = additional_data.get("estimated_wait", 0)
    
    # Merge any additional data
    if additional_data:
        update_data.update(additional_data)
    
    try:
        response = supabase.table("repository_analyses").update(update_data).eq("run_id", run_id).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error updating repository analysis status: {e}")
        return False

def list_user_analyses(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    List all repository analyses for a user
    """
    try:
        response = (
            supabase.table("repository_analyses")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        print(f"Error listing user analyses: {e}")
        return []

def delete_repository_analysis(run_id: str) -> bool:
    """
    Delete a repository analysis
    """
    try:
        response = supabase.table("repository_analyses").delete().eq("run_id", run_id).execute()
        return bool(response.data)
    except Exception as e:
        print(f"Error deleting repository analysis: {e}")
        return False

def get_queued_analyses() -> List[Dict[str, Any]]:
    """
    Get all analyses in queued status, ordered by creation time
    """
    try:
        response = (
            supabase.table("repository_analyses")
            .select("*")
            .eq("status", "queued")
            .order("created_at", asc=True)
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching queued analyses: {e}")
        return []

def get_active_analyses() -> List[Dict[str, Any]]:
    """
    Get all analyses currently running
    """
    try:
        response = (
            supabase.table("repository_analyses")
            .select("*")
            .eq("status", "running")
            .execute()
        )
        return response.data if response.data else []
    except Exception as e:
        print(f"Error fetching active analyses: {e}")
        return []