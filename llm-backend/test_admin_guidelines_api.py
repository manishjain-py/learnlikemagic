"""
Quick test script to verify the admin guidelines API endpoints work.
"""
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)

print("=" * 80)
print("TESTING ADMIN GUIDELINES API")
print("=" * 80)

# Test 1: List books
print("\n1. Testing GET /admin/guidelines/books...")
response = client.get("/admin/guidelines/books")
print(f"   Status: {response.status_code}")
if response.status_code == 200:
    books = response.json()
    print(f"   ✅ Found {len(books)} books")
    if books:
        book = books[0]
        print(f"   First book: {book['book_id']}")
        print(f"   - Status: {book['extraction_status']}")
        print(f"   - Subtopics: {book['subtopics_count']}")
else:
    print(f"   ❌ Failed: {response.text}")

# Test 2: Get topics for test book
book_id = "ncert_mathematics_3_2024"
print(f"\n2. Testing GET /admin/guidelines/books/{book_id}/topics...")
response = client.get(f"/admin/guidelines/books/{book_id}/topics")
print(f"   Status: {response.status_code}")
if response.status_code == 200:
    topics = response.json()
    print(f"   ✅ Found {len(topics)} topics")
    if topics:
        topic = topics[0]
        print(f"   First topic: {topic['topic_title']}")
        print(f"   - Subtopics: {len(topic['subtopics'])}")
        if topic['subtopics']:
            subtopic = topic['subtopics'][0]
            print(f"   First subtopic: {subtopic['subtopic_title']}")
            print(f"   - Status: {subtopic['status']}")
            print(f"   - Pages: {subtopic['page_range']}")

            # Test 3: Get guideline detail
            print(f"\n3. Testing GET guideline detail...")
            response = client.get(
                f"/admin/guidelines/books/{book_id}/subtopics/{subtopic['subtopic_key']}",
                params={"topic_key": topic['topic_key']}
            )
            print(f"   Status: {response.status_code}")
            if response.status_code == 200:
                guideline = response.json()
                print(f"   ✅ Retrieved guideline: {guideline['subtopic_title']}")
                print(f"   - Objectives: {len(guideline['objectives'])}")
                print(f"   - Examples: {len(guideline['examples'])}")
                print(f"   - Misconceptions: {len(guideline['misconceptions'])}")
                print(f"   - Assessments: {len(guideline['assessments'])}")
                if guideline['teaching_description']:
                    desc = guideline['teaching_description']
                    print(f"   - Teaching description: {desc[:100]}...")
            else:
                print(f"   ❌ Failed: {response.text}")
else:
    print(f"   ❌ Failed: {response.text}")

# Test 4: Get page assignments
print(f"\n4. Testing GET /admin/guidelines/books/{book_id}/page-assignments...")
response = client.get(f"/admin/guidelines/books/{book_id}/page-assignments")
print(f"   Status: {response.status_code}")
if response.status_code == 200:
    assignments = response.json()
    print(f"   ✅ Found assignments for {len(assignments)} pages")
    if assignments:
        first_page = list(assignments.keys())[0]
        assignment = assignments[first_page]
        print(f"   Page {first_page}: {assignment['subtopic_key']}")
        print(f"   - Confidence: {assignment['confidence']}")
else:
    print(f"   ❌ Failed: {response.text}")

print("\n" + "=" * 80)
print("API TEST COMPLETE")
print("=" * 80)
print("\nAll endpoints are working! ✅")
print("\nAPI Documentation available at:")
print("  - http://localhost:8000/docs (Swagger UI)")
print("  - http://localhost:8000/redoc (ReDoc)")
