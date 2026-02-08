# Root Cause Analysis: Why Pattern Extension and Section F Gate Failed

## Issue #12: Pattern Extension Failure

### What Happened:
- C28 has r1-r15, r99 mapped
- C28r16-C28r23 exist in dataset but weren't found
- C20r98 and C26r14 also missed

### Why It Failed:

**Root Cause: No Systematic Search Process**

Manus' process:
1. Found C28r1-r15 and r99 by matching patterns
2. Stopped after finding initial pattern
3. Didn't actively search dataset_inventory for additional variables
4. Didn't verify completeness

**The Prompt Said:**
- "EXTEND PATTERNS: If you find sequential pattern (r1-rN, r99), check dataset inventory for..."
- "Verify variable labels match question text before including"

**But Manus Didn't:**
- Systematically search for r16, r17, r18... r23
- Verify completeness after mapping each question
- Actively look for gaps in sequential patterns

**Why:** The prompt says "check" but doesn't require a systematic search loop. Manus interpreted it as optional, not mandatory.

### Fix Applied:
Added explicit verification requirement:
- "For each multi-select question, VERIFY completeness"
- "Search dataset_inventory for ALL variables matching the pattern"
- "Check for gaps in sequential numbering"
- "If you find r1-r15 and r99, search for r16, r17, r18... up to r98"

---

## Issue #07: Section F Gate Failure

### What Happened:
- Section F has 7 questions: F01-F07
- Section gate: "SECTION ONLY SHOWN TO GEN POP"
- Only F06 and F07 got section_skip logic
- F01-F05 got NO logic at all

### Why It Failed:

**Root Cause: No Verification Step**

Manus' process:
1. Found section gate for Section F
2. Applied section_skip to some questions (F06, F07)
3. Stopped without verifying all questions got logic
4. Thought it was done: "applied to all questions in Sections C, D, E, F"

**The Prompt Said:**
- "Add skip logic to EVERY question in that section"
- "Section gates: COUNT questions in section, COUNT questions with section_skip - MUST MATCH"

**But Manus Didn't:**
- Actually count the questions
- Verify the counts matched
- Systematically process ALL questions in Section F

**Why:** The prompt says "COUNT" but doesn't require Manus to actually perform the count and fix mismatches. Manus interpreted validation as optional reporting, not mandatory verification.

### Fix Applied:
Added explicit verification requirement:
- "VERIFY section gates: For EACH section with a gate, count: questions in section vs questions with section_skip"
- "If counts don't match, you missed questions - find them and add section_skip logic"
- "Only then SAVE your result"

---

## Common Pattern: Missing Verification Steps

Both failures share the same root cause: **Manus doesn't verify completeness**.

### Pattern:
1. Prompt says "do X for all Y"
2. Manus does X for some Y
3. Prompt says "verify" but Manus doesn't actually verify
4. Manus thinks it's done
5. Validation catches the failure

### Solution:
Make verification **mandatory and explicit**:
- Not just "verify" but "VERIFY: count X, count Y, if not equal FIX IT"
- Not just "check" but "SYSTEMATICALLY SEARCH for all matching patterns"
- Require verification BEFORE saving output

---

## Why Verification Wasn't Done

**Hypothesis:**
Manus treats verification as "reporting" not "fixing". It will report what it did, but won't actively search for what it missed.

**Evidence:**
- Manus said "applied to all questions" but didn't actually apply to all
- Manus found r1-r15 but didn't search for r16-r23
- Manus didn't count to verify completeness

**Fix:**
Make verification a **mandatory step that blocks completion**:
- "BEFORE SAVING, VERIFY..."
- "If counts don't match, FIX IT"
- "Only then SAVE"

This forces Manus to actually perform the verification, not just report on it.
