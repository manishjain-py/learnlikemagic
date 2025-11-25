# Evaluator Agent Accuracy Improvement

## Problem Statement

**Session**: `5836b86d-90fd-4135-9d0a-d30984d4b084`

**What Happened**:
- Student task: Count letters in cricket player names (virat, rohit, hardik, jasprit, siraj)
- Student response: "virat 5, rohit 5, hardik 6, jasprit 6, siraj 5"
- **Error**: Student miscounted "jasprit" as 6 letters (correct: 7)
- **Evaluator failed**: Also counted "jasprit" as 6, gave score 1.0, marked step completed
- Student moved to next step with uncorrected misconception

**Impact**: Critical accuracy failure in basic counting task evaluation.

---

## Root Cause Analysis

### 1. **No Independent Verification Requirement**
- Evaluator prompt asks "Is it correct?" but doesn't mandate independent verification
- LLM relies on pattern matching rather than actual computation
- No instruction to "count it yourself first, then compare"

### 2. **LLM Character Counting Weakness**
- Known LLM limitation: poor at character-level operations
- Evaluator made same counting error as student (both said 6 instead of 7)
- Without explicit verification instructions, LLM approximates rather than computes

### 3. **Success Criteria Applied Prematurely**
- Evaluator applied success criteria ("count letters accurately") without verifying accuracy
- Marked step complete based on form (student provided counts) not correctness
- No check: "Did I verify each answer before accepting it?"

---

## Solution Architecture

### Workflow: How Error Correction SHOULD Work

```
┌─────────────────────────────────────────────────────────────┐
│ EXECUTOR asks: "Count letters in each name"                 │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ STUDENT responds: "virat 5, rohit 5, hardik 6, jasprit 6..." │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ EVALUATOR (IMPROVED):                                        │
│  1. Independently verifies each answer:                      │
│     - virat: v-i-r-a-t = 5 ✓                                │
│     - jasprit: j-a-s-p-r-i-t = 7 ✗ (student said 6)         │
│  2. Scores: 4/5 correct = 0.8                               │
│  3. Step status: KEEP "in_progress" (not fully correct)     │
│  4. Feedback: "Great! 4/5 correct. Let's recount jasprit"   │
│  5. Conversation updated with corrective feedback            │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ WORKFLOW routes to: EXECUTOR (step still in_progress)       │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ EXECUTOR reads:                                              │
│  - Previous conversation (sees corrective feedback)          │
│  - Step status: in_progress (success criteria not met)      │
│  - Student got jasprit wrong                                 │
│                                                              │
│ EXECUTOR generates: "Let's count jasprit together:          │
│ j-a-s-p-r-i-t. How many letters now?"                       │
└─────────────────────────────────────────────────────────────┘
                            ↓
                [Correction loop until mastery]
```

### Key Insight
**No new routing logic needed.** The existing workflow already handles corrections:
- Evaluator provides feedback → conversation updated
- Step stays in_progress → workflow routes back to EXECUTOR
- EXECUTOR sees feedback → generates corrective question

**We just need the evaluator to be ACCURATE.**

---

## Implementation Plan

### Change 1: Enhanced Evaluator Prompt
**File**: `llm-backend/agents/prompts/evaluator.txt`

**Add to SECTION 1 (Evaluate Response)**:

```
## SECTION 1: EVALUATE RESPONSE WITH PRECISION

**CRITICAL: Independently verify answers before evaluating.**

For tasks with verifiable answers (counting, arithmetic, comparisons, measurements):

1. **Verify independently**: Don't assume student is correct. Perform the task yourself.
2. **Be systematic**: Use explicit methods (e.g., count each item, show calculations)
3. **Compare results**: Your answer vs. student's answer
4. **Be precise**: Score based on actual correctness, not effort

Examples of verification:
- Counting: Count each item yourself, state your count, compare with student
- Arithmetic: Calculate the answer yourself, compare with student
- Comparisons: Determine correct answer yourself, check if student matches

**Score accurately**:
- 5/5 correct = 1.0
- 4/5 correct = 0.8 (NOT 1.0!)
- Partial understanding = partial score

**Feedback based on verification**:
- If errors found: Point them out gently, suggest rechecking specific items
- If fully correct: Praise specific achievements
- If partially correct: Acknowledge successes, guide toward fixing errors
```

