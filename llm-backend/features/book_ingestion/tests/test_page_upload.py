"""
Test script for page upload functionality.

Creates a simple test image and uploads it to test the complete flow.
"""
from PIL import Image, ImageDraw, ImageFont
import io
import requests
import json

# Create a simple test book page image
def create_test_page():
    """Create a simple test page image with text."""
    # Create image
    width, height = 800, 1000
    image = Image.new('RGB', (width, height), color='white')
    draw = ImageDraw.Draw(image)

    # Add some text content
    text_content = """
    Chapter 1: Fractions

    Understanding Fractions

    A fraction represents a part of a whole. For example, if you have
    a pizza cut into 8 equal slices and you eat 3 slices, you have
    eaten 3/8 of the pizza.

    The top number is called the numerator (3).
    The bottom number is called the denominator (8).

    Example 1: Compare 3/8 and 5/8

    Since both fractions have the same denominator (8), we compare
    the numerators. 5 is greater than 3, so 5/8 > 3/8.

    Practice Problem:
    Which is larger: 2/7 or 5/7?

    Answer: 5/7 is larger because 5 > 2.
    """

    # Draw text (simple, no fancy font)
    y = 50
    for line in text_content.strip().split('\n'):
        draw.text((50, y), line.strip(), fill='black')
        y += 30

    # Save to bytes
    img_bytes = io.BytesIO()
    image.save(img_bytes, format='PNG')
    img_bytes.seek(0)

    return img_bytes.getvalue()


def test_upload_flow():
    """Test the complete page upload flow."""
    base_url = "http://localhost:8000"
    book_id = "ncert_mathematics_3_2024"

    print("🧪 Testing Page Upload Flow\n")

    # Create test image
    print("1. Creating test page image...")
    image_data = create_test_page()
    print(f"   ✓ Created test image ({len(image_data)} bytes)\n")

    # Upload page
    print("2. Uploading page to API...")
    files = {'image': ('test_page.png', image_data, 'image/png')}

    try:
        response = requests.post(
            f"{base_url}/admin/books/{book_id}/pages",
            files=files,
            timeout=60  # OCR might take a while
        )

        if response.status_code == 200:
            result = response.json()
            print(f"   ✓ Page uploaded successfully!")
            print(f"   Page number: {result['page_num']}")
            print(f"   Status: {result['status']}")
            print(f"   Image URL: {result['image_url'][:80]}...")
            print(f"\n   OCR Text Preview:")
            print(f"   {'-' * 60}")
            print(f"   {result['ocr_text'][:500]}...")
            print(f"   {'-' * 60}\n")

            page_num = result['page_num']

            # Approve page
            print("3. Approving page...")
            approve_response = requests.put(
                f"{base_url}/admin/books/{book_id}/pages/{page_num}/approve"
            )

            if approve_response.status_code == 200:
                approve_result = approve_response.json()
                print(f"   ✓ Page approved!")
                print(f"   Status: {approve_result['status']}\n")

                # Get book details to see the page
                print("4. Fetching book details...")
                book_response = requests.get(f"{base_url}/admin/books/{book_id}")

                if book_response.status_code == 200:
                    book = book_response.json()
                    print(f"   ✓ Book retrieved")
                    print(f"   Title: {book['title']}")
                    print(f"   Page Count: {book['page_count']}")
                    print(f"   Guideline Count: {book['guideline_count']}")
                    print(f"   Approved Count: {book['approved_guideline_count']}")
                    print(f"   Total pages: {len(book['pages'])}")
                    print(f"\n   Pages:")
                    for page in book['pages']:
                        print(f"     - Page {page['page_num']}: {page['status']}")

                    print(f"\n✅ All tests passed!")
                else:
                    print(f"   ❌ Failed to get book: {book_response.status_code}")
                    print(f"   {book_response.text}")
            else:
                print(f"   ❌ Failed to approve page: {approve_response.status_code}")
                print(f"   {approve_response.text}")
        else:
            print(f"   ❌ Upload failed: {response.status_code}")
            print(f"   {response.text}")

    except requests.exceptions.ConnectionError:
        print("   ❌ Cannot connect to server. Is it running?")
        print("   Start server with: uvicorn main:app --reload")
    except Exception as e:
        print(f"   ❌ Error: {e}")


if __name__ == "__main__":
    test_upload_flow()
