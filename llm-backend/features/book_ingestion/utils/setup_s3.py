"""
Script to setup and verify S3 bucket for book ingestion.

Can be run to:
1. Check if bucket exists
2. Create bucket if needed
3. Verify connectivity
"""
import boto3
from botocore.exceptions import ClientError
from config import get_settings
import sys


def check_bucket_exists(bucket_name: str, region: str) -> bool:
    """Check if S3 bucket exists."""
    s3_client = boto3.client('s3', region_name=region)

    try:
        s3_client.head_bucket(Bucket=bucket_name)
        print(f"✅ Bucket '{bucket_name}' exists!")
        return True
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == '404':
            print(f"❌ Bucket '{bucket_name}' does not exist")
            return False
        elif error_code == '403':
            print(f"⚠️  Bucket '{bucket_name}' exists but you don't have access")
            return False
        else:
            print(f"❌ Error checking bucket: {e}")
            return False


def create_bucket(bucket_name: str, region: str) -> bool:
    """Create S3 bucket."""
    s3_client = boto3.client('s3', region_name=region)

    try:
        # For us-east-1, don't specify LocationConstraint
        if region == 'us-east-1':
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={'LocationConstraint': region}
            )

        print(f"✅ Bucket '{bucket_name}' created successfully in {region}!")
        return True
    except ClientError as e:
        print(f"❌ Failed to create bucket: {e}")
        return False


def verify_access(bucket_name: str, region: str) -> bool:
    """Verify read/write access to bucket."""
    s3_client = boto3.client('s3', region_name=region)

    test_key = "_test_access.txt"
    test_content = b"Test access file"

    try:
        # Test write
        s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=test_content)
        print(f"✅ Write access verified")

        # Test read
        response = s3_client.get_object(Bucket=bucket_name, Key=test_key)
        content = response['Body'].read()
        assert content == test_content
        print(f"✅ Read access verified")

        # Test delete
        s3_client.delete_object(Bucket=bucket_name, Key=test_key)
        print(f"✅ Delete access verified")

        return True
    except ClientError as e:
        print(f"❌ Access verification failed: {e}")
        return False


def main():
    print("🔄 S3 Bucket Setup & Verification\n")

    settings = get_settings()
    bucket_name = settings.aws_s3_bucket
    region = settings.aws_region

    print(f"Bucket: {bucket_name}")
    print(f"Region: {region}\n")

    # Check AWS credentials
    try:
        boto3.client('s3', region_name=region)
        print("✅ AWS credentials detected\n")
    except Exception as e:
        print(f"❌ AWS credentials not found!")
        print(f"   Please configure ~/.aws/credentials or set environment variables")
        print(f"   Error: {e}\n")
        sys.exit(1)

    # Check if bucket exists
    exists = check_bucket_exists(bucket_name, region)

    if not exists:
        print(f"\n📦 Bucket does not exist. Would you like to create it?")
        response = input("   Create bucket? (yes/no): ")

        if response.lower() == "yes":
            success = create_bucket(bucket_name, region)
            if not success:
                sys.exit(1)
        else:
            print("   Bucket creation skipped")
            sys.exit(0)

    # Verify access
    print(f"\n🔐 Verifying bucket access...")
    success = verify_access(bucket_name, region)

    if success:
        print(f"\n✅ S3 setup complete! Bucket is ready for book ingestion.")
    else:
        print(f"\n❌ S3 setup failed. Please check permissions.")
        sys.exit(1)


if __name__ == "__main__":
    main()
