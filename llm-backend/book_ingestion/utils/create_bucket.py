"""Simple script to create the S3 bucket non-interactively."""
import boto3
from botocore.exceptions import ClientError
from config import get_settings

settings = get_settings()
bucket_name = settings.aws_s3_bucket
region = settings.aws_region

print(f"Creating S3 bucket: {bucket_name} in {region}")

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

    print(f"✅ Bucket '{bucket_name}' created successfully!")

    # Test access
    test_key = "_test_access.txt"
    s3_client.put_object(Bucket=bucket_name, Key=test_key, Body=b"Test")
    s3_client.delete_object(Bucket=bucket_name, Key=test_key)
    print(f"✅ Access verified!")

except ClientError as e:
    if e.response['Error']['Code'] == 'BucketAlreadyOwnedByYou':
        print(f"✅ Bucket '{bucket_name}' already exists and you own it!")
    elif e.response['Error']['Code'] == 'BucketAlreadyExists':
        print(f"❌ Bucket '{bucket_name}' already exists and is owned by someone else!")
    else:
        print(f"❌ Error: {e}")
