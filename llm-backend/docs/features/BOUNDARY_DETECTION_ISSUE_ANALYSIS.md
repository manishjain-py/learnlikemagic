# Boundary Detection Issue: Over-Segmentation Analysis

**Date**: 2025-10-31
**Issue**: Guideline generation creating too many granular subtopics
**Status**: 🔍 Under Investigation

---

## 📊 Observed Behavior

### Test Case: Grade 3 Math Textbook (8 pages)

**Generation Results:**
```
Pages processed: 8
Subtopics created: 8
Subtopics finalized: 0
```

**Subtopics Created:**
1. **Counting Cows with Tally Marks** (Page 1)
2. **Animal Name Lengths** (Page 3)
3. **Number Names and Letter Counts** (Page 5)
4. **Categorizing Household Items** (Page 7)
5. **Categorizing Hair Styles** (Page 8)

### 🚨 Problem Identified

The subtopics are **NOT cohesive**:
- "Categorizing" should be **ONE subtopic**, not two separate ones
- Other activities (tally marks, animal names, number names) are just **different teaching examples**, not independent subtopics
- Expected: **1-2 subtopics** (e.g., "Data Handling", "Organizing Information")
- Actual: **5 subtopics** (one per activity/page)

---

## 🔍 Root Cause Analysis

### 1. Current Boundary Detection Logic

**Location**: `/llm-backend/features/book_ingestion/services/boundary_detection_service.py`

**Thresholds:**
```python
CONTINUE_THRESHOLD = 0.6   # 60% confidence to continue current subtopic
NEW_THRESHOLD = 0.75       # 75% confidence to start new subtopic
```

**Hysteresis Logic:**
- Strong continue: `continue_score ≥ 0.6` AND `new_score < 0.7` → **CONTINUE**
- Strong new: `new_score ≥ 0.75` → **NEW**
- Ambiguous zone (0.6-0.75): Use best guess, mark as low confidence

**Decision Flow:**
```
Page 1 → No previous subtopic → NEW ("Counting Cows with Tally Marks")
Page 2 → Skip (only 1, 3, 5, 7, 8 shown)
Page 3 → Different activity → NEW ("Animal Name Lengths")
Page 5 → Different activity → NEW ("Number Names and Letter Counts")
Page 7 → Different activity → NEW ("Categorizing Household Items")
Page 8 → Similar to Page 7 but different example → NEW ("Categorizing Hair Styles")
```

### 2. Why Is This Happening?

#### Issue #1: Activity-Level Granularity
The LLM is treating each **activity** as a separate subtopic:
- Page 1: Activity = "Count cows using tally marks" → Subtopic = "Counting Cows with Tally Marks"
- Page 3: Activity = "Measure animal name lengths" → Subtopic = "Animal Name Lengths"
- Page 7: Activity = "Categorize household items" → Subtopic = "Categorizing Household Items"

**What it should do:**
- Recognize these are all **examples** of a broader concept: "Data Handling" or "Organizing Information"
- Create ONE subtopic: "Data Handling and Organization"
- Store activities as **examples** within that subtopic

#### Issue #2: Lack of Pedagogical Context
The boundary detection prompt doesn't provide:
- Grade-level curriculum structure
- Common topic patterns for Grade 3 Math
- Understanding that multiple activities can teach the same concept

**Current prompt guidance:**
```
GUIDELINES:
- Practice problems usually CONTINUE the current subtopic
- Headers like "Chapter X" or "Section Y" usually indicate NEW subtopic
- Gradual topic drift = CONTINUE (don't split on minor variations)
- Clear conceptual shift = NEW
```

**Missing guidance:**
- Multiple activities for the same concept = CONTINUE (or same subtopic)
- Different examples/exercises teaching the same skill = CONTINUE
- Look for conceptual similarity, not activity similarity

#### Issue #3: No Higher-Level Topic Understanding
The system processes **page-by-page** without understanding the **chapter/unit structure**:
- No awareness that pages 1-8 might all belong to "Chapter 1: Data Handling"
- No context about typical Grade 3 Math curriculum topics
- Can't recognize that tally marks, categorizing, and counting are all **data handling skills**

### 3. Current Prompt Analysis

**File**: `/llm-backend/features/book_ingestion/prompts/boundary_detection.txt`

**What the prompt does well:**
✅ Provides context (grade, subject, recent pages)
✅ Shows open subtopics
✅ Asks for confidence scores
✅ Mentions practice problems should CONTINUE

**What's missing:**
❌ No curriculum/pedagogical guidance
❌ No concept of "different activities, same learning objective"
❌ No understanding of topic hierarchy (topic → subtopic → examples)
❌ No semantic similarity check for activities

---

## 🎯 Impact Assessment

