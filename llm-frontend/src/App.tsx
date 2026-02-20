/**
 * Main App with Routing
 *
 * Routes:
 * /login - Welcome/auth screen
 * /login/* - Auth flow pages
 * /onboarding - Post-signup profile wizard
 * / - Tutor interface (protected)
 * /profile - User profile settings (protected)
 * /history - Session history (protected)
 * /admin/* - Admin dashboard
 */

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import OnboardingGuard from './components/OnboardingGuard';
import TutorApp from './TutorApp';

// Auth pages
import LoginPage from './pages/LoginPage';
import EmailLoginPage from './pages/EmailLoginPage';
import EmailSignupPage from './pages/EmailSignupPage';
import PhoneLoginPage from './pages/PhoneLoginPage';
import OTPVerifyPage from './pages/OTPVerifyPage';
import ForgotPasswordPage from './pages/ForgotPasswordPage';
import OAuthCallbackPage from './pages/OAuthCallbackPage';
import EmailVerifyPage from './pages/EmailVerifyPage';

// Protected pages
import OnboardingFlow from './pages/OnboardingFlow';
import ProfilePage from './pages/ProfilePage';
import SessionHistoryPage from './pages/SessionHistoryPage';
import ScorecardPage from './pages/ScorecardPage';

// Admin pages
import BooksDashboard from './features/admin/pages/BooksDashboard';
import CreateBook from './features/admin/pages/CreateBook';
import BookDetail from './features/admin/pages/BookDetail';
import GuidelinesReview from './features/admin/pages/GuidelinesReview';
import EvaluationDashboard from './features/admin/pages/EvaluationDashboard';

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          {/* Public auth routes */}
          <Route path="/login" element={<LoginPage />} />
          <Route path="/login/email" element={<EmailLoginPage />} />
          <Route path="/login/phone" element={<PhoneLoginPage />} />
          <Route path="/login/phone/verify" element={<OTPVerifyPage />} />
          <Route path="/signup/email" element={<EmailSignupPage />} />
          <Route path="/signup/email/verify" element={<EmailVerifyPage />} />
          <Route path="/forgot-password" element={<ForgotPasswordPage />} />
          <Route path="/auth/callback" element={<OAuthCallbackPage />} />

          {/* Onboarding (authenticated but profile incomplete) */}
          <Route path="/onboarding" element={
            <ProtectedRoute>
              <OnboardingFlow />
            </ProtectedRoute>
          } />

          {/* Protected routes */}
          <Route path="/" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <TutorApp />
              </OnboardingGuard>
            </ProtectedRoute>
          } />

          <Route path="/profile" element={
            <ProtectedRoute>
              <ProfilePage />
            </ProtectedRoute>
          } />

          <Route path="/history" element={
            <ProtectedRoute>
              <SessionHistoryPage />
            </ProtectedRoute>
          } />

          <Route path="/scorecard" element={
            <ProtectedRoute>
              <ScorecardPage />
            </ProtectedRoute>
          } />

          {/* Admin routes (unchanged, no auth required for now) */}
          <Route path="/admin" element={<Navigate to="/admin/books" replace />} />
          <Route path="/admin/books" element={<BooksDashboard />} />
          <Route path="/admin/books/new" element={<CreateBook />} />
          <Route path="/admin/books/:id" element={<BookDetail />} />
          <Route path="/admin/guidelines" element={<GuidelinesReview />} />
          <Route path="/admin/evaluation" element={<EvaluationDashboard />} />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
