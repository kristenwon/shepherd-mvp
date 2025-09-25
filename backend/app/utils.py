from dotenv import load_dotenv
import firebase_admin
import os
import pathlib
import uuid
from firebase_admin import credentials, firestore, storage
from datetime import datetime
from typing import Optional, Dict, Any

load_dotenv()


def initialize_firebase():
    """Initialize Firebase Admin SDK if not already initialized"""
    try:
        firebase_admin.get_app()
    except ValueError:
        # Firebase not initialized yet
        service_account_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH")
        if service_account_path:
            cred = credentials.Certificate(service_account_path)
            firebase_admin.initialize_app(cred)
        else:
            raise ValueError(
                "FIREBASE_SERVICE_ACCOUNT_PATH not found in environment variables")


def get_firestore_client():
    """Get Firestore client instance"""
    initialize_firebase()
    return firestore.client()


def save_email_to_firestore(email: str) -> None:
    """When user gets at capacity pop up, save email to Firestore collection 'waitlist'"""
    db = get_firestore_client()
    document_id = str(uuid.uuid4())
    doc_ref = db.collection("waitlist").document(document_id)
    doc_ref.set({
        "email": email,
        "timestamp": firestore.SERVER_TIMESTAMP
    })


def save_hypothesis_to_firestore(run_id: str, hypothesis: str, github_url: str, user_id: str = None) -> None:
    """Save hypothesis to Firestore collection 'hypotheses'"""
    db = get_firestore_client()
    doc_ref = db.collection(
        os.getenv("HYPOTHESIS_COLLECTION")).document(run_id)
    doc_ref.set({
        "run_id": run_id,
        "hypothesis": hypothesis,
        "github_url": github_url,
        "timestamp": firestore.SERVER_TIMESTAMP
    })


def save_run_request_to_firestore(
    run_id: str,
    github_url: str,
    tunnel_url: str,
    assets_path: Optional[str] = None,
    assets_metadata: Optional[Dict[str, Any]] = None,
    status: str = "started"
) -> Dict[str, Any]:
    """
    Save run request data to Firestore collection 'runs'

    Args:
        run_id: Unique identifier for the run
        github_url: GitHub repository URL
        tunnel_url: Tunnel URL for the run
        assets_path: Local path where assets file was saved
        assets_metadata: Metadata about the uploaded assets file
        status: Initial status of the run

    Returns:
        Dict containing the saved document data
    """
    db = get_firestore_client()

    # Prepare the document data
    doc_data = {
        "run_id": run_id,
        "github_url": github_url,
        "tunnel_url": tunnel_url,
        "status": status,
        "created_at": firestore.SERVER_TIMESTAMP,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    # Add assets information if provided
    if assets_path:
        doc_data["assets_path"] = assets_path

    if assets_metadata:
        doc_data["assets_metadata"] = assets_metadata

    # Save to Firestore
    doc_ref = db.collection("runs").document(run_id)
    doc_ref.set(doc_data)

    # Return the data (with client-side timestamp for immediate use)
    doc_data["created_at"] = datetime.utcnow().isoformat()
    doc_data["updated_at"] = datetime.utcnow().isoformat()

    return doc_data


def update_run_status_in_firestore(
    run_id: str,
    status: str,
    additional_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Update the status of a run in Firestore

    Args:
        run_id: Unique identifier for the run
        status: New status for the run (e.g., "completed", "failed", "cancelled")
        additional_data: Any additional data to update
    """
    db = get_firestore_client()
    doc_ref = db.collection("runs").document(run_id)

    update_data = {
        "status": status,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    # Add completion timestamp for terminal states
    if status in ["completed", "failed", "cancelled"]:
        update_data[f"{status}_at"] = firestore.SERVER_TIMESTAMP

    # Add any additional data
    if additional_data:
        update_data.update(additional_data)

    doc_ref.update(update_data)


def get_run_from_firestore(run_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a run document from Firestore

    Args:
        run_id: Unique identifier for the run

    Returns:
        Dict containing the run data or None if not found
    """
    db = get_firestore_client()
    doc_ref = db.collection("runs").document(run_id)
    doc = doc_ref.get()

    if doc.exists:
        return doc.to_dict()
    return None


def repo_display_name(src: str) -> str:
    """Nicely-formatted folder name for deployment artefacts."""
    if src.startswith("http"):
        # For GitHub URLs, extract the repo name from the URL path
        if "github.com" in src:
            # Handle URLs like https://github.com/owner/repo or https://github.com/owner/repo.git
            parts = src.rstrip('/').split('/')
            if len(parts) >= 2:
                repo_name = parts[-1]
                # Remove .git extension if present
                if repo_name.endswith('.git'):
                    repo_name = repo_name[:-4]
                return repo_name
        # Fallback to original logic for other HTTP URLs
        stem = pathlib.Path(src).stem  # e.g. repo.git
        return stem[:-4] if stem.endswith(".git") else stem
    return pathlib.Path(src).name
