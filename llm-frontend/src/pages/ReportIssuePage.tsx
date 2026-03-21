import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  interpretIssue,
  uploadIssueScreenshot,
  createIssue,
  transcribeAudio,
} from '../api';

type Phase = 'input' | 'interpreting' | 'review' | 'submitting' | 'done';

export default function ReportIssuePage() {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<Phase>('input');
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [uploadedKeys, setUploadedKeys] = useState<string[]>([]);
  const [interpretation, setInterpretation] = useState<{ title: string; description: string } | null>(null);
  const [error, setError] = useState('');

  // Audio recording
  const [recording, setRecording] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const [transcribing, setTranscribing] = useState(false);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Audio recording ─────────────────────────────
  const toggleRecording = async () => {
    if (recording) {
      mediaRecorderRef.current?.stop();
      setRecording(false);
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferredTypes = ['audio/webm', 'audio/mp4', 'audio/ogg'];
      const mimeType = preferredTypes.find((t) => MediaRecorder.isTypeSupported(t));
      const recorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);

      audioChunksRef.current = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(audioChunksRef.current, { type: recorder.mimeType });
        setTranscribing(true);
        try {
          const transcribedText = await transcribeAudio(blob);
          setText((prev) => (prev ? prev + ' ' + transcribedText : transcribedText));
        } catch {
          setError('Failed to transcribe audio. Please try again or type your issue.');
        } finally {
          setTranscribing(false);
        }
      };

      recorder.start();
      setRecording(true);
      mediaRecorderRef.current = recorder;
    } catch {
      setError('Microphone access denied. Please allow microphone access and try again.');
    }
  };

  // ── File handling ───────────────────────────────
  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    setFiles((prev) => [...prev, ...selected]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  // ── Submit for interpretation ───────────────────
  const handleInterpret = async (refinementText?: string) => {
    if (!text.trim() && !refinementText) return;
    setError('');
    setPhase('interpreting');

    try {
      // Upload screenshots if not already uploaded
      let keys = uploadedKeys;
      if (files.length > 0 && uploadedKeys.length === 0) {
        const uploadPromises = files.map((f) => uploadIssueScreenshot(f));
        keys = await Promise.all(uploadPromises);
        setUploadedKeys(keys);
      }

      const result = await interpretIssue({
        user_input: refinementText || text,
        has_screenshots: keys.length > 0,
        previous_interpretation: interpretation
          ? `Title: ${interpretation.title}\nDescription: ${interpretation.description}`
          : undefined,
        refinement_input: refinementText || undefined,
      });

      setInterpretation(result);
      setPhase('review');
    } catch {
      setError('Failed to interpret your issue. Please try again.');
      setPhase('input');
    }
  };

  // ── Final submit ────────────────────────────────
  const handleSubmit = async () => {
    if (!interpretation) return;
    setPhase('submitting');
    setError('');

    try {
      await createIssue({
        title: interpretation.title,
        description: interpretation.description,
        original_input: text,
        screenshot_s3_keys: uploadedKeys.length > 0 ? uploadedKeys : undefined,
      });
      setPhase('done');
    } catch {
      setError('Failed to submit issue. Please try again.');
      setPhase('review');
    }
  };

  // ── Refine ──────────────────────────────────────
  const [refineText, setRefineText] = useState('');
  const handleRefine = () => {
    if (!refineText.trim()) return;
    handleInterpret(refineText);
    setRefineText('');
  };

  // ── Styles ──────────────────────────────────────
  const containerStyle: React.CSSProperties = {
    maxWidth: '640px',
    margin: '0 auto',
    padding: '24px 16px',
  };

  const cardStyle: React.CSSProperties = {
    backgroundColor: 'white',
    borderRadius: '12px',
    padding: '24px',
    boxShadow: '0 1px 3px rgba(0,0,0,0.1)',
  };

  const btnPrimary: React.CSSProperties = {
    backgroundColor: '#4F46E5',
    color: 'white',
    border: 'none',
    borderRadius: '8px',
    padding: '12px 24px',
    fontSize: '15px',
    fontWeight: 600,
    cursor: 'pointer',
    width: '100%',
  };

  const btnSecondary: React.CSSProperties = {
    ...btnPrimary,
    backgroundColor: 'white',
    color: '#4F46E5',
    border: '1px solid #C7D2FE',
  };

  const btnDanger: React.CSSProperties = {
    ...btnPrimary,
    backgroundColor: '#EF4444',
  };

  // ── Done screen ─────────────────────────────────
  if (phase === 'done') {
    return (
      <div style={containerStyle}>
        <div style={{ ...cardStyle, textAlign: 'center' }}>
          <div style={{ fontSize: '48px', marginBottom: '16px' }}>&#10003;</div>
          <h2 style={{ margin: '0 0 8px', color: '#111827' }}>Issue Reported</h2>
          <p style={{ color: '#6B7280', marginBottom: '24px' }}>
            Thanks for reporting this issue! We'll look into it.
          </p>
          <button style={btnPrimary} onClick={() => navigate('/learn')}>
            Back to Home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div style={containerStyle}>
      <h1 style={{ fontSize: '24px', fontWeight: 700, color: '#111827', marginBottom: '4px' }}>
        Report an Issue
      </h1>
      <p style={{ color: '#6B7280', fontSize: '14px', marginBottom: '24px' }}>
        Tell us what went wrong — type, speak, or attach screenshots.
      </p>

      {error && (
        <div style={{
          backgroundColor: '#FEF2F2', color: '#DC2626', padding: '12px 16px',
          borderRadius: '8px', marginBottom: '16px', fontSize: '14px',
        }}>
          {error}
        </div>
      )}

      {/* ── Input phase ─────────────────────────── */}
      {(phase === 'input' || phase === 'interpreting') && (
        <div style={cardStyle}>
          <label style={{ display: 'block', fontWeight: 600, marginBottom: '8px', color: '#374151' }}>
            Describe the issue
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What happened? What were you trying to do?"
            rows={5}
            style={{
              width: '100%',
              border: '1px solid #D1D5DB',
              borderRadius: '8px',
              padding: '12px',
              fontSize: '15px',
              resize: 'vertical',
              fontFamily: 'inherit',
              boxSizing: 'border-box',
            }}
            disabled={phase === 'interpreting'}
          />

          {/* Mic + Upload row */}
          <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
            <button
              onClick={toggleRecording}
              disabled={phase === 'interpreting' || transcribing}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 16px',
                borderRadius: '8px',
                border: recording ? '2px solid #EF4444' : '1px solid #D1D5DB',
                backgroundColor: recording ? '#FEF2F2' : 'white',
                color: recording ? '#EF4444' : '#374151',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" y1="19" x2="12" y2="23"/>
                <line x1="8" y1="23" x2="16" y2="23"/>
              </svg>
              {transcribing ? 'Transcribing...' : recording ? 'Stop Recording' : 'Record'}
            </button>

            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={phase === 'interpreting'}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                padding: '8px 16px',
                borderRadius: '8px',
                border: '1px solid #D1D5DB',
                backgroundColor: 'white',
                color: '#374151',
                cursor: 'pointer',
                fontSize: '14px',
                fontWeight: 500,
              }}
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <rect x="3" y="3" width="18" height="18" rx="2" ry="2"/>
                <circle cx="8.5" cy="8.5" r="1.5"/>
                <polyline points="21 15 16 10 5 21"/>
              </svg>
              Screenshots
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              onChange={handleFileSelect}
              style={{ display: 'none' }}
            />
          </div>

          {/* File list */}
          {files.length > 0 && (
            <div style={{ marginTop: '12px' }}>
              {files.map((f, i) => (
                <div key={i} style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '6px 12px',
                  backgroundColor: '#F3F4F6',
                  borderRadius: '6px',
                  marginBottom: '4px',
                  fontSize: '13px',
                }}>
                  <span style={{ color: '#374151' }}>{f.name}</span>
                  <button
                    onClick={() => removeFile(i)}
                    style={{
                      border: 'none', background: 'none', color: '#9CA3AF',
                      cursor: 'pointer', fontSize: '16px', padding: '0 4px',
                    }}
                  >
                    x
                  </button>
                </div>
              ))}
            </div>
          )}

          <button
            onClick={() => handleInterpret()}
            disabled={(!text.trim() && files.length === 0) || phase === 'interpreting'}
            style={{
              ...btnPrimary,
              marginTop: '20px',
              opacity: (!text.trim() && files.length === 0) || phase === 'interpreting' ? 0.5 : 1,
            }}
          >
            {phase === 'interpreting' ? 'Analyzing...' : 'Submit for Review'}
          </button>
        </div>
      )}

      {/* ── Review phase ────────────────────────── */}
      {(phase === 'review' || phase === 'submitting') && interpretation && (
        <div style={cardStyle}>
          <p style={{ color: '#6B7280', fontSize: '14px', marginBottom: '16px' }}>
            Here's how we understood your issue. Is this correct?
          </p>

          <div style={{
            backgroundColor: '#F9FAFB',
            border: '1px solid #E5E7EB',
            borderRadius: '8px',
            padding: '16px',
            marginBottom: '20px',
          }}>
            <h3 style={{ margin: '0 0 8px', fontSize: '16px', color: '#111827' }}>
              {interpretation.title}
            </h3>
            <p style={{ margin: 0, color: '#374151', fontSize: '14px', lineHeight: '1.6' }}>
              {interpretation.description}
            </p>
          </div>

          <div style={{ display: 'flex', gap: '12px', marginBottom: '16px' }}>
            <button
              onClick={handleSubmit}
              disabled={phase === 'submitting'}
              style={{ ...btnPrimary, flex: 1, opacity: phase === 'submitting' ? 0.5 : 1 }}
            >
              {phase === 'submitting' ? 'Submitting...' : 'Yes, Submit'}
            </button>
          </div>

          <div style={{
            borderTop: '1px solid #E5E7EB',
            paddingTop: '16px',
          }}>
            <label style={{ display: 'block', fontWeight: 500, marginBottom: '8px', color: '#374151', fontSize: '14px' }}>
              Not quite right? Add more details:
            </label>
            <textarea
              value={refineText}
              onChange={(e) => setRefineText(e.target.value)}
              placeholder="Tell us what we got wrong..."
              rows={3}
              style={{
                width: '100%',
                border: '1px solid #D1D5DB',
                borderRadius: '8px',
                padding: '10px',
                fontSize: '14px',
                resize: 'vertical',
                fontFamily: 'inherit',
                boxSizing: 'border-box',
              }}
              disabled={phase === 'submitting'}
            />
            <button
              onClick={handleRefine}
              disabled={!refineText.trim() || phase === 'submitting'}
              style={{
                ...btnSecondary,
                marginTop: '8px',
                opacity: !refineText.trim() || phase === 'submitting' ? 0.5 : 1,
              }}
            >
              Re-analyze
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
