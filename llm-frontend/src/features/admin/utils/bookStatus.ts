import { Book } from '../types';

export type DisplayStatus =
    | 'no_pages'
    | 'ready_for_extraction'
    | 'processing'
    | 'pending_review'
    | 'approved';

export function getDisplayStatus(book: Book): DisplayStatus {
    if (book.has_active_job) return 'processing';
    if (book.page_count === 0) return 'no_pages';
    if (book.guideline_count === 0) return 'ready_for_extraction';
    if (book.approved_guideline_count === book.guideline_count && book.guideline_count > 0) return 'approved';
    return 'pending_review';
}

export function getStatusLabel(status: DisplayStatus): string {
    switch (status) {
        case 'no_pages': return 'Draft';
        case 'ready_for_extraction': return 'Ready for Extraction';
        case 'processing': return 'Processing';
        case 'pending_review': return 'Pending Review';
        case 'approved': return 'Approved';
        default: return status;
    }
}

export function getStatusColor(status: DisplayStatus): "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning" {
    switch (status) {
        case 'no_pages': return 'default';
        case 'ready_for_extraction': return 'info';
        case 'processing': return 'warning';
        case 'pending_review': return 'primary';
        case 'approved': return 'success';
        default: return 'default';
    }
}
