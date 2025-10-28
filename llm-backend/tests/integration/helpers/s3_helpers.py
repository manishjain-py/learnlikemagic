"""S3 helper utilities for integration tests."""


def cleanup_s3_prefix(s3_client, prefix):
    """
    Delete all objects under a given prefix.

    Args:
        s3_client: S3Client instance
        prefix: S3 key prefix to delete
    """
    try:
        # List all objects with prefix
        paginator = s3_client.client.get_paginator('list_objects_v2')

        for page in paginator.paginate(Bucket=s3_client.bucket_name, Prefix=prefix):
            if 'Contents' in page:
                objects = [{'Key': obj['Key']} for obj in page['Contents']]
                if objects:
                    s3_client.client.delete_objects(
                        Bucket=s3_client.bucket_name,
                        Delete={'Objects': objects}
                    )
    except Exception as e:
        print(f"Warning: Failed to cleanup S3 prefix {prefix}: {e}")


def verify_s3_object_exists(s3_client, key):
    """
    Verify an S3 object exists.

    Args:
        s3_client: S3Client instance
        key: S3 object key

    Returns:
        True if object exists, False otherwise
    """
    try:
        s3_client.client.head_object(Bucket=s3_client.bucket_name, Key=key)
        return True
    except:
        return False


def verify_s3_object_not_exists(s3_client, key):
    """
    Verify an S3 object does not exist.

    Args:
        s3_client: S3Client instance
        key: S3 object key

    Returns:
        True if object does not exist, False otherwise
    """
    return not verify_s3_object_exists(s3_client, key)


def get_s3_object_content(s3_client, key):
    """
    Get content of an S3 object.

    Args:
        s3_client: S3Client instance
        key: S3 object key

    Returns:
        Object content as bytes
    """
    response = s3_client.client.get_object(Bucket=s3_client.bucket_name, Key=key)
    return response['Body'].read()


def list_s3_objects_with_prefix(s3_client, prefix):
    """
    List all objects with a given prefix.

    Args:
        s3_client: S3Client instance
        prefix: S3 key prefix

    Returns:
        List of object keys
    """
    keys = []
    paginator = s3_client.client.get_paginator('list_objects_v2')

    for page in paginator.paginate(Bucket=s3_client.bucket_name, Prefix=prefix):
        if 'Contents' in page:
            keys.extend([obj['Key'] for obj in page['Contents']])

    return keys


def cleanup_book_s3_data(s3_client, book_id):
    """
    Clean up all S3 data for a book.

    This includes pages, guidelines, and metadata.

    Args:
        s3_client: S3Client instance
        book_id: Book ID
    """
    prefix = f"books/{book_id}/"
    cleanup_s3_prefix(s3_client, prefix)


def verify_book_has_s3_data(s3_client, book_id):
    """
    Verify a book has any S3 data.

    Args:
        s3_client: S3Client instance
        book_id: Book ID

    Returns:
        True if book has S3 data, False otherwise
    """
    prefix = f"books/{book_id}/"
    objects = list_s3_objects_with_prefix(s3_client, prefix)
    return len(objects) > 0
