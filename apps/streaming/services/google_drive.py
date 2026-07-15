"""
Google Drive download utilities for video import.

Supports downloading publicly shared files ("Anyone with the link")
using the direct download URL approach. For private files or very large
files (>2 GB), consider switching to the Google Drive API v3 with a
service account.
"""
import re
import os
import logging
from typing import Optional, Callable

import requests

logger = logging.getLogger(__name__)


def extract_google_drive_file_id(url: str) -> Optional[str]:
    """
    Extract the Google Drive file ID from various URL formats.

    Supported patterns:
        - https://drive.google.com/file/d/<FILE_ID>/...
        - https://drive.google.com/open?id=<FILE_ID>
        - https://docs.google.com/.../d/<FILE_ID>/...

    Args:
        url: A Google Drive share link.

    Returns:
        The file ID string, or None if the URL is not recognised.
    """
    patterns = [
        r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/.*/d/([a-zA-Z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def download_from_google_drive(
    file_id: str,
    destination: str,
    progress_callback: Optional[Callable[[int], None]] = None,
) -> str:
    """
    Download a file from Google Drive using its file ID.

    The file must be shared as "Anyone with the link can view".
    Handles the large-file virus-scan confirmation page automatically.

    Progress is reported as 0-80 (reserving 80-100 for post-download
    processing in the calling task).

    Args:
        file_id: Google Drive file ID.
        destination: Local filesystem path to write the downloaded file.
        progress_callback: Optional callable receiving an int (0-80).

    Returns:
        The *destination* path on success.

    Raises:
        requests.HTTPError: If the download request fails.
        IOError: If writing to *destination* fails.
    """
    session = requests.Session()

    # Initial request
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    response = session.get(url, stream=True, timeout=30)
    response.raise_for_status()

    # Handle large-file confirmation page (virus-scan warning cookie)
    for key, value in response.cookies.items():
        if key.startswith("download_warning"):
            url = (
                f"https://drive.google.com/uc?export=download"
                f"&confirm={value}&id={file_id}"
            )
            response = session.get(url, stream=True, timeout=30)
            response.raise_for_status()
            break

    total_size = int(response.headers.get("content-length", 0))
    downloaded = 0
    chunk_size = 8 * 1024 * 1024  # 8 MB

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(destination), exist_ok=True)

    with open(destination, "wb") as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            if chunk:
                f.write(chunk)
                downloaded += len(chunk)
                if progress_callback and total_size > 0:
                    # Map download progress to 0-80 range
                    progress = min(80, int((downloaded / total_size) * 80))
                    progress_callback(progress)

    if total_size and downloaded < total_size:
        logger.warning(
            f"Incomplete download: got {downloaded}/{total_size} bytes for file {file_id}"
        )

    logger.info(
        f"Downloaded Google Drive file {file_id} to {destination} "
        f"({downloaded} bytes)"
    )
    return destination
