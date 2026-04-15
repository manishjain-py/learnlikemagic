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

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = Array.from(e.target.files || []);
    setFiles((prev) => [...prev, ...selected]);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmit = async () => {
    if (!text.trim() && files.length === 0) return;
    setError('');
    setSubmitting(true);

    try {
      let screenshotKeys: string[] = [];
      if (files.length > 0) {
        screenshotKeys = await Promise.all(files.map((f) => uploadIssueScreenshot(f)));
      }

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

  if (done) {
    return (
      <div className="report-issue-container">
        <div className="report-issue-card report-issue-done">
          <div className="report-issue-done-check">&#10003;</div>
          <h2 className="report-issue-done-title">Issue Reported</h2>
          <p className="report-issue-done-text">
            Thanks for reporting this issue! We'll look into it.
          </p>
          <button className="report-issue-submit-btn" onClick={() => navigate('/learn')}>
            Back to Home
          </button>
        </div>
      </div>
    );
  }

  const canSubmit = (text.trim() || files.length > 0) && !submitting && !recording && !transcribing;

  return (
    <div className="report-issue-container">
      <h1 className="report-issue-heading">Report an Issue</h1>
      <p className="report-issue-subtitle">
        Tell us what went wrong — type, speak, or attach screenshots.
      </p>

      {error && (
        <div className="report-issue-error">
          {error}
        </div>
      )}

      <div className="report-issue-card">
        <label className="report-issue-label">
          Describe the issue
        </label>
        <textarea
          className="report-issue-textarea"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="What happened? What were you trying to do?"
          rows={5}
          disabled={submitting}
        />

        <div className="report-issue-tools">
          <button
            className={`report-issue-tool-btn${recording ? ' report-issue-tool-btn--recording' : ''}`}
            onClick={toggleRecording}
            disabled={submitting || transcribing}
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
            className="report-issue-tool-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={submitting}
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
            className="report-issue-file-input"
          />
        </div>

        {files.length > 0 && (
          <div className="report-issue-previews">
            {files.map((f, i) => (
              <div key={i} className="report-issue-preview">
                <img
                  className="report-issue-preview-img"
                  src={URL.createObjectURL(f)}
                  alt={f.name}
                />
                <button
                  className="report-issue-preview-remove"
                  onClick={() => removeFile(i)}
                >
                  x
                </button>
              </div>
            ))}
          </div>
        )}

        <button
          className="report-issue-submit-btn"
          onClick={handleSubmit}
          disabled={!canSubmit}
        >
          {submitting ? 'Submitting...' : 'Submit Issue'}
        </button>
      </div>
    </div>
  );
}
