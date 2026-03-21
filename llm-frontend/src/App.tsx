/**
 * Main App with Routing
 *
 * Routes:
 * /login - Welcome/auth screen
 * /login/* - Auth flow pages
 * /onboarding - Post-signup profile wizard
 * /learn - Subject selection (protected)
 * /learn/:subject - Chapter selection
 * /learn/:subject/:chapter - Topic selection
 * /learn/:subject/:chapter/:topic - Mode selection
 * /session/:sessionId - Chat session (protected)
 * / - Redirect to /learn
 * /profile - User profile settings (protected)
 * /history - Session history (protected)
 * /admin/* - Admin dashboard
 */

import React from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';
import ProtectedRoute from './components/ProtectedRoute';
import OnboardingGuard from './components/OnboardingGuard';
import AppShell from './components/AppShell';

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
import EnrichmentPage from './pages/EnrichmentPage';
import SessionHistoryPage from './pages/SessionHistoryPage';
import ReportCardPage from './pages/ReportCardPage';
import ReportIssuePage from './pages/ReportIssuePage';

// Learn pages
import SubjectSelect from './pages/SubjectSelect';
import ChapterSelect from './pages/ChapterSelect';
import TopicSelect from './pages/TopicSelect';
import ModeSelectPage from './pages/ModeSelectPage';
import ChatSession from './pages/ChatSession';
import ExamReviewPage from './pages/ExamReviewPage';

// Admin pages
import EvaluationDashboard from './features/admin/pages/EvaluationDashboard';
import DocsViewer from './features/admin/pages/DocsViewer';
import LLMConfigPage from './features/admin/pages/LLMConfigPage';
import TestScenariosPage from './features/admin/pages/TestScenariosPage';
import BookV2Dashboard from './features/admin/pages/BookV2Dashboard';
import CreateBookV2 from './features/admin/pages/CreateBookV2';
import BookV2Detail from './features/admin/pages/BookV2Detail';
import PixiJsPocPage from './features/admin/pages/PixiJsPocPage';
import FeatureFlagsPage from './features/admin/pages/FeatureFlagsPage';
import AdminIssuesPage from './features/admin/pages/AdminIssuesPage';
import AdminLayout from './features/admin/components/AdminLayout';
import AdminHome from './features/admin/pages/AdminHome';

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

          {/* All authenticated post-onboarding routes under AppShell */}
          <Route element={
            <ProtectedRoute>
              <OnboardingGuard>
                <AppShell />
              </OnboardingGuard>
            </ProtectedRoute>
          }>
            {/* Learn routes */}
            <Route path="/learn" element={<SubjectSelect />} />
            <Route path="/learn/:subject" element={<ChapterSelect />} />
            <Route path="/learn/:subject/:chapter" element={<TopicSelect />} />
            <Route path="/learn/:subject/:chapter/:topic" element={<ModeSelectPage />} />
            <Route path="/learn/:subject/:chapter/:topic/exam-review/:sessionId" element={<ExamReviewPage />} />

            {/* Profile & settings */}
            <Route path="/profile" element={<ProfilePage />} />
            <Route path="/profile/enrichment" element={<EnrichmentPage />} />

            {/* History & report card */}
            <Route path="/history" element={<SessionHistoryPage />} />
            <Route path="/report-card" element={<ReportCardPage />} />

            {/* Issue reporting */}
            <Route path="/report-issue" element={<ReportIssuePage />} />
          </Route>

          {/* Chat session routes — OUTSIDE AppShell (own nav-bar) */}
          <Route path="/learn/:subject/:chapter/:topic/teach/:sessionId" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <ChatSession />
              </OnboardingGuard>
            </ProtectedRoute>
          } />
          <Route path="/learn/:subject/:chapter/:topic/exam/:sessionId" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <ChatSession />
              </OnboardingGuard>
            </ProtectedRoute>
          } />
          <Route path="/learn/:subject/:chapter/:topic/clarify/:sessionId" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <ChatSession />
              </OnboardingGuard>
            </ProtectedRoute>
          } />

          {/* Backward compat: old session URL */}
          <Route path="/session/:sessionId" element={
            <ProtectedRoute>
              <OnboardingGuard>
                <ChatSession />
              </OnboardingGuard>
            </ProtectedRoute>
          } />

          {/* Backward compat: redirect / to /learn */}
          <Route path="/" element={<Navigate to="/learn" replace />} />

          {/* Admin routes — wrapped in shared AdminLayout with top nav */}
          <Route path="/admin" element={<AdminLayout />}>
            <Route index element={<AdminHome />} />
            <Route path="books" element={<Navigate to="/admin/books-v2" replace />} />
            <Route path="evaluation" element={<EvaluationDashboard />} />
            <Route path="docs" element={<DocsViewer />} />
            <Route path="llm-config" element={<LLMConfigPage />} />
            <Route path="test-scenarios" element={<TestScenariosPage />} />
            <Route path="books-v2" element={<BookV2Dashboard />} />
            <Route path="books-v2/new" element={<CreateBookV2 />} />
            <Route path="books-v2/:id" element={<BookV2Detail />} />
            <Route path="pixi-js-poc" element={<PixiJsPocPage />} />
            <Route path="feature-flags" element={<FeatureFlagsPage />} />
            <Route path="issues" element={<AdminIssuesPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
