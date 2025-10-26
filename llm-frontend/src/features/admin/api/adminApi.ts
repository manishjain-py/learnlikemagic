/**
 * Admin API client for book ingestion
 */

import {
  Book,
  BookDetail,
  CreateBookRequest,
  PageUploadResponse,
  PageDetails,
} from '../types';

const API_BASE_URL = 'http://localhost:8000';

// Helper function for API calls
async function apiFetch<T>(
  endpoint: string,
  options?: RequestInit
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    ...options,
    headers: {
      ...options?.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return {} as T;
  }

  return response.json();
}

// ===== Book Management =====

export async function createBook(data: CreateBookRequest): Promise<Book> {
  return apiFetch<Book>('/admin/books', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
}

export async function listBooks(filters?: {
  country?: string;
  board?: string;
  grade?: number;
  subject?: string;
  status?: string;
}): Promise<{ books: Book[]; total: number }> {
  const params = new URLSearchParams();
  if (filters) {
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.append(key, String(value));
      }
    });
  }

  const query = params.toString();
  return apiFetch<{ books: Book[]; total: number }>(
    `/admin/books${query ? `?${query}` : ''}`
  );
}

export async function getBook(bookId: string): Promise<BookDetail> {
  return apiFetch<BookDetail>(`/admin/books/${bookId}`);
}

export async function updateBookStatus(
  bookId: string,
  status: string
): Promise<Book> {
  return apiFetch<Book>(`/admin/books/${bookId}/status`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ status }),
  });
}

export async function deleteBook(bookId: string): Promise<void> {
  return apiFetch<void>(`/admin/books/${bookId}`, {
    method: 'DELETE',
  });
}

// ===== Page Management =====

export async function uploadPage(
  bookId: string,
  imageFile: File
): Promise<PageUploadResponse> {
  const formData = new FormData();
  formData.append('image', imageFile);

  const response = await fetch(`${API_BASE_URL}/admin/books/${bookId}/pages`, {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(error.detail || `HTTP ${response.status}`);
  }

  return response.json();
}

export async function approvePage(
  bookId: string,
  pageNum: number
): Promise<{ page_num: number; status: string }> {
  return apiFetch(`/admin/books/${bookId}/pages/${pageNum}/approve`, {
    method: 'PUT',
  });
}

export async function deletePage(bookId: string, pageNum: number): Promise<void> {
  return apiFetch<void>(`/admin/books/${bookId}/pages/${pageNum}`, {
    method: 'DELETE',
  });
}

export async function getPage(
  bookId: string,
  pageNum: number
): Promise<PageDetails> {
  return apiFetch<PageDetails>(`/admin/books/${bookId}/pages/${pageNum}`);
}
