from __future__ import annotations

import os
import uuid
from abc import ABC, abstractmethod
from typing import Optional

from app.config import settings


class StorageService(ABC):
    @abstractmethod
    def upload(self, data: bytes, original_filename: str, mime_type: str) -> str:
        """Return a stable storage_key."""

    @abstractmethod
    def get_bytes(self, storage_key: str) -> bytes:
        ...

    @abstractmethod
    def delete(self, storage_key: str) -> None:
        ...

    @abstractmethod
    def exists(self, storage_key: str) -> bool:
        ...

    @abstractmethod
    def signed_url(self, storage_key: str, expires_sec: int = 900) -> str:
        """Return a URL the frontend can use to fetch the file (via backend)."""


class LocalStorageAdapter(StorageService):
    def __init__(self, base_path: str):
        self.base_path = base_path
        os.makedirs(self.base_path, exist_ok=True)

    def _path(self, storage_key: str) -> str:
        # Prevent path traversal: only allow generated keys (uuid-based).
        safe = os.path.basename(storage_key)
        return os.path.join(self.base_path, safe)

    def upload(self, data: bytes, original_filename: str, mime_type: str) -> str:
        key = uuid.uuid4().hex + "_" + os.path.basename(original_filename)[:64]
        with open(self._path(key), "wb") as f:
            f.write(data)
        return key

    def get_bytes(self, storage_key: str) -> bytes:
        with open(self._path(storage_key), "rb") as f:
            return f.read()

    def delete(self, storage_key: str) -> None:
        p = self._path(storage_key)
        if os.path.exists(p):
            os.remove(p)

    def exists(self, storage_key: str) -> bool:
        return os.path.exists(self._path(storage_key))

    def signed_url(self, storage_key: str, expires_sec: int = 900) -> str:
        # Local backend serves via an authenticated endpoint; key + short ttl token.
        from itsdangerous import URLSafeTimedSerializer

        s = URLSafeTimedSerializer(settings.SESSION_SECRET, salt="orderflow-file")
        token = s.dumps({"k": os.path.basename(storage_key)}, max_age=expires_sec)
        return f"/api/attachments/file/{os.path.basename(storage_key)}?token={token}"


class S3StorageAdapter(StorageService):
    def __init__(self):
        import boto3

        self.bucket = settings.S3_BUCKET_NAME
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION or None,
        )

    def upload(self, data: bytes, original_filename: str, mime_type: str) -> str:
        key = uuid.uuid4().hex + "_" + os.path.basename(original_filename)[:64]
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=data, ContentType=mime_type
        )
        return key

    def get_bytes(self, storage_key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=os.path.basename(storage_key))
        return obj["Body"].read()

    def delete(self, storage_key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=os.path.basename(storage_key))

    def exists(self, storage_key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=os.path.basename(storage_key))
            return True
        except Exception:
            return False

    def signed_url(self, storage_key: str, expires_sec: int = 900) -> str:
        from botocore.exceptions import ClientError

        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": os.path.basename(storage_key)},
                ExpiresIn=expires_sec,
            )
        except ClientError:
            return ""


_service: Optional[StorageService] = None


def get_storage() -> StorageService:
    global _service
    if _service is None:
        if settings.STORAGE_BACKEND == "s3":
            _service = S3StorageAdapter()
        else:
            _service = LocalStorageAdapter(settings.LOCAL_STORAGE_PATH)
    return _service
