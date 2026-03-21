import React, { useState, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  uploadIssueScreenshot,
  createIssue,
  transcribeAudio,
} from '../api';

export default function ReportIssuePage() {
  const navigate = useNavigate();
  const [text, setText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState('');

  // Audio recording
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);

  const fileInputRef = useRef<HTMLInputElement>(null);

  // ── Audio recording (matches ChatSession pattern) ───
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
      const mediaRecorder = mimeType
        ? new MediaRecorder(stream, { mimeType })
        : new MediaRecorder(stream);
      const activeMime = mediaRecorder.mimeType || 'audio/webm';

      audioChunksRef.current = [];

      mediaRecorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      mediaRecorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        mediaRecorderRef.current = null;

        const audioBlob = new Blob(audioChunksRef.current, { type: activeMime });
        if (audioBlob.size === 0) return;

        setTranscribing(true);
        try {
          const transcribedText = await transcribeAudio(audioBlob);
          if (transcribedText) {
            setText((prev) => (prev ? prev + ' ' + transcribedText : transcribedText));
          }
        } catch {
          setError('Failed to transcribe audio. Please try again or type your issue.');
        } finally {
          setTranscribing(false);
        }
      };

      mediaRecorder.start();
      mediaRecorderRef.current = mediaRecorder;
      setRecording(true);
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

  // ── Submit ──────────────────────────────────────
  const handleSubmit = async () => {
    if (!text.trim() && files.length === 0) return;
    setError('');
    setSubmitting(true);

    try {
      // Upload screenshots
      let screenshotKeys: string[] = [];
      if (files.length > 0) {
        screenshotKeys = await Promise.all(files.map((f) => uploadIssueScreenshot(f)));
      }

      // Create issue — title is first 80 chars of input
      const title = text.trim().slice(0, 80) || 'Issue with screenshots';
      await createIssue({
        title,
        description: text.trim(),
        original_input: text.trim(),
        screenshot_s3_keys: screenshotKeys.length > 0 ? screenshotKeys : undefined,
      });

      setDone(true);
    } catch {
      setError('Failed to submit issue. Please try again.');
      setSubmitting(false);
    }
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

  // ── Done screen ─────────────────────────────────
  if (done) {
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

  const canSubmit = (text.trim() || files.length > 0) && !submitting && !recording && !transcribing;

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
          disabled={submitting}
        />

        {/* Mic + Upload row */}
        <div style={{ display: 'flex', gap: '12px', marginTop: '12px' }}>
          <button
            onClick={toggleRecording}
            disabled={submitting || transcribing}
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
            disabled={submitting}
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

        {/* Screenshot previews */}
        {files.length > 0 && (
          <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', marginTop: '12px' }}>
            {files.map((f, i) => (
              <div key={i} style={{ position: 'relative', width: '100px', height: '100px' }}>
                <img
                  src={URL.createObjectURL(f)}
                  alt={f.name}
                  style={{
                    width: '100%',
                    height: '100%',
                    objectFit: 'cover',
                    borderRadius: '8px',
                    border: '1px solid #E5E7EB',
                  }}
                />
                <button
                  onClick={() => removeFile(i)}
                  style={{
                    position: 'absolute',
                    top: '-6px',
                    right: '-6px',
                    width: '22px',
                    height: '22px',
                    borderRadius: '50%',
                    border: '1px solid #D1D5DB',
                    backgroundColor: 'white',
                    color: '#6B7280',
                    cursor: 'pointer',
                    fontSize: '12px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    padding: 0,
                  }}
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={handleSubmit}
          disabled={!canSubmit}
          style={{
            ...btnPrimary,
            marginTop: '20px',
            opacity: canSubmit ? 1 : 0.5,
          }}
        >
          {submitting ? 'Submitting...' : 'Submit Issue'}
        </button>
      </div>
    </div>
  );
}
