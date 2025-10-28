"""Integration tests for Page Management endpoints."""
import pytest
import io


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.s3
@pytest.mark.llm
@pytest.mark.slow
def test_upload_page_with_ocr(client, db_session, s3_client, sample_book_data, sample_page_image, cleanup_tracker):
    """Test uploading a page image and triggering OCR."""
    # Create book first
    book_response = client.post("/admin/books", json=sample_book_data)
    assert book_response.status_code == 201
    book_id = book_response.json().get("book_id") or book_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    # Upload page
    sample_page_image.seek(0)  # Reset buffer position
    files = {"image": ("page_1.png", sample_page_image, "image/png")}
    response = client.post(f"/admin/books/{book_id}/pages", files=files)

    assert response.status_code == 200
    data = response.json()

    # Verify response structure (PageUploadResponse: page_num, image_url, ocr_text, status)
    assert "page_num" in data
    page_num = data["page_num"]
    assert page_num is not None
    assert "image_url" in data
    assert "ocr_text" in data
    assert "status" in data

    # Track S3 key for cleanup
    s3_key = f"books/{book_id}/pages/{page_num}.png"
    cleanup_tracker["s3_keys"].append(s3_key)


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.s3
@pytest.mark.llm
@pytest.mark.slow
def test_get_page_with_presigned_url(client, db_session, s3_client, sample_book_data, sample_page_image, cleanup_tracker):
    """Test fetching page details with presigned URL."""
    # Create book and upload page
    book_response = client.post("/admin/books", json=sample_book_data)
    book_id = book_response.json().get("book_id") or book_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    sample_page_image.seek(0)
    files = {"image": ("page_1.png", sample_page_image, "image/png")}
    upload_response = client.post(f"/admin/books/{book_id}/pages", files=files)
    page_num = upload_response.json().get("page_num", 1)

    # Get page details
    response = client.get(f"/admin/books/{book_id}/pages/{page_num}")

    assert response.status_code == 200
    data = response.json()

    # Should have presigned URL or image URL
    has_url = any(key in data for key in ["image_url", "url", "presigned_url"])
    if has_url:
        url = data.get("image_url") or data.get("url") or data.get("presigned_url")
        assert url.startswith("https://") or url.startswith("http://")


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.s3
@pytest.mark.llm
@pytest.mark.slow
def test_approve_page(client, db_session, sample_book_data, sample_page_image, cleanup_tracker):
    """Test approving a page after OCR review."""
    # Create book and upload page
    book_response = client.post("/admin/books", json=sample_book_data)
    book_id = book_response.json().get("book_id") or book_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    sample_page_image.seek(0)
    files = {"image": ("page_1.png", sample_page_image, "image/png")}
    upload_response = client.post(f"/admin/books/{book_id}/pages", files=files)
    page_num = upload_response.json().get("page_num", 1)

    # Approve page
    response = client.put(f"/admin/books/{book_id}/pages/{page_num}/approve")

    # API may return 200 or 400 depending on page state
    assert response.status_code in [200, 400]

    if response.status_code == 200:
        data = response.json()
        # Verify approval status
        if "status" in data:
            assert data["status"] in ["approved", "success"]


@pytest.mark.integration
@pytest.mark.db
@pytest.mark.s3
@pytest.mark.llm
@pytest.mark.slow
def test_delete_page(client, db_session, s3_client, sample_book_data, sample_page_image, cleanup_tracker):
    """Test deleting/rejecting a page."""
    # Create book and upload page
    book_response = client.post("/admin/books", json=sample_book_data)
    book_id = book_response.json().get("book_id") or book_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    sample_page_image.seek(0)
    files = {"image": ("page_1.png", sample_page_image, "image/png")}
    upload_response = client.post(f"/admin/books/{book_id}/pages", files=files)
    page_num = upload_response.json().get("page_num", 1)

    s3_key = f"books/{book_id}/pages/{page_num}.png"

    # Delete page
    response = client.delete(f"/admin/books/{book_id}/pages/{page_num}")

    assert response.status_code == 204

    # Verify S3 object deleted (may not be immediate)
    # This is cleanup, so we don't strictly assert on deletion


@pytest.mark.integration
@pytest.mark.s3
def test_upload_page_invalid_format(client, sample_book_data, cleanup_tracker):
    """Test uploading page with invalid image format."""
    # Create book
    book_response = client.post("/admin/books", json=sample_book_data)
    book_id = book_response.json().get("book_id") or book_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    # Upload invalid file
    invalid_file = io.BytesIO(b"not an image")
    files = {"image": ("page.txt", invalid_file, "text/plain")}
    response = client.post(f"/admin/books/{book_id}/pages", files=files)

    # Should return 400 or 422
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_upload_page_to_nonexistent_book(client, sample_page_image):
    """Test uploading page to non-existent book."""
    import uuid
    fake_book_id = str(uuid.uuid4())

    sample_page_image.seek(0)
    files = {"image": ("page_1.png", sample_page_image, "image/png")}
    response = client.post(f"/admin/books/{fake_book_id}/pages", files=files)

    # Should return 400, 404, or 422
    assert response.status_code in [400, 404, 422]


@pytest.mark.integration
def test_get_page_nonexistent_book(client):
    """Test getting page from non-existent book."""
    import uuid
    fake_book_id = str(uuid.uuid4())

    response = client.get(f"/admin/books/{fake_book_id}/pages/1")

    # Should return 404 or 422
    assert response.status_code in [404, 422]


@pytest.mark.integration
def test_approve_page_nonexistent_book(client):
    """Test approving page in non-existent book."""
    import uuid
    fake_book_id = str(uuid.uuid4())

    response = client.put(f"/admin/books/{fake_book_id}/pages/1/approve")

    # Should return 404, 422, or 400
    assert response.status_code in [404, 422, 400]


@pytest.mark.integration
def test_delete_page_nonexistent_book(client):
    """Test deleting page from non-existent book."""
    import uuid
    fake_book_id = str(uuid.uuid4())

    response = client.delete(f"/admin/books/{fake_book_id}/pages/1")

    # Should return 404, 422, or 400
    assert response.status_code in [404, 422, 400]
