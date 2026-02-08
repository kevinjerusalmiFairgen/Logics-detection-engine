# Investigation: Issues #12 and #07

## Issue #12: 19 Unmapped Variables - Pattern Extension Failure

### Missing Variables:
1. **C20r98** - "Other" option
2. **C26r14** - "Outdoor Advertising" option  
3. **C28r16-C28r23** - 8 options (TikTok, YouTube, Snapchat, Pinterest, Reddit, BeReal, Podcasts, Emails)

### Pattern Analysis:

**C20 Pattern:**
- Has: C20r1, C20r2, C20r3, C20r4, C20r5, C20r6, C20r7, C20r8, C20r9, C20r10, C20r99
- Missing: C20r98
- **Pattern:** r1-r10, r99 → r98 should be obvious (r98 typically = "Other")

**C26 Pattern:**
- Has: C26r1-C26r13, C26r99
- Missing: C26r14
- **Pattern:** Sequential r1-r13, then r99 → r14 should be checked

**C28 Pattern:**
- Has: C28r1-C28r15, C28r99
- Missing: C28r16-C28r23 (8 variables)
- **Pattern:** Sequential r1-r15, then r99 → r16-r23 should be checked

### Root Cause:
Manus didn't extend obvious multi-select patterns. When finding r1-rN and r99, it should:
1. Check for r98 (common "Other" pattern)
2. Check for gaps in sequential numbering
3. Verify against dataset inventory for any matching variables

### Current Prompt Issue:
s3_mapping.py doesn't explicitly instruct to extend patterns. It says "map based on evidence" but doesn't say "extend obvious patterns when gaps exist".

---

## Issue #07: Section F Gate Missing Skip Logic

### Problem:
- **F01-F05:** NO skip logic at all
- **F06-F07:** Have section_skip with correct condition: `(B01r3 == 1 AND B12 >= 1500)`

### Section F Gate Analysis:

**PDF Gate Condition:**
- "SECTION ONLY SHOWN TO GEN POP (SHORT COMPLETES)"
- Condition: `B01_3 NOT SELECTED OR B12 < 1500`

**Inverted Skip Condition (for skip logic):**
- Skip Section F if NOT Gen Pop
- NOT Gen Pop = NOT(B01r3 != 1 OR B12 < 1500)
- = (B01r3 == 1 AND B12 >= 1500) ✓

**Section F Questions:**
- F01, F02, F03, F04, F05, F06, F07 (7 questions total)

**What Happened:**
- F06 and F07 got section_skip logic correctly
- F01-F05 got NO logic at all
- This violates the prompt instruction: "Add skip logic to EVERY question in that section"

### Root Cause:
Manus didn't systematically apply section gates to ALL questions. It may have:
1. Only processed some questions in Section F
2. Missed F01-F05 when expanding the gate
3. Not verified that ALL questions in the section got the skip logic

### Current Prompt Issue:
s5_logic.py says "Add skip logic to EVERY question in that section" but doesn't enforce systematic verification that all questions were processed.

---

## Proposed Fixes

### Fix #1: Pattern Extension (s3_mapping.py)

Add explicit instruction to extend obvious patterns:

```
PATTERN EXTENSION:
- When mapping multi-select questions, if you find sequential pattern (r1, r2, r3...rN, r99):
  1. Check for r98 (common "Other" pattern between rN and r99)
  2. Check dataset inventory for any variables matching the pattern with gaps
  3. Verify variable labels match the question text
  4. Extend the pattern to include all matching variables
```

### Fix #2: Section Gate Verification (s5_logic.py)

Add verification requirement:

```
After expanding section gates, VERIFY:
- Count questions in the section
- Count questions with section_skip logic
- If counts don't match, you missed some questions - fix it
- Every question in a gated section MUST have section_skip logic
```

---

## Evidence from Dataset

All missing variables exist in s2_dataset_inventory.json with matching labels:
- C20r98: "Other - From which of the following have you purchased fine jewelry"
- C26r14: "Outdoor Advertising - Which of the following people and places..."
- C28r16-C28r23: All match C28 question text pattern

These should have been found by pattern extension.
