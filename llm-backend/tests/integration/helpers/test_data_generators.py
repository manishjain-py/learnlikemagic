"""Test data generation utilities."""
import uuid
from PIL import Image, ImageDraw
import io


def generate_test_student_id(prefix="test"):
    """Generate a unique test student ID."""
    return f"{prefix}_student_{uuid.uuid4().hex[:8]}"


def generate_test_book_title(prefix="test"):
    """Generate a unique test book title."""
    return f"{prefix}_Test_Book_{uuid.uuid4().hex[:8]}"


def generate_sample_page_image(page_num=1, content=None):
    """
    Generate a sample page image with specific content.

    Args:
        page_num: Page number to include in content
        content: Optional list of text lines to include

    Returns:
        BytesIO object containing PNG image
    """
    # Create a test image with text
    img = Image.new('RGB', (800, 1000), color='white')
    draw = ImageDraw.Draw(img)

    # Default content if not provided
    if content is None:
        content = [
            f"Page {page_num}",
            "",
            "Linear Equations",
            "",
            "A linear equation is an equation of the form ax + b = c",
            "where a, b, and c are constants and x is a variable.",
            "",
            "Examples:",
            "1. 2x + 3 = 7",
            "2. 5x - 4 = 11",
            f"3. {page_num}x + 8 = 15"
        ]

    # Draw text lines
    y_position = 50
    for line in content:
        draw.text((50, y_position), str(line), fill='black')
        y_position += 40

    # Convert to bytes
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


def generate_test_book_with_pages(num_pages=5, title_prefix="test"):
    """
    Generate a complete test book with pages.

    Args:
        num_pages: Number of pages to generate
        title_prefix: Prefix for book title

    Returns:
        Tuple of (book_data, list_of_page_images)
    """
    book_data = {
        "title": generate_test_book_title(title_prefix),
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subject": "Mathematics",
        "publisher": "Test Publisher",
        "year": 2024,
        "isbn": f"test-isbn-{uuid.uuid4().hex[:12]}"
    }

    pages = [generate_sample_page_image(i) for i in range(1, num_pages + 1)]

    return book_data, pages


def generate_sample_guidelines_data():
    """
    Generate sample guidelines data for testing.

    Returns:
        Dictionary with guideline structure
    """
    return {
        "subtopic_shard": {
            "subtopic_key": "linear_equations_basics",
            "subtopic_name": "Linear Equations Basics",
            "topic_key": "algebra",
            "topic_name": "Algebra"
        },
        "teaching_description": "Teach students how to solve basic linear equations by isolating the variable.",
        "sorted_facts": [
            "A linear equation has one variable with degree 1",
            "The goal is to isolate the variable on one side",
            "Use inverse operations to solve for the variable"
        ],
        "page_range": "1-3"
    }


def generate_sample_curriculum_data():
    """
    Generate sample curriculum data for testing.

    Returns:
        Dictionary with curriculum hierarchy
    """
    return {
        "country": "India",
        "board": "CBSE",
        "grade": 8,
        "subjects": [
            {
                "name": "Mathematics",
                "topics": [
                    {
                        "name": "Algebra",
                        "subtopics": [
                            "Linear Equations",
                            "Quadratic Equations",
                            "Polynomials"
                        ]
                    },
                    {
                        "name": "Geometry",
                        "subtopics": [
                            "Triangles",
                            "Circles",
                            "Quadrilaterals"
                        ]
                    }
                ]
            }
        ]
    }
