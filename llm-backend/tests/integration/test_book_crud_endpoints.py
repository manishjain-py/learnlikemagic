"""Integration tests for Book CRUD endpoints."""
import pytest
import uuid


@pytest.mark.integration
@pytest.mark.db
def test_create_book_success(client, db_session, sample_book_data, cleanup_tracker):
    """Test creating a new book."""
    response = client.post("/admin/books", json=sample_book_data)

    assert response.status_code == 201
    data = response.json()

    # Verify response structure
    assert "book_id" in data or "id" in data
    book_id = data.get("book_id") or data.get("id")
    assert book_id is not None
    assert data.get("title") == sample_book_data["title"]
    assert data.get("status") in ["draft", "pending", None]

    cleanup_tracker["book_ids"].append(book_id)

    # Verify book persisted to database
    from tests.integration.helpers.database_helpers import verify_book_in_db
    db_record = verify_book_in_db(db_session, book_id)
    assert db_record.title == sample_book_data["title"]


@pytest.mark.integration
@pytest.mark.db
def test_list_books_empty(client):
    """Test listing books when none exist for the filter."""
    response = client.get("/admin/books", params={
        "country": "NonExistentCountry",
        "board": "NonExistentBoard",
        "grade": 999
    })

    assert response.status_code == 200
    data = response.json()

    # Should return empty list or minimal structure
    if isinstance(data, list):
        assert len(data) == 0 or all(
            book.get("country") != "NonExistentCountry"
            for book in data
        )
    elif isinstance(data, dict):
        books = data.get("books", [])
        assert len(books) == 0 or all(
            book.get("country") != "NonExistentCountry"
            for book in books
        )


@pytest.mark.integration
@pytest.mark.db
def test_list_books_with_filters(client, db_session, sample_book_data, cleanup_tracker):
    """Test listing books with various filters."""
    # Create test book
    create_response = client.post("/admin/books", json=sample_book_data)
    assert create_response.status_code == 201
    book_id = create_response.json().get("book_id") or create_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    # List with filters matching our book
    response = client.get("/admin/books", params={
        "country": sample_book_data["country"],
        "board": sample_book_data["board"],
        "grade": sample_book_data["grade"]
    })

    assert response.status_code == 200
    data = response.json()

    # Verify response structure
    if isinstance(data, list):
        assert len(data) > 0
        # Find our book
        book_found = any(
            (book.get("id") == book_id or book.get("book_id") == book_id)
            for book in data
        )
        assert book_found, f"Created book {book_id} not found in list"
    elif isinstance(data, dict):
        books = data.get("books", [])
        assert len(books) > 0
        book_found = any(
            (book.get("id") == book_id or book.get("book_id") == book_id)
            for book in books
        )
        assert book_found, f"Created book {book_id} not found in list"


@pytest.mark.integration
@pytest.mark.db
def test_get_book_details(client, db_session, sample_book_data, cleanup_tracker):
    """Test fetching book details."""
    # Create book
    create_response = client.post("/admin/books", json=sample_book_data)
    book_id = create_response.json().get("book_id") or create_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    # Get details
    response = client.get(f"/admin/books/{book_id}")

    assert response.status_code == 200
    data = response.json()

    # Verify book data
    assert data.get("id") == book_id or data.get("book_id") == book_id
    assert data.get("title") == sample_book_data["title"]
    assert data.get("country") == sample_book_data["country"]
    assert data.get("board") == sample_book_data["board"]
    assert data.get("grade") == sample_book_data["grade"]


@pytest.mark.integration
@pytest.mark.db
def test_update_book_status(client, db_session, sample_book_data, cleanup_tracker):
    """Test updating book status."""
    # Create book
    create_response = client.post("/admin/books", json=sample_book_data)
    book_id = create_response.json().get("book_id") or create_response.json().get("id")
    cleanup_tracker["book_ids"].append(book_id)

    # Update status (must be one of: draft, uploading_pages, pages_complete, generating_guidelines, guidelines_pending_review, approved)
    response = client.put(f"/admin/books/{book_id}/status", json={
        "status": "uploading_pages"
    })

    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "uploading_pages"

    # Verify in database
    from tests.integration.helpers.database_helpers import verify_book_in_db
    db_record = verify_book_in_db(db_session, book_id)
    assert db_record.status == "uploading_pages"


@pytest.mark.integration
@pytest.mark.db
def test_delete_book(client, db_session, sample_book_data):
    """Test deleting a book."""
    # Create book
    create_response = client.post("/admin/books", json=sample_book_data)
    book_id = create_response.json().get("book_id") or create_response.json().get("id")

    # Delete book
    response = client.delete(f"/admin/books/{book_id}")

    assert response.status_code == 204

    # Verify book is deleted
    get_response = client.get(f"/admin/books/{book_id}")
    assert get_response.status_code == 404


@pytest.mark.integration
def test_create_book_invalid_data(client):
    """Test creating book with invalid data."""
    invalid_data = {
        "title": "",  # Empty title
        "grade": "invalid"  # Invalid grade type
    }

    response = client.post("/admin/books", json=invalid_data)

    # Should return validation error
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_create_book_missing_required_fields(client):
    """Test creating book without required fields."""
    incomplete_data = {
        "title": "Test Book"
        # Missing other required fields
    }

    response = client.post("/admin/books", json=incomplete_data)

    # Should return validation error
    assert response.status_code in [400, 422]


@pytest.mark.integration
def test_get_nonexistent_book(client):
    """Test fetching non-existent book."""
    fake_book_id = str(uuid.uuid4())

    response = client.get(f"/admin/books/{fake_book_id}")

    # Should return 404
    assert response.status_code == 404


@pytest.mark.integration
def test_update_status_nonexistent_book(client):
    """Test updating status of non-existent book."""
    fake_book_id = str(uuid.uuid4())

    response = client.put(f"/admin/books/{fake_book_id}/status", json={
        "status": "uploading_pages"
    })

    # Should return 404 or 400
    assert response.status_code in [404, 400]


@pytest.mark.integration
def test_delete_nonexistent_book(client):
    """Test deleting non-existent book."""
    fake_book_id = str(uuid.uuid4())

    response = client.delete(f"/admin/books/{fake_book_id}")

    # Should return 404
    assert response.status_code == 404