### Change 2: Stricter Success Criteria Checking
**File**: `llm-backend/agents/prompts/evaluator.txt`

**Add to SECTION 2 (Update Step Status)**:

```
## SECTION 2: UPDATE STEP STATUS CAREFULLY

Before marking step as "completed":
1. **Re-read success criteria** for current step
2. **Verify student met ALL criteria** (not just attempted the task)
3. **Check your score**: If < 0.9, success criteria likely NOT met
4. **Be conservative**: When in doubt, keep in_progress for more practice

Status transitions:
- pending → in_progress: First attempt at step
- in_progress → completed: Success criteria FULLY met (high score, demonstrated mastery)
- in_progress → in_progress: Making progress but not mastery yet (COMMON for learning)
- in_progress → blocked: No progress after 3+ attempts, fundamental gap

**Remember**: Keeping step in_progress is GOOD. It means EXECUTOR will:
- See your corrective feedback
- Generate follow-up question
- Help student achieve mastery

Don't rush to "completed" - let students learn through iteration.
```

### Change 3: Add Verification Reminder to Guidelines
**File**: `llm-backend/agents/prompts/evaluator.txt`

**Add to IMPORTANT GUIDELINES section**:

```
8. **Independent Verification**: For computational/factual tasks, verify answers yourself before scoring
9. **Precision in Scoring**: 4/5 correct is 0.8, not 1.0. Be mathematically accurate.
10. **Success Criteria Rigor**: Re-read criteria before marking completed. When uncertain, keep in_progress.
```

---

## Expected Outcomes

### Before Fix (Current Behavior)
```
Student: "jasprit 6" (wrong)
Evaluator: "Correct! jasprit has 6 letters" (also wrong)
Score: 1.0
Status: completed
Result: Student moves on with misconception
```

### After Fix (Expected Behavior)
```
Student: "jasprit 6" (wrong)
Evaluator: [Counts: j-a-s-p-r-i-t = 7]
          "You got 4/5! Let's recount jasprit together"
Score: 0.8
Status: in_progress
Result: EXECUTOR generates corrective question
        Student practices until mastery
        Step completed only when truly correct
```

### Success Metrics
1. **Accuracy**: Evaluator catches counting/arithmetic errors student makes
2. **Precision**: Scores reflect actual correctness (4/5 = 0.8, not 1.0)
3. **Pedagogical**: Students get corrective feedback and practice before moving on
4. **No false positives**: Steps marked complete only when criteria truly met

---

## Testing Strategy

### Test Case 1: Original Failing Scenario
- **Input**: Student counts "jasprit" as 6 letters
- **Expected**: Evaluator detects error, provides feedback, keeps step in_progress
- **Verify**: Check logs show evaluator counted 7 letters independently

### Test Case 2: Partial Correctness
- **Input**: Student gets 3/5 counting tasks correct
- **Expected**: Score = 0.6, feedback identifies 2 errors, step stays in_progress
- **Verify**: EXECUTOR generates follow-up question addressing the 2 errors

### Test Case 3: Full Correctness
- **Input**: Student gets all 5/5 correct
- **Expected**: Score = 1.0, step marked completed
- **Verify**: Workflow moves to next step

### Test Case 4: Arithmetic Task
- **Input**: Student says "3/8 + 2/8 = 6/16"
- **Expected**: Evaluator calculates 5/8, detects error, score < 0.3
- **Verify**: Feedback explains correct addition of fractions

---

## Implementation Checklist

- [ ] Update `evaluator.txt` SECTION 1 with verification requirements
- [ ] Update `evaluator.txt` SECTION 2 with stricter completion criteria
- [ ] Add verification guidelines to IMPORTANT GUIDELINES section
- [ ] Test with original failing session scenario
- [ ] Test with arithmetic tasks (fractions, addition, etc.)
- [ ] Test with comparison tasks (longest/shortest)
- [ ] Monitor next 10 tutoring sessions for evaluation accuracy
- [ ] Document any edge cases discovered

---

## Notes

- **No code changes needed** - this is purely a prompt engineering fix
- **Workflow already handles corrections** - we just need accurate evaluation
- **Conservative approach**: Better to keep step in_progress and iterate than mark complete prematurely
- **LLM weakness mitigation**: Explicit verification instructions compensate for character-counting limitations
