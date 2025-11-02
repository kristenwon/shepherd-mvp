# firebase_storage_download.py
"""
Firebase Storage Download Service
Integrates with existing Firebase setup from utils.py
"""

from __future__ import annotations

import io
import os
import logging
from datetime import timedelta
from typing import BinaryIO, Optional, Tuple, List
from pathlib import Path

from google.cloud.storage import Blob
from google.cloud.storage.bucket import Bucket

# Import the existing Firebase initialization from utils
from ..firebase_storage import init_firebase

logger = logging.getLogger(__name__)


class FirebaseDownloadService:
    """Service for downloading files from Firebase Storage"""

    def __init__(
        self,
        prefix: str = "user-assets-zip/",
        signed_url_ttl: timedelta = timedelta(hours=1),
    ):
        """
        Initialize Firebase Download Service

        Args:
            prefix: Default prefix for file paths
            signed_url_ttl: Time-to-live for signed URLs
        """
        self.prefix = prefix
        self.signed_url_ttl = signed_url_ttl
        self._bucket: Optional[Bucket] = None

    @property
    def bucket(self) -> Bucket:
        """Get or initialize the storage bucket"""
        if self._bucket is None:
            _, self._bucket = init_firebase()
        return self._bucket

    def download_file_to_stream(
        self,
        file_path: str,
        chunk_size: int = 256 * 1024  # 256KB chunks
    ) -> Tuple[BinaryIO, str, int]:
        """
        Download a file from Firebase Storage to a stream

        Args:
            file_path: Path to the file in Firebase Storage
            chunk_size: Size of chunks for streaming

        Returns:
            Tuple of (file_stream, filename, file_size)

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: For other download errors
        """
        try:
            blob: Blob = self.bucket.blob(file_path)

            if not blob.exists():
                raise FileNotFoundError(
                    f"File not found in Firebase Storage: {file_path}")

            # Get file metadata
            blob.reload()
            file_size = blob.size or 0

            # Download to stream
            file_stream = io.BytesIO()
            blob.download_to_file(file_stream)
            file_stream.seek(0)

            # Extract filename
            filename = Path(file_path).name

            logger.info(
                f"Successfully prepared stream for {filename} ({file_size} bytes)")
            return file_stream, filename, file_size

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error downloading file from Firebase Storage: {e}")
            raise Exception(f"Failed to download file: {str(e)}")

    def download_file_to_bytes(self, file_path: str) -> Tuple[bytes, str, int]:
        """
        Download a file from Firebase Storage to bytes

        Args:
            file_path: Path to the file in Firebase Storage

        Returns:
            Tuple of (file_content, filename, file_size)

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: For other download errors
        """
        try:
            blob: Blob = self.bucket.blob(file_path)

            if not blob.exists():
                raise FileNotFoundError(
                    f"File not found in Firebase Storage: {file_path}")

            # Get file metadata
            blob.reload()
            file_size = blob.size or 0

            # Download as bytes
            file_content = blob.download_as_bytes()

            # Extract filename
            filename = Path(file_path).name

            logger.info(
                f"Successfully downloaded {filename} ({file_size} bytes)")
            return file_content, filename, file_size

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error downloading file from Firebase Storage: {e}")
            raise Exception(f"Failed to download file: {str(e)}")

    def generate_signed_url(
        self,
        file_path: str,
        ttl: Optional[timedelta] = None,
        content_type: Optional[str] = None
    ) -> str:
        """
        Generate a signed URL for downloading a file

        Args:
            file_path: Path to the file in Firebase Storage
            ttl: Time-to-live for the URL (uses default if not provided)
            content_type: Optional content type for the download

        Returns:
            Signed download URL

        Raises:
            FileNotFoundError: If file doesn't exist
            Exception: For other errors
        """
        try:
            blob: Blob = self.bucket.blob(file_path)

            if not blob.exists():
                raise FileNotFoundError(
                    f"File not found in Firebase Storage: {file_path}")

            # Use provided TTL or default
            expiration = ttl or self.signed_url_ttl

            # Generate signed URL
            url = blob.generate_signed_url(
                version="v4",
                expiration=expiration,
                method="GET",
                content_type=content_type or "application/zip"
            )

            logger.info(
                f"Generated signed URL for {file_path} (expires in {expiration})")
            return url

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error generating signed URL: {e}")
            raise Exception(f"Failed to generate signed URL: {str(e)}")

    def list_files(
        self,
        prefix: Optional[str] = None,
        delimiter: Optional[str] = None,
        max_results: int = 100
    ) -> List[dict]:
        """
        List files in Firebase Storage

        Args:
            prefix: Path prefix to filter files (uses default if not provided)
            delimiter: Delimiter for hierarchical listing
            max_results: Maximum number of results to return

        Returns:
            List of file metadata dictionaries
        """
        try:
            prefix = prefix or self.prefix
            blobs = self.bucket.list_blobs(
                prefix=prefix,
                delimiter=delimiter,
                max_results=max_results
            )

            files = []
            for blob in blobs:
                files.append({
                    "name": blob.name,
                    "size": blob.size,
                    "content_type": blob.content_type,
                    "created": blob.time_created.isoformat() if blob.time_created else None,
                    "updated": blob.updated.isoformat() if blob.updated else None,
                })

            logger.info(f"Found {len(files)} files with prefix '{prefix}'")
            return files

        except Exception as e:
            logger.error(f"Error listing files: {e}")
            raise Exception(f"Failed to list files: {str(e)}")

    def get_file_metadata(self, file_path: str) -> dict:
        """
        Get metadata for a file in Firebase Storage

        Args:
            file_path: Path to the file in Firebase Storage

        Returns:
            Dictionary with file metadata

        Raises:
            FileNotFoundError: If file doesn't exist
        """
        try:
            blob: Blob = self.bucket.blob(file_path)

            if not blob.exists():
                raise FileNotFoundError(
                    f"File not found in Firebase Storage: {file_path}")

            # Reload to get latest metadata
            blob.reload()

            metadata = {
                "name": blob.name,
                "size": blob.size,
                "content_type": blob.content_type,
                "created": blob.time_created.isoformat() if blob.time_created else None,
                "updated": blob.updated.isoformat() if blob.updated else None,
                "md5_hash": blob.md5_hash,
                "etag": blob.etag,
                "generation": blob.generation,
                "metageneration": blob.metageneration,
                "cache_control": blob.cache_control,
                "metadata": blob.metadata
            }

            return metadata

        except FileNotFoundError:
            raise
        except Exception as e:
            logger.error(f"Error getting file metadata: {e}")
            raise Exception(f"Failed to get file metadata: {str(e)}")

    def file_exists(self, file_path: str) -> bool:
        """
        Check if a file exists in Firebase Storage

        Args:
            file_path: Path to the file in Firebase Storage

        Returns:
            True if file exists, False otherwise
        """
        try:
            blob: Blob = self.bucket.blob(file_path)
            return blob.exists()
        except Exception as e:
            logger.error(f"Error checking file existence: {e}")
            return False
