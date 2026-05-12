---
name: failure-as-lessons
description: User wants every test failure analyzed for root cause, generalized into fixes or improvements, not just retried
type: feedback
---

Every failure in stress testing or E2E testing should be treated as a learning opportunity:

1. Identify the root cause (not just the symptom)
2. Generalize: does this failure pattern affect other parts of the system?
3. Either fix the bug, improve the feature, or document it
4. Store the lesson so it's not repeated

Examples of applying this:
- "pick not available" failures led to adding unavailable_reason diagnostics (game_started, line_moved, market_unavailable, no_data)
- Games at top of list always failing led to reverse-order strategy (try future games first)
- 502 errors from validators led to identifying slow UIDs (0, 201) and dead ones (86)
- Imminent games getting filtered out was wrong because that's peak volume time
