# utils.py
from __future__ import annotations

import io
import os
import uuid
from datetime import timedelta
from typing import BinaryIO, List, Optional, Set, Tuple, Dict, Any
from google.cloud.firestore_v1._helpers import DatetimeWithNanoseconds

import firebase_admin
from firebase_admin import credentials, firestore, storage
from google.cloud.storage import Blob
from google.cloud.storage.bucket import Bucket

# ----------------------------- Constants -----------------------------

ALLOWED_IMAGE_MIME: Set[str] = {
    "image/jpeg", "image/png", "image/webp",
    "image/gif", "image/heic", "image/heif",
}

DEFAULT_MAX_IMAGES = 10
DEFAULT_MAX_BYTES = 15 * 1024 * 1024  # 15 MB
DEFAULT_PREFIX = "report-issues/"
DEFAULT_SIGNED_URL_TTL = timedelta(days=7)

# Log storage configuration
LOGS_PREFIX = "run-logs/"

# Mapping MIME -> file extension (best-effort)
MIME_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/heif": ".heif",
}

# ------------------------- Firebase bootstrap ------------------------

_APP: Optional[firebase_admin.App] = None
_DB: Optional[firestore.Client] = None
_BUCKET: Optional[Bucket] = None


def init_firebase() -> Tuple[firestore.Client, Bucket]:
    """
    Initialize Firebase Admin (Firestore + Storage) once per process.

    Requires environment variables:
      - GOOGLE_APPLICATION_CREDENTIALS: absolute path to service account JSON
      - FIREBASE_STORAGE_BUCKET: bucket name, e.g. <project-id>.appspot.com
    """
    global _APP, _DB, _BUCKET
    if _APP is not None:
        # Already initialized
        assert _DB is not None and _BUCKET is not None
        return _DB, _BUCKET

    cred_path = os.environ.get("FIREBASE_SERVICE_ACCOUNT_PATH")
    bucket_name = os.environ.get("FIREBASE_STORAGE_BUCKET")
    if not cred_path:
        raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_PATH is not set")
    if not bucket_name:
        raise RuntimeError("FIREBASE_STORAGE_BUCKET is not set")

    cred = credentials.Certificate(cred_path)
    _APP = firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
    _DB = firestore.client()
    _BUCKET = storage.bucket()  # returns google.cloud.storage.bucket.Bucket
    return _DB, _BUCKET


def get_firestore_client():
    """Get Firestore client instance"""
    db, _ = init_firebase()
    return db


def get_storage_bucket():
    """Get Storage bucket instance"""
    _, bucket = init_firebase()
    return bucket

# ------------------------------ Utilities ----------------------------


def bytes_to_stream(b: bytes) -> BinaryIO:
    return io.BytesIO(b)


