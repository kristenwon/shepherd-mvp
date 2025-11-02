from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime


class DownloadUrlResponse(BaseModel):
    """Response model for download URL"""
    download_url: str
    filename: str
    file_path: str
    expires_in_minutes: int


class FileMetadataResponse(BaseModel):
    """Response model for file metadata"""
    name: str
    size: Optional[int] = None
    content_type: Optional[str] = None
    created: Optional[str] = None
    updated: Optional[str] = None
    md5_hash: Optional[str] = None


class FileListResponse(BaseModel):
    """Response model for file listing"""
    files: list[dict]
    count: int
    prefix: str
