# Principles: Scorecard & Progress Tracking

How we track and display student progress.

## 1. Deterministic Metrics Only

Report card shows coverage % and practice scores only. No aggregate scores, no inferred trends, no AI-generated strengths/weaknesses. If we can't compute it deterministically from data, we don't show it.

## 2. Coverage = Teach Me Only

Only teach_me sessions count toward coverage. Clarify Doubts sessions and practice attempts don't affect coverage. Coverage = how much of the study plan was worked through.

## 3. Latest Plan Is Truth

Coverage denominator = current plan version, not union of historical plans. Plan updates recalculate coverage. No "denominator drift" from accumulating old plan concepts.

## 4. Accumulate, Don't Reset

Concepts covered accumulates across multiple Teach Me sessions. Starting a new session on same topic picks up where student left off.

## 5. Practice = Latest Score + Attempt Count

Practice score display is deterministic: latest graded attempt's `total_score` / `total_possible`, plus the count of all graded attempts. No rolling averages, no "best of N", no trend lines. Latest is most informative and cheapest to compute.