def validate_images(
    files: List[Tuple[str, str, bytes]],
    allowed_mime: Optional[Set[str]] = None,
    max_images: int = DEFAULT_MAX_IMAGES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> None:
    """
    Validate images before upload.
    :param files: list of tuples (filename, content_type, data_bytes)
    """
    if allowed_mime is None:
        allowed_mime = ALLOWED_IMAGE_MIME

    if len(files) > max_images:
        raise ValueError(f"Too many images. Max allowed is {max_images}.")

    for i, (name, ctype, data) in enumerate(files):
        display = name or str(i)
        if ctype not in allowed_mime:
            raise ValueError(
                f"Unsupported image type for file {display}: {ctype}")
        if len(data) > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise ValueError(f"File too large for {display}. Max is {mb} MB.")


def _object_name(prefix: str, content_type: str) -> str:
    """
    Build a unique object path; append extension if known from MIME.
    """
    ext = MIME_EXT.get(content_type, "")
    return f"{prefix}{uuid.uuid4().hex}{ext}"


def upload_image_stream(
    file_stream: BinaryIO,
    content_type: str,
    prefix: str = DEFAULT_PREFIX,
    make_public: bool = False,
    signed_url_ttl: timedelta = DEFAULT_SIGNED_URL_TTL,
) -> str:
    """
    Upload a single image to Firebase Storage and return a URL.
      - If make_public=True, returns blob.public_url (object is made public).
      - Else returns a V4 signed URL with the given TTL.
    """
    if _BUCKET is None:
        raise RuntimeError(
            "Firebase not initialized. Call init_firebase() first.")

    bucket = get_storage_bucket()

    object_name = _object_name(prefix, content_type)
    blob: Blob = bucket.blob(object_name)

    blob.upload_from_file(file_stream, content_type=content_type)
    blob.cache_control = "public, max-age=31536000, immutable"
    blob.patch()

    if make_public:
        blob.make_public()
        return blob.public_url

    return blob.generate_signed_url(
        version="v4",
        expiration=signed_url_ttl,
        method="GET",
        content_type=content_type,
    )


# ---------------------------- Domain service -------------------------

class ReportIssueService:
    """
    Encapsulates the 'create report issue' workflow:
      - validate images
      - upload images
      - write Firestore document
      - return created record (id, text, image URLs)
    """

    def __init__(
        self,
        collection_name: str = "report_issues",
        prefix: str = DEFAULT_PREFIX,
        make_public_images: bool = False,
        signed_url_ttl: timedelta = DEFAULT_SIGNED_URL_TTL,
        max_images: int = DEFAULT_MAX_IMAGES,
        max_bytes: int = DEFAULT_MAX_BYTES,
        allowed_mime: Optional[Set[str]] = None,
    ):
        self.collection = collection_name
        self.prefix = prefix
        self.make_public = make_public_images
        self.signed_url_ttl = signed_url_ttl
        self.max_images = max_images
        self.max_bytes = max_bytes
        self.allowed_mime = allowed_mime or ALLOWED_IMAGE_MIME

    def create_report(
        self,
        text: str,
        images: List[Tuple[str, str, bytes]],
    ) -> dict:
        """
        Creates a report and returns { id, text, images }.
        :param images: list of tuples (filename, content_type, data_bytes)
        """
        # Ensure Firebase is ready
        db, _ = init_firebase()

        # Validate inputs
        validate_images(
            files=images,
            allowed_mime=self.allowed_mime,
            max_images=self.max_images,
            max_bytes=self.max_bytes,
        )

        # Upload images
        urls: List[str] = []
        for _, ctype, data in images:
            url = upload_image_stream(
                bytes_to_stream(data),
                content_type=ctype,
                prefix=self.prefix,
                make_public=self.make_public,
                signed_url_ttl=self.signed_url_ttl,
            )
            urls.append(url)

        # Firestore document
        doc = {
            "text": text,
            "images": urls,
            "status": "open",
            "created_at": firestore.SERVER_TIMESTAMP,
        }

        ref = db.collection(self.collection).document()
        ref.set(doc)
        return {"id": ref.id, "text": text, "images": urls}

# ---------------------- Log Storage Functions ------------------------


def upload_log_file(
    user_id: str,
    run_id: str,
    log_file_path: str,
    make_public: bool = True
) -> Optional[str]:  # ← Changed return type
    """
    Upload a log file to Firebase Storage.
    Returns None if upload fails instead of raising exception.
    """
    try:
        # Validate file exists and has content
        if not log_file_path:
            print(f"⚠️ No log file path provided for run {run_id}")
            return None

        if not os.path.exists(log_file_path):
            print(f"⚠️ Log file does not exist: {log_file_path}")
            return None

        file_size = os.path.getsize(log_file_path)
        if file_size == 0:
            print(f"⚠️ Log file is empty: {log_file_path}")
            return None

        print(f"📤 Uploading log file: {log_file_path} ({file_size} bytes)")

        bucket = get_storage_bucket()
        storage_path = f"{LOGS_PREFIX}{user_id}/{run_id}.log"
        blob = bucket.blob(storage_path)

        blob.upload_from_filename(log_file_path, content_type="text/plain")

        if make_public:
            blob.cache_control = "public, max-age=31536000, immutable"
            blob.patch()
            blob.make_public()
            url = blob.public_url
        else:
            blob.cache_control = "private, max-age=3600"
            blob.patch()
            from datetime import timedelta
            url = blob.generate_signed_url(
                version="v4",
                expiration=timedelta(days=7),
                method="GET",
                content_type="text/plain",
            )

        print(f"✅ Log uploaded successfully")
        return url

    except Exception as e:
        print(f"❌ Failed to upload log file: {e}")
        import traceback
        traceback.print_exc()
        return None  # ← Returns None instead of raising


def upload_log_content(
    user_id: str,
    run_id: str,
    log_content: str,
    make_public: bool = False
) -> str:
    """
    Upload log content directly to Firebase Storage (without local file).

    Args:
        user_id: User ID
        run_id: Run ID
        log_content: String content of the logs
        make_public: Whether to make the file publicly accessible

    Returns:
        URL to access the log file (signed URL or public URL)
    """
    bucket = get_storage_bucket()

    # Create storage path: run-logs/{user_id}/{run_id}.log
    storage_path = f"{LOGS_PREFIX}{user_id}/{run_id}.log"
    blob: Blob = bucket.blob(storage_path)

    # Upload the content
    blob.upload_from_string(log_content, content_type="text/plain")
    blob.cache_control = "private, max-age=3600"
    blob.patch()

    if make_public:
        blob.make_public()
        return blob.public_url

    # Return signed URL valid for 30 days
    return blob.generate_signed_url(
        version="v4",
        method="GET",
        content_type="text/plain",
    )


# -------------------- Session Management Functions -------------------

def save_run_session(
    user_id: str,
    user_email: str,
    run_id: str,
    log_url: Optional[str] = None,
    github_url: Optional[str] = None,
    tunnel_url: Optional[str] = None,
    status: str = "completed",
    additional_metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Save a run session to Firestore under the user's sessions collection.
    Also creates/updates the run-sessions collection entry.

    Collections structure:
    - run-sessions/{user_id}_{run_id}: Individual run session document
    - users/{user_id}/sessions/{run_id}: User's session subcollection

    Args:
        user_id: User ID
        user_email: User email address
        run_id: Run ID
        log_url: URL to the log file in Firebase Storage
        github_url: Optional GitHub repository URL
        tunnel_url: Optional tunnel URL
        status: Status of the run session
        additional_metadata: Any additional metadata to store
    """
    try:
        db = get_firestore_client()

        # Prepare session data
        session_data = {
            "run_id": run_id,
            "status": status,
            "timestamp": firestore.SERVER_TIMESTAMP,
            "created_at": firestore.SERVER_TIMESTAMP
        }

        # ✅ Only add log_url if it exists
        if log_url:
            session_data["log_url"] = log_url
            session_data["has_log"] = True
        else:
            session_data["has_log"] = False
            print(f"⚠️ Saving session without log URL for run {run_id}")

        # Add optional fields
        if github_url:
            session_data["github_url"] = github_url
        if tunnel_url:
            session_data["tunnel_url"] = tunnel_url
        if additional_metadata:
            session_data["metadata"] = additional_metadata

        # Save to run-sessions collection with composite ID
        composite_id = f"{user_id}_{run_id}"
        run_sessions_ref = db.collection("run-sessions").document(composite_id)
        run_sessions_ref.set(session_data)

        # Save to user's sessions subcollection
        user_session_ref = db.collection("user-sessions").document(
            user_id).collection("sessions").document(run_id)
        user_session_ref.set(session_data)

        print(f"✅ Saved run session: {composite_id}")

    except Exception as e:
        print(f"❌ Failed to save session: {e}")
        import traceback
        traceback.print_exc()


def get_user_sessions(user_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """
    Retrieve all sessions for a specific user.

    Args:
        user_id: User ID
        limit: Maximum number of sessions to return

    Returns:
        List of session dictionaries
    """

    db = get_firestore_client()

    sessions_ref = db.collection("user-sessions").document(
        user_id).collection("sessions")
    sessions = sessions_ref.order_by(
        "timestamp", direction=firestore.Query.DESCENDING).limit(limit).stream()

    result = []
    for session in sessions:
        session_dict = session.to_dict()

        # Convert timestamp fields to ISO strings
        for key in ['timestamp', 'created_at', 'updated_at', 'completed_at', 'failed_at', 'cancelled_at']:
            if key in session_dict and isinstance(session_dict[key], DatetimeWithNanoseconds):
                session_dict[key] = session_dict[key].isoformat()

        # Handle metadata timestamps if they exist
        if 'metadata' in session_dict and isinstance(session_dict['metadata'], dict):
            for key, value in session_dict['metadata'].items():
                if isinstance(value, DatetimeWithNanoseconds):
                    session_dict['metadata'][key] = value.isoformat()

        result.append(session_dict)

    return result


def get_run_session(user_id: str, run_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a specific run session.

    Args:
        user_id: User ID
        run_id: Run ID

    Returns:
        Session dictionary or None if not found
    """
    from google.cloud.firestore_v1._helpers import DatetimeWithNanoseconds

    db = get_firestore_client()

    composite_id = f"{user_id}_{run_id}"
    doc_ref = db.collection("run-sessions").document(composite_id)
    doc = doc_ref.get()

    if doc.exists:
        session_dict = doc.to_dict()

        # Convert timestamps to ISO strings
        for key in ['timestamp', 'created_at', 'updated_at', 'completed_at', 'failed_at', 'cancelled_at']:
            if key in session_dict and isinstance(session_dict[key], DatetimeWithNanoseconds):
                session_dict[key] = session_dict[key].isoformat()

        # Handle metadata timestamps
        if 'metadata' in session_dict and isinstance(session_dict['metadata'], dict):
            for key, value in session_dict['metadata'].items():
                if isinstance(value, DatetimeWithNanoseconds):
                    session_dict['metadata'][key] = value.isoformat()

        return session_dict

    return None


def update_session_status(
    user_id: str,
    run_id: str,
    status: str,
    additional_data: Optional[Dict[str, Any]] = None
) -> None:
    """
    Update the status of a run session.

    Args:
        user_id: User ID
        run_id: Run ID
        status: New status
        additional_data: Additional data to update
    """
    db = get_firestore_client()

    update_data = {
        "status": status,
        "updated_at": firestore.SERVER_TIMESTAMP
    }

    if additional_data:
        update_data.update(additional_data)

    # Update in both collections
    composite_id = f"{user_id}_{run_id}"

    # Update run-sessions
    run_sessions_ref = db.collection("run-sessions").document(composite_id)
    run_sessions_ref.update(update_data)

    # Update user sessions subcollection
    user_session_ref = db.collection("user-sessions").document(
        user_id).collection("sessions").document(run_id)
    user_session_ref.update(update_data)


def save_error_log_to_storage(
    user_id: str,
    run_id: str,
    error_message: str,
    traceback_str: Optional[str] = None
) -> Optional[str]:
    """
    Save error information as a log file when no actual log file exists.
    Useful for runs that fail before log file creation.
    """
    try:
        from datetime import datetime, timezone

        # Create error log content
        timestamp = datetime.now(timezone.utc).isoformat()
        log_content = f"""
ERROR LOG FOR RUN: {run_id}
Generated: {timestamp}
User: {user_id}

{'='*80}
ERROR OCCURRED DURING RUN
{'='*80}

Error Message:
{error_message}

"""
        if traceback_str:
            log_content += f"""
Full Traceback:
{traceback_str}
"""

        log_content += f"""
{'='*80}
Note: This run failed before a complete log file could be generated.
{'='*80}
"""

        # Upload as string content
        bucket = get_storage_bucket()
        storage_path = f"{LOGS_PREFIX}{user_id}/{run_id}_error.log"
        blob = bucket.blob(storage_path)

        blob.upload_from_string(log_content, content_type="text/plain")
        blob.cache_control = "public, max-age=31536000, immutable"
        blob.patch()
        blob.make_public()

        print(f"✅ Error log saved to {storage_path}")
        return blob.public_url

    except Exception as e:
        print(f"❌ Failed to save error log: {e}")
        return None