### Severity: **HIGH** 🔴

**Why this matters:**
1. **Poor User Experience**: Teachers see 8 subtopics instead of 1-2, making navigation confusing
2. **Redundant Guidelines**: Multiple subtopics covering the same concept waste storage and processing
3. **Inconsistent Structure**: Different books will have wildly different granularity
4. **Description Field Impact**: The new comprehensive description field we added will be fragmented across many subtopics instead of consolidated

### Affected Users:
- Teachers trying to navigate guidelines
- Curriculum designers reviewing book structure
- Students using the tutor (fragmented learning paths)

---

## 💡 Proposed Solutions

### Solution 1: **Enhance Boundary Detection Prompt** (Quick Fix)
**Effort**: 30 minutes
**Impact**: Medium

**Changes to `boundary_detection.txt`:**
```
ENHANCED GUIDELINES:
- Multiple activities teaching the SAME CONCEPT = CONTINUE (e.g., different categorizing exercises)
- Different examples with same learning objective = CONTINUE
- Look for CONCEPTUAL similarity, not activity similarity
- For Grade {grade} {subject}, consider typical curriculum topics:
  - Grade 3 Math: Data Handling, Number Operations, Geometry, Measurement
  - Activities like tally marks, categorizing, organizing = ALL Data Handling
- Only start NEW subtopic when learning objective changes significantly
```

**Testing**: Regenerate guidelines for test book, expect 1-2 subtopics instead of 5

---

### Solution 2: **Adjust Hysteresis Thresholds** (Quick Fix)
**Effort**: 15 minutes
**Impact**: Low-Medium

**Current:**
```python
CONTINUE_THRESHOLD = 0.6   # Too low?
NEW_THRESHOLD = 0.75       # Good
```

**Proposed:**
```python
CONTINUE_THRESHOLD = 0.5   # Lower threshold = easier to continue
NEW_THRESHOLD = 0.80       # Higher threshold = harder to start new
```

**Risk**: May cause under-segmentation (topics that should be separate get merged)

---

### Solution 3: **Add Curriculum Context Service** (Medium-term)
**Effort**: 4-6 hours
**Impact**: High

**Create**: `CurriculumContextService`

**Features:**
1. Load curriculum structure for grade/subject/board
2. Provide topic hierarchy to boundary detector:
   ```json
   {
     "grade": 3,
     "subject": "Mathematics",
     "topics": [
       {
         "topic": "Data Handling",
         "subtopics": [
           "Organizing Data",
           "Tally Marks and Tables",
           "Categorizing Objects"
         ]
       },
       {
         "topic": "Number Operations",
         "subtopics": ["Addition", "Subtraction", "Multiplication"]
       }
     ]
   }
   ```

3. Boundary detector checks: "Does this page fit an existing subtopic in the curriculum?"
4. Reduces reliance on LLM judgment, uses structured curriculum knowledge

---

### Solution 4: **Post-Processing: Merge Over-Segmented Subtopics** (Long-term)
**Effort**: 6-8 hours
**Impact**: High

**Create**: `SubtopicMergeService`

**Process:**
1. After guideline generation completes
2. Analyze all subtopics for semantic similarity:
   - Use embeddings (OpenAI embeddings API)
   - Compare subtopic titles, objectives, examples
   - Calculate similarity scores
3. Merge subtopics with high similarity (>0.85)
4. Consolidate objectives, examples, assessments
5. Regenerate description for merged subtopic

**Benefits:**
- Works retroactively on existing guidelines
- Catches edge cases that prompt engineering misses
- Allows manual override (user can approve/reject merges)

---

### Solution 5: **Two-Pass Boundary Detection** (Advanced)
**Effort**: 8-10 hours
**Impact**: Very High

**Approach:**
1. **Pass 1 (Current)**: Page-by-page boundary detection (fast, real-time)
2. **Pass 2 (Post-processing)**: After all pages processed:
   - Analyze entire book structure
   - Identify topic hierarchy
   - Re-segment if needed based on global context
   - Merge over-segmented, split under-segmented

**Benefits:**
- Combines speed of page-by-page with accuracy of global analysis
- Can handle books with non-linear structure (review chapters, mixed topics)

---

## 🎬 Recommended Action Plan

### Phase 1: Immediate (Today) ✅
**Solution 1**: Enhance boundary detection prompt
- Add pedagogical guidance
- Emphasize conceptual similarity over activity similarity
- Test with sample book

### Phase 2: Short-term (This Week) 🔄
**Solution 3 (Simplified)**: Add basic curriculum hints
- Create simple topic mappings for common grades/subjects
- Grade 3 Math → ["Data Handling", "Numbers", "Geometry", "Measurement"]
- Pass as context to boundary detector

