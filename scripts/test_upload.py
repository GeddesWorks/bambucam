#!/usr/bin/env python3
"""Test Appwrite upload connectivity."""

import os
import sys
import tempfile
from pathlib import Path

from bambucam.upload.appwrite import AppwriteUploader


def main() -> None:
    required = ["APPWRITE_ENDPOINT", "APPWRITE_PROJECT_ID",
                 "APPWRITE_API_KEY", "APPWRITE_BUCKET_ID"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print(f"ERROR: Set environment variables: {', '.join(missing)}")
        sys.exit(1)

    uploader = AppwriteUploader(
        endpoint=os.environ["APPWRITE_ENDPOINT"],
        project_id=os.environ["APPWRITE_PROJECT_ID"],
        api_key=os.environ["APPWRITE_API_KEY"],
        bucket_id=os.environ["APPWRITE_BUCKET_ID"],
    )

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as f:
        f.write(b"BambuCam upload test")
        test_file = Path(f.name)

    print(f"Uploading test file...")
    result = uploader.upload(test_file, metadata={"test": True})

    if result.success:
        print(f"Upload OK. File ID: {result.file_id}")
        verified = uploader.verify(result.file_id)
        print(f"Verification: {'OK' if verified else 'FAILED'}")
    else:
        print("Upload FAILED.")
        sys.exit(1)

    test_file.unlink()


if __name__ == "__main__":
    main()
