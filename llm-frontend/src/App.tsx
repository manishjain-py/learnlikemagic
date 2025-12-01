/**
 * Main App with Routing
 *
 * Routes:
 * / - Tutor interface (existing app)
 * /admin - Admin dashboard
 * /admin/books - Books list
 * /admin/books/new - Create book
 * /admin/books/:id - Book detail
 * /admin/guidelines - Guidelines review
 */

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import TutorApp from './TutorApp';

// Admin pages
import BooksDashboard from './features/admin/pages/BooksDashboard';
import CreateBook from './features/admin/pages/CreateBook';
import BookDetail from './features/admin/pages/BookDetail';
import GuidelinesReview from './features/admin/pages/GuidelinesReview';

function App() {
  return (
    <BrowserRouter>
      <Routes>
        {/* Main tutor interface */}
        <Route path="/" element={<TutorApp />} />

        {/* Admin routes */}
        <Route path="/admin" element={<Navigate to="/admin/books" replace />} />
        <Route path="/admin/books" element={<BooksDashboard />} />
        <Route path="/admin/books/new" element={<CreateBook />} />
        <Route path="/admin/books/:id" element={<BookDetail />} />
        <Route path="/admin/guidelines" element={<GuidelinesReview />} />
      </Routes>
    </BrowserRouter>
  );
}

export default App;
