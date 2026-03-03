/**
 * EnrichmentPage — 9-section enrichment form + personality card.
 * Parents fill this to help personalize the tutoring experience.
 */

import React, { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import {
  getEnrichmentProfile,
  updateEnrichmentProfile,
  getPersonality,
  regeneratePersonality,
  EnrichmentProfileResponse,
  PersonalityApiResponse,
  MyWorldEntry,
  PersonalityTrait,
} from '../api';
import SectionCard from '../components/enrichment/SectionCard';
import ChipSelector from '../components/enrichment/ChipSelector';
import PeopleEditor from '../components/enrichment/PeopleEditor';
import PersonalitySliders from '../components/enrichment/PersonalitySliders';
import FavoritesSection from '../components/enrichment/FavoritesSection';
import SessionPreferences from '../components/enrichment/SessionPreferences';

// Predefined options for each chip section
const INTEREST_OPTIONS = [
  'Cricket', 'Football', 'Basketball', 'Drawing', 'Painting', 'Reading',
  'Gaming', 'Music', 'Dance', 'Cooking', 'Science experiments', 'Animals/Pets',
  'Cycling', 'Swimming', 'Puzzles', 'Building/Lego', 'Watching cartoons/movies',
  'Crafts', 'Photography', 'Coding',
];

const LEARNING_STYLE_OPTIONS = [
  { label: 'Seeing pictures, diagrams, and visuals', value: 'visual' },
  { label: 'Step-by-step explanations', value: 'structured' },
  { label: 'Trying things and figuring it out', value: 'exploratory' },
  { label: 'Connecting to real life examples', value: 'contextual' },
  { label: 'Stories and narratives', value: 'narrative' },
  { label: 'Hands-on activities and doing', value: 'kinesthetic' },
];

const MOTIVATION_OPTIONS = [
  { label: 'Loves challenges and competing', value: 'challenge' },
  { label: 'Lights up with praise and encouragement', value: 'praise' },
  { label: 'Wants to know why this matters in real life', value: 'relevance' },
  { label: 'Enjoys creating and being imaginative', value: 'creative' },
  { label: 'Likes earning rewards and achievements', value: 'achievement' },
  { label: 'Loves helping and teaching others', value: 'social' },
];

const STRENGTH_OPTIONS = [
  'Quick thinker', 'Creative', 'Great memory', 'Good with numbers',
  'Strong reader', 'Problem solver', 'Storyteller', 'Artistic',
  'Curious', 'Patient', 'Good listener', 'Detail-oriented',
];

const GROWTH_OPTIONS = [
  'Staying focused for long', 'Showing work/steps', 'Word problems',
  'Memorizing facts', 'Writing answers', 'Reading comprehension',
  'Speed/time pressure', 'Math calculations', 'Understanding abstract concepts',
  'Getting started on tasks',
];

// Helper: for sections with label/value pairs, show labels but store values
function LabeledChipSelector({
  options,
  selected,
  onChange,
}: {
  options: { label: string; value: string }[];
  selected: string[];
  onChange: (selected: string[]) => void;
}) {
  return (
    <div className="enrichment-chips">
      {options.map((opt) => (
        <button
          key={opt.value}
          type="button"
          className={`enrichment-chip ${selected.includes(opt.value) ? 'enrichment-chip-selected' : ''}`}
          onClick={() => {
            if (selected.includes(opt.value)) {
              onChange(selected.filter((s) => s !== opt.value));
            } else {
              onChange([...selected, opt.value]);
            }
          }}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}

export default function EnrichmentPage() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const kidName = user?.preferred_name || user?.name || 'your child';

  // Form state
  const [interests, setInterests] = useState<string[]>([]);
  const [myWorld, setMyWorld] = useState<MyWorldEntry[]>([]);
  const [learningStyles, setLearningStyles] = useState<string[]>([]);
  const [motivations, setMotivations] = useState<string[]>([]);
  const [strengths, setStrengths] = useState<string[]>([]);
  const [growthAreas, setGrowthAreas] = useState<string[]>([]);
  const [personalityTraits, setPersonalityTraits] = useState<PersonalityTrait[]>([]);
  const [favoriteMedia, setFavoriteMedia] = useState<string[]>([]);
  const [favoriteCharacters, setFavoriteCharacters] = useState<string[]>([]);
  const [memorableExperience, setMemorableExperience] = useState('');
  const [aspiration, setAspiration] = useState('');
  const [parentNotes, setParentNotes] = useState('');
  const [attentionSpan, setAttentionSpan] = useState('');
  const [pacePreference, setPacePreference] = useState('');

  // UI state
  const [openSection, setOpenSection] = useState<number | null>(null);
  const [sectionsFilledCount, setSectionsFilledCount] = useState(0);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState('');
  const [loading, setLoading] = useState(true);
  const [hasAboutMe, setHasAboutMe] = useState(false);
  const [personality, setPersonality] = useState<PersonalityApiResponse | null>(null);
  const [regenerating, setRegenerating] = useState(false);

  // Load profile on mount
  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      const profile = await getEnrichmentProfile();
      setInterests(profile.interests || []);
      setMyWorld(profile.my_world || []);
      setLearningStyles(profile.learning_styles || []);
      setMotivations(profile.motivations || []);
      setStrengths(profile.strengths || []);
      setGrowthAreas(profile.growth_areas || []);
      setPersonalityTraits(profile.personality_traits || []);
      setFavoriteMedia(profile.favorite_media || []);
      setFavoriteCharacters(profile.favorite_characters || []);
      setMemorableExperience(profile.memorable_experience || '');
      setAspiration(profile.aspiration || '');
      setParentNotes(profile.parent_notes || '');
      setAttentionSpan(profile.attention_span || '');
      setPacePreference(profile.pace_preference || '');
      setSectionsFilledCount(profile.sections_filled);
      setHasAboutMe(profile.has_about_me);

      // Load personality
      try {
        const p = await getPersonality();
        setPersonality(p);
      } catch {
        // Personality endpoint may not exist yet (Phase 2)
      }
    } catch (err) {
      console.error('Failed to load enrichment profile:', err);
    } finally {
      setLoading(false);
    }
  };

  // Auto-save when a section is closed
  const saveSection = useCallback(async (fields: Record<string, any>) => {
    setSaving(true);
    setSaveMsg('');
    try {
      const result = await updateEnrichmentProfile(fields);
      setSectionsFilledCount(result.sections_filled);
      setSaveMsg('Saved!');
      setTimeout(() => setSaveMsg(''), 2000);
    } catch (err) {
      setSaveMsg('Failed to save');
    } finally {
      setSaving(false);
    }
  }, []);

  const handleSectionToggle = (sectionIndex: number) => {
    // If closing a section, save its data
    if (openSection === sectionIndex) {
      saveSectionData(sectionIndex);
      setOpenSection(null);
    } else {
      // Save previous section if one was open
      if (openSection !== null) {
        saveSectionData(openSection);
      }
      setOpenSection(sectionIndex);
    }
  };

  const saveSectionData = (sectionIndex: number) => {
    const fieldMap: Record<number, Record<string, any>> = {
      0: { interests },
      1: { my_world: myWorld.filter((e) => e.name.trim()) },
      2: { learning_styles: learningStyles },
      3: { motivations },
      4: { strengths },
      5: { growth_areas: growthAreas },
      6: { personality_traits: personalityTraits },
      7: {
        favorite_media: favoriteMedia,
        favorite_characters: favoriteCharacters,
        memorable_experience: memorableExperience || undefined,
        aspiration: aspiration || undefined,
      },
      8: { parent_notes: parentNotes || undefined },
      9: {
        attention_span: attentionSpan || undefined,
        pace_preference: pacePreference || undefined,
      },
    };
    const fields = fieldMap[sectionIndex];
    if (fields) {
      saveSection(fields);
    }
  };

  // Migration: copy about_me into parent_notes and persist immediately
  const handleMigrateAboutMe = async () => {
    if (user?.about_me) {
      setParentNotes(user.about_me);
      setHasAboutMe(false);
      setOpenSection(8); // Open Parent's Notes section
      // Persist immediately so data isn't lost if user navigates away
      try {
        const result = await updateEnrichmentProfile({ parent_notes: user.about_me });
        setSectionsFilledCount(result.sections_filled);
      } catch (err) {
        console.error('Failed to migrate about_me:', err);
      }
    }
  };

  const handleRetryPersonality = async () => {
    setRegenerating(true);
    try {
      await regeneratePersonality();
      setPersonality({ status: 'generating' });
    } catch (err) {
      console.error('Failed to regenerate personality:', err);
    } finally {
      setRegenerating(false);
    }
  };

  // Check if a section has data
  const isSectionFilled = (index: number): boolean => {
    switch (index) {
      case 0: return interests.length > 0;
      case 1: return myWorld.some((e) => e.name.trim());
      case 2: return learningStyles.length > 0;
      case 3: return motivations.length > 0;
      case 4: return strengths.length > 0;
      case 5: return growthAreas.length > 0;
      case 6: return personalityTraits.length > 0;
      case 7: return favoriteMedia.length > 0 || favoriteCharacters.length > 0 || !!memorableExperience || !!aspiration;
      case 8: return !!parentNotes;
      default: return false;
    }
  };

  if (loading) {
    return (
      <div className="auth-page">
        <div className="auth-container" style={{ textAlign: 'center', padding: '3rem' }}>
          Loading...
        </div>
      </div>
    );
  }

  const sections = [
    { title: `What does ${kidName} enjoy doing?`, helper: "We'll use these interests to make examples and stories relatable." },
    { title: `${kidName}'s world`, helper: "Tell us about important people in their life \u2014 we'll use their names in examples and stories." },
    { title: `How ${kidName} learns best`, helper: 'Every child learns differently. What works best?' },
    { title: `What motivates ${kidName}`, helper: "What makes their eyes light up when learning?" },
    { title: `${kidName}'s superpowers`, helper: 'What comes naturally? What are they proud of?' },
    { title: 'Areas to grow', helper: 'What do they find challenging? No judgment \u2014 this helps us focus our support.' },
    { title: `${kidName}'s personality`, helper: "Help us match our teaching style to their temperament." },
    { title: 'Favorites & fun facts', helper: "The fun stuff! These help us make learning feel personal." },
    { title: "Parent's notes", helper: 'Anything else we should know? Tips from the expert \u2014 you!' },
  ];

  return (
    <div className="auth-page">
      <div className="auth-container enrichment-page">
        <div className="profile-header">
          <button className="auth-back-btn" onClick={() => navigate('/profile')}>
            &larr; Back to Profile
          </button>
          <h2 className="auth-title">Help us know {kidName} better</h2>
          <p className="auth-subtitle">
            The more we know, the more personalized the learning experience.
            Fill in any sections you'd like &mdash; all optional!
          </p>
        </div>

        {/* Progress indicator */}
        <div className="enrichment-progress">
          <div className="enrichment-progress-bar">
            <div
              className="enrichment-progress-fill"
              style={{ width: `${(sectionsFilledCount / 9) * 100}%` }}
            />
          </div>
          <span className="enrichment-progress-text">{sectionsFilledCount} of 9 sections filled</span>
        </div>

        {/* Save status */}
        {(saving || saveMsg) && (
          <div className={`enrichment-save-status ${saveMsg === 'Saved!' ? 'enrichment-save-success' : ''}`}>
            {saving ? 'Saving...' : saveMsg}
          </div>
        )}

        {/* Migration banner */}
        {hasAboutMe && (
          <div className="enrichment-migration-banner">
            <p>We found your earlier note about {kidName}. Want to use it as a starting point?</p>
            <button className="auth-btn auth-btn-outline" onClick={handleMigrateAboutMe}>
              Use it in Parent's Notes
            </button>
          </div>
        )}

        {/* 9 Sections */}
        {sections.map((section, index) => (
          <SectionCard
            key={index}
            title={section.title}
            helper={section.helper}
            isFilled={isSectionFilled(index)}
            isOpen={openSection === index}
            onToggle={() => handleSectionToggle(index)}
          >
            {index === 0 && (
              <ChipSelector options={INTEREST_OPTIONS} selected={interests} onChange={setInterests} allowCustom />
            )}
            {index === 1 && (
              <PeopleEditor entries={myWorld} onChange={setMyWorld} />
            )}
            {index === 2 && (
              <LabeledChipSelector options={LEARNING_STYLE_OPTIONS} selected={learningStyles} onChange={setLearningStyles} />
            )}
            {index === 3 && (
              <LabeledChipSelector options={MOTIVATION_OPTIONS} selected={motivations} onChange={setMotivations} />
            )}
            {index === 4 && (
              <ChipSelector options={STRENGTH_OPTIONS} selected={strengths} onChange={setStrengths} allowCustom />
            )}
            {index === 5 && (
              <ChipSelector options={GROWTH_OPTIONS} selected={growthAreas} onChange={setGrowthAreas} allowCustom />
            )}
            {index === 6 && (
              <PersonalitySliders traits={personalityTraits} onChange={setPersonalityTraits} />
            )}
            {index === 7 && (
              <FavoritesSection
                favoriteMedia={favoriteMedia}
                favoriteCharacters={favoriteCharacters}
                memorableExperience={memorableExperience}
                aspiration={aspiration}
                onChange={(field, value) => {
                  if (field === 'favorite_media') setFavoriteMedia(value);
                  else if (field === 'favorite_characters') setFavoriteCharacters(value);
                  else if (field === 'memorable_experience') setMemorableExperience(value);
                  else if (field === 'aspiration') setAspiration(value);
                }}
              />
            )}
            {index === 8 && (
              <div className="auth-field">
                <textarea
                  value={parentNotes}
                  onChange={(e) => setParentNotes(e.target.value)}
                  placeholder="E.g., 'She learns faster in the morning', 'He gets anxious during tests', 'She loves it when you relate things to cooking'..."
                  maxLength={1000}
                  rows={4}
                />
                <span className="enrichment-char-count">{parentNotes.length}/1000</span>
              </div>
            )}
          </SectionCard>
        ))}

        {/* Session Preferences */}
        <div className="enrichment-session-section">
          <h3 className="enrichment-session-title">Session Preferences</h3>
          <SessionPreferences
            attentionSpan={attentionSpan}
            pacePreference={pacePreference}
            onChange={(field, value) => {
              if (field === 'attention_span') setAttentionSpan(value);
              else if (field === 'pace_preference') setPacePreference(value);
              // Auto-save session preferences immediately
              saveSection({ [field]: value });
            }}
          />
        </div>

        {/* Personality Card placeholder (Phase 2) */}
        {personality && personality.status === 'ready' && personality.personality_json && (
          <div className="enrichment-personality-card">
            <h3>Here's what we understand about {kidName}</h3>
            <div className="enrichment-personality-content">
              {personality.personality_json.teaching_approach && (
                <div className="enrichment-personality-field">
                  <strong>How we'll teach</strong>
                  <p>{personality.personality_json.teaching_approach}</p>
                </div>
              )}
              {personality.personality_json.example_themes && (
                <div className="enrichment-personality-field">
                  <strong>Examples we'll use</strong>
                  <p>{(personality.personality_json.example_themes as string[]).join(', ')}</p>
                </div>
              )}
              {personality.personality_json.encouragement_strategy && (
                <div className="enrichment-personality-field">
                  <strong>What motivates {kidName}</strong>
                  <p>{personality.personality_json.encouragement_strategy}</p>
                </div>
              )}
              {personality.personality_json.growth_focus && (
                <div className="enrichment-personality-field">
                  <strong>What we'll focus on</strong>
                  <p>{personality.personality_json.growth_focus}</p>
                </div>
              )}
            </div>
            {personality.updated_at && (
              <p className="enrichment-personality-updated">
                Last updated: {new Date(personality.updated_at).toLocaleDateString()}
              </p>
            )}
          </div>
        )}
        {personality && personality.status === 'generating' && (
          <div className="enrichment-personality-card enrichment-personality-generating">
            <h3>Creating {kidName}'s learning profile...</h3>
            <p>This takes a few seconds. Refresh to see the result.</p>
          </div>
        )}
        {personality && personality.status === 'failed' && (
          <div className="enrichment-personality-card enrichment-personality-failed">
            <h3>We couldn't generate the profile</h3>
            <p>Something went wrong. Please try again.</p>
            <button
              className="auth-btn auth-btn-primary"
              onClick={handleRetryPersonality}
              disabled={regenerating}
            >
              {regenerating ? 'Retrying...' : 'Try again'}
            </button>
          </div>
        )}
        {(!personality || personality.status === 'none') && sectionsFilledCount === 0 && (
          <div className="enrichment-personality-card enrichment-personality-empty">
            <p>Fill in a few sections above and we'll create a personalized learning profile for {kidName}!</p>
          </div>
        )}
        {(!personality || personality.status === 'none') && sectionsFilledCount > 0 && (
          <div className="enrichment-personality-card enrichment-personality-generating">
            <h3>Almost there!</h3>
            <p>Save a section to generate {kidName}'s personalized learning profile.</p>
          </div>
        )}
      </div>
    </div>
  );
}
