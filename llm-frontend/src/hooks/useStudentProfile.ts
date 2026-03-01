import { useAuth } from '../contexts/AuthContext';

export interface StudentProfile {
  country: string;
  board: string;
  grade: number;
  studentId: string;
  studentName: string;
}

export function useStudentProfile(): StudentProfile {
  const { user } = useAuth();
  return {
    country: 'India',
    board: user?.board || 'CBSE',
    grade: user?.grade || 3,
    studentId: user?.id || 's1',
    studentName: user?.preferred_name || user?.name || '',
  };
}
