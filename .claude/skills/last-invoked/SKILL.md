---
name: last-invoked
description: Reports how long ago this skill was last invoked. Use when the user asks "when did I last invoke this skill" or "how long since I last used this skill".
allowed-tools: Bash(date *), Bash(cat *), Bash(echo *)
---

Current unix timestamp: !`date +%s`
Last invoked timestamp: !`cat "${CLAUDE_SKILL_DIR}/last_invoked.txt" 2>/dev/null || echo "never"`

Steps:
1. If last invoked is "never", tell the user this is the first time the skill has been invoked.
2. Otherwise, calculate the difference between the current timestamp and the last invoked timestamp, and format it in a human-readable way (e.g., "3 days, 2 hours, 15 minutes ago").
3. Save the current timestamp by running: `date +%s > "${CLAUDE_SKILL_DIR}/last_invoked.txt"`
4. Confirm to the user that the invocation time has been recorded.