### Phase 3: Medium-term (Next 2 Weeks) 📅
**Solution 4**: Implement subtopic merge service
- Detect and merge over-segmented subtopics
- Manual review UI for approve/reject merges
- Regenerate consolidated descriptions

### Phase 4: Long-term (Next Month) 🚀
**Solution 5**: Two-pass boundary detection
- Full implementation with global analysis
- A/B test against current approach
- Roll out to production

---

## 📝 Test Plan

### Test Case 1: Grade 3 Math (Current Issue)
**Book**: 8-page sample with data handling activities
**Expected**: 1-2 subtopics
**Current**: 5 subtopics
**Target**: Reduce to 1-2 after Solution 1

### Test Case 2: Grade 5 Science
**Book**: 20-page chapter on "Matter and Materials"
**Expected**: 2-3 subtopics (States of Matter, Properties, Changes)
**Current**: Unknown (needs testing)
**Target**: Verify no over-segmentation

### Test Case 3: Legitimate Subtopic Boundaries
**Book**: Chapter with multiple distinct topics
**Expected**: Correctly identify boundaries
**Target**: Ensure fixes don't cause under-segmentation

---

## 🔬 Metrics to Track

1. **Subtopics per Page Ratio**:
   - Current: ~0.62 (5 subtopics / 8 pages)
   - Target: ~0.10-0.20 (1-2 subtopics / 10 pages)

2. **Boundary Decision Distribution**:
   - Current: 62% NEW, 38% CONTINUE
   - Target: 20% NEW, 80% CONTINUE (for typical textbook)

3. **User Feedback**:
   - Survey: "Are the subtopics appropriately granular?"
   - Rating: 1-5 scale

---

## 📚 References

- **Current Implementation**: `/llm-backend/features/book_ingestion/services/boundary_detection_service.py`
- **Prompt Template**: `/llm-backend/features/book_ingestion/prompts/boundary_detection.txt`
- **Related Issue**: Description field implementation (just completed)
- **PRD Section**: Phase 6 - Guideline Extraction Architecture

---

## 🏁 Implementation Progress

### ✅ Completed
1. ✅ **Document issue** (this file) - 2025-10-31
2. ✅ **Implement Solution 1** (enhance prompt) - 2025-10-31
   - Enhanced boundary_detection.txt with pedagogical principles
   - Added explicit guidance for continuation vs. new subtopic
   - Added common grade-level topics reference
   - Emphasized CONCEPTUAL similarity over surface-level changes
   - Added bias towards continuation

### 🔄 Changes Made to Prompt

**File**: `/llm-backend/features/book_ingestion/prompts/boundary_detection.txt`

**Key Additions:**
```
IMPORTANT - PEDAGOGICAL PRINCIPLES:
A subtopic represents a LEARNING OBJECTIVE, not individual activities or examples.
Multiple activities can teach the SAME learning objective.

GUIDELINES FOR CONTINUATION (favor CONTINUE over NEW):
1. Same Learning Objective - different examples → CONTINUE
2. Different Activities, Same Skill → CONTINUE
3. Common Grade-Level Topics awareness
4. Look for CONCEPTUAL similarity

BIAS TOWARDS CONTINUATION:
- When in doubt, CONTINUE rather than create NEW
- Subtopics should be BROADER, not narrower
- Target: 10-20 pages per subtopic (not 1-2 pages)
```

**Specific Examples Added:**
- "Categorizing household items" + "Categorizing hairstyles" = SAME CONCEPT → CONTINUE
- "Tally marks for cows" + "Tally marks for books" = SAME SKILL → CONTINUE
- All data handling activities (tally marks, tables, categorizing) = ONE SUBTOPIC

### ⏳ Next Steps
3. 🔄 **Test with sample book** (in progress - ready for user to regenerate)
4. ⏳ **Measure improvement**
5. ⏳ **If needed, proceed to Solution 3**

---

## 🧪 Testing Instructions

**To test the improved boundary detection:**

1. Navigate to the book: `ncert_mathematics_3_2024`
2. **Delete existing guidelines** (Reject & Delete button)
3. **Regenerate guidelines** (Generate Guidelines button)
4. **Expected Results:**
   - Before: 5 subtopics (8 pages)
   - After: 1-2 subtopics (8 pages)
   - "Categorizing" activities should be merged into one subtopic
   - All data handling activities grouped together

5. **Metrics to Check:**
   - Subtopics created: Should be 1-2 (was 5)
   - Pages per subtopic: Should be 4-8 (was 1-2)
   - Subtopic names: Should be broader (e.g., "Data Handling" not "Counting Cows")

---

**Status**: Solution 1 implemented, ready for testing
**Owner**: Implementation team
**Priority**: High
**Date**: 2025-10-31
