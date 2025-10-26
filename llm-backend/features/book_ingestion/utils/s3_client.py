"""
AWS S3 client for book ingestion feature.

Provides a clean interface for S3 operations with proper error handling.
"""
import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from config import get_settings

logger = logging.getLogger(__name__)


class S3Client:
    """
    AWS S3 client for book storage operations.

    Handles file uploads, downloads, and metadata management for book ingestion.
    Credentials are automatically detected from ~/.aws/credentials or environment.
    """

    def __init__(self):
        """
        Initialize S3 client with settings from config.

        AWS credentials are auto-detected from:
        1. Environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY)
        2. ~/.aws/credentials file
        3. IAM role (when running on AWS)
        """
        settings = get_settings()
        self.bucket_name = settings.aws_s3_bucket
        self.region = settings.aws_region

        try:
            self.s3_client = boto3.client('s3', region_name=self.region)
            logger.info(f"S3 client initialized for bucket: {self.bucket_name}, region: {self.region}")
        except NoCredentialsError:
            logger.error("AWS credentials not found! Check ~/.aws/credentials or environment variables")
            raise

    def upload_file(self, local_path: str, s3_key: str) -> str:
        """
        Upload a file to S3.

        Args:
            local_path: Path to local file
            s3_key: S3 object key (e.g., "books/book_id/1.png")

        Returns:
            S3 URL of uploaded file

        Raises:
            ClientError: If upload fails
        """
        try:
            self.s3_client.upload_file(local_path, self.bucket_name, s3_key)
            logger.info(f"Uploaded {local_path} to s3://{self.bucket_name}/{s3_key}")
            return f"s3://{self.bucket_name}/{s3_key}"
        except ClientError as e:
            logger.error(f"Failed to upload {local_path} to S3: {e}")
            raise

    def upload_bytes(self, data: bytes, s3_key: str, content_type: Optional[str] = None) -> str:
        """
        Upload bytes data to S3.

        Args:
            data: Bytes to upload
            s3_key: S3 object key
            content_type: MIME type (e.g., "image/png", "text/plain")

        Returns:
            S3 URL of uploaded object

        Raises:
            ClientError: If upload fails
        """
        try:
            extra_args = {'ContentType': content_type} if content_type else {}
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=s3_key,
                Body=data,
                **extra_args
            )
            logger.info(f"Uploaded bytes to s3://{self.bucket_name}/{s3_key}")
            return f"s3://{self.bucket_name}/{s3_key}"
        except ClientError as e:
            logger.error(f"Failed to upload bytes to S3: {e}")
            raise

    def download_file(self, s3_key: str, local_path: str) -> str:
        """
        Download a file from S3.

        Args:
            s3_key: S3 object key
            local_path: Path to save downloaded file

        Returns:
            Path to downloaded file

        Raises:
            ClientError: If download fails
        """
        try:
            self.s3_client.download_file(self.bucket_name, s3_key, local_path)
            logger.info(f"Downloaded s3://{self.bucket_name}/{s3_key} to {local_path}")
            return local_path
        except ClientError as e:
            logger.error(f"Failed to download {s3_key} from S3: {e}")
            raise

    def download_bytes(self, s3_key: str) -> bytes:
        """
        Download file contents as bytes.

        Args:
            s3_key: S3 object key

        Returns:
            File contents as bytes

        Raises:
            ClientError: If download fails
        """
        try:
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            data = response['Body'].read()
            logger.info(f"Downloaded bytes from s3://{self.bucket_name}/{s3_key}")
            return data
        except ClientError as e:
            logger.error(f"Failed to download bytes from S3: {e}")
            raise

    def get_presigned_url(self, s3_key: str, expiration: int = 3600) -> str:
        """
        Generate a presigned URL for temporary access to an S3 object.

        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned URL

        Raises:
            ClientError: If URL generation fails
        """
        try:
            url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': s3_key},
                ExpiresIn=expiration
            )
            logger.debug(f"Generated presigned URL for {s3_key}")
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise

    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3.

        Args:
            s3_key: S3 object key

        Returns:
            True if deleted, False otherwise

        Raises:
            ClientError: If deletion fails
        """
        try:
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            logger.info(f"Deleted s3://{self.bucket_name}/{s3_key}")
            return True
        except ClientError as e:
            logger.error(f"Failed to delete {s3_key} from S3: {e}")
            raise

    def delete_folder(self, prefix: str) -> int:
        """
        Delete all objects with a given prefix (folder).

        Args:
            prefix: S3 key prefix (e.g., "books/book_id/")

        Returns:
            Number of objects deleted

        Raises:
            ClientError: If deletion fails
        """
        try:
            # List all objects with prefix
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )

            if 'Contents' not in response:
                logger.info(f"No objects found with prefix: {prefix}")
                return 0

            # Delete all objects
            objects = [{'Key': obj['Key']} for obj in response['Contents']]
            self.s3_client.delete_objects(
                Bucket=self.bucket_name,
                Delete={'Objects': objects}
            )

            count = len(objects)
            logger.info(f"Deleted {count} objects with prefix: {prefix}")
            return count

        except ClientError as e:
            logger.error(f"Failed to delete folder {prefix} from S3: {e}")
            raise

    def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3.

        Args:
            s3_key: S3 object key

        Returns:
            True if file exists, False otherwise
        """
        try:
            self.s3_client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            else:
                logger.error(f"Error checking if {s3_key} exists: {e}")
                raise

    def upload_json(self, data: Dict[str, Any], s3_key: str) -> str:
        """
        Upload a Python dict as JSON to S3.

        Args:
            data: Dictionary to upload
            s3_key: S3 object key

        Returns:
            S3 URL of uploaded JSON

        Raises:
            ClientError: If upload fails
        """
        json_str = json.dumps(data, indent=2)
        json_bytes = json_str.encode('utf-8')
        return self.upload_bytes(json_bytes, s3_key, content_type='application/json')

    def download_json(self, s3_key: str) -> Dict[str, Any]:
        """
        Download and parse JSON from S3.

        Args:
            s3_key: S3 object key

        Returns:
            Parsed JSON as dictionary

        Raises:
            ClientError: If download fails
            json.JSONDecodeError: If JSON parsing fails
        """
        json_bytes = self.download_bytes(s3_key)
        json_str = json_bytes.decode('utf-8')
        return json.loads(json_str)

    def update_metadata_json(self, book_id: str, metadata: Dict[str, Any]) -> str:
        """
        Update the metadata.json file for a book.

        Args:
            book_id: Book identifier
            metadata: Metadata dictionary

        Returns:
            S3 URL of updated metadata.json

        Raises:
            ClientError: If upload fails
        """
        s3_key = f"books/{book_id}/metadata.json"
        return self.upload_json(metadata, s3_key)


# Global S3 client instance
_s3_client: Optional[S3Client] = None


def get_s3_client() -> S3Client:
    """
    Get or create the global S3 client instance.

    Returns:
        S3Client: S3 client instance
    """
    global _s3_client
    if _s3_client is None:
        _s3_client = S3Client()
    return _s3_client


def reset_s3_client():
    """Reset the global S3 client (useful for testing)."""
    global _s3_client
    _s3_client = None
