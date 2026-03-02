"""
Chunk builder utility — builds 3-page processing windows from a page list.

Pages [1,2,3,4,5,6,7,8,9,10] → Chunks:
  [0] pages=[1,2,3]  prev=None
  [1] pages=[4,5,6]  prev=3
  [2] pages=[7,8,9]  prev=6
  [3] pages=[10]     prev=9
"""
from typing import List

from book_ingestion_v2.constants import CHUNK_SIZE, CHUNK_STRIDE
from book_ingestion_v2.models.processing_models import ChunkWindow


def build_chunk_windows(page_numbers: List[int]) -> List[ChunkWindow]:
    """
    Build non-overlapping chunk windows from a sorted list of page numbers.

    Args:
        page_numbers: Sorted list of absolute page numbers.

    Returns:
        List of ChunkWindow objects.
    """
    if not page_numbers:
        return []

    sorted_pages = sorted(page_numbers)
    chunks = []

    for i in range(0, len(sorted_pages), CHUNK_STRIDE):
        chunk_pages = sorted_pages[i : i + CHUNK_SIZE]
        previous_page = sorted_pages[i - 1] if i > 0 else None

        chunks.append(
            ChunkWindow(
                chunk_index=len(chunks),
                pages=chunk_pages,
                previous_page=previous_page,
            )
        )

    return chunks
