# REG-15: Direct Marketing Consent and Self-Excluded Player Suppression

> Demo policy document for the NorthPlay legal approver agent (NorthPlay is a fictional operator). Fictional rules modelled on Ontario-style internet gaming advertising standards, written for hackathon use only; not legal advice and not any regulator's official text.

- **Rule ID:** REG-15
- **Category:** Targeting & Consent
- **Source:** NorthPlay Advertising Policy (modelled on Ontario-style iGaming advertising standards), Section 2.07 and Standard 2.03 (no targeting of self-excluded or high-risk persons)
- **Severity:** blocker
- **Jurisdiction:** Ontario, Canada

## Rule
Players must actively opt in before receiving direct marketing of inducements, bonuses and credits, and must be able to withdraw consent at any time. Marketing must not target self-excluded, centrally self-excluded, underage or known high-risk persons.

## Intent
Direct marketing is the only permitted bonus channel, so consent and suppression must be airtight.

## What the reviewer checks for
- Email/SMS/push creative without an unsubscribe or opt-out mechanism
- Audience definitions that include lapsed, self-excluded or high-risk segments
- 'Win-back' campaigns aimed at players who stopped playing
- Lookalike audiences seeded from high-loss players

## Non-compliant examples
- SMS with bonus offer and no opt-out instructions
- "We miss you!" bonus campaign to players inactive after self-exclusion

## Compliant examples
- Consented email with clear unsubscribe link, audience scrubbed against self-exclusion lists

## Remediation
Add opt-out, confirm consent flags, and scrub audience against self-exclusion and high-risk lists.
