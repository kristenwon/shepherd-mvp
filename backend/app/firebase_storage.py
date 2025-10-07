# utils.py
from __future__ import annotations

import io
import os
import uuid
from datetime import timedelta
from typing import BinaryIO, List, Optional, Set, Tuple

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

    object_name = _object_name(prefix, content_type)
    blob: Blob = _BUCKET.blob(object_name)

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
