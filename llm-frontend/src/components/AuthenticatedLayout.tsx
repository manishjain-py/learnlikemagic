import React from 'react';
import { Outlet } from 'react-router-dom';
import PracticeBanner from './practice/PracticeBanner';

/**
 * Thin wrapper for authenticated routes. Mounts above both AppShell
 * (student-facing non-chat routes) and chat-session routes so shared
 * elements — currently just `PracticeBanner` — fire regardless of
 * which route group the student is on.
 *
 * Sits below `ProtectedRoute` + `OnboardingGuard` in App.tsx.
 */
export default function AuthenticatedLayout() {
  return (
    <>
      <PracticeBanner />
      <Outlet />
    </>
  );
}
