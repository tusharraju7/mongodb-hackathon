# NorthPlay Demo Data: Legal Approver Agent

Demo data for the MongoDB "Agents in Context" hackathon. **NorthPlay is a fictional Ontario sportsbook.** All people, figures and decisions are made up. The regulations are paraphrased from Ontario's AGCO Registrar's Standards for Internet Gaming for demo use only; they are not legal advice and not the official text.

## What's in here

| Folder | Contents | Load into MongoDB? | Suggested collection |
|---|---|---|---|
| `regulations/` | 15 regulation docs (REG-01 to REG-15), each as `.md` + `.pdf`, plus `regulations.json` (all 15, structured) | Yes | `policies` |
| `historical_ads/` | 15 past ads (`images/*.png`) + `historical_ads.json` with status, rationale, cited rules, required changes, extracted text | Yes | `ad_decisions` |
| `strategy_decks/` | 2 decks as `.pdf` + `.md`: 2027 Business Strategy (Oct 14, 2026) and Q1 2027 Marketing & Brand Plan (Oct 28, 2026) | Yes | `strategy_docs` |
| `slack/slack_export/` | Slack export: `users.json`, `channels.json`, and one JSON file per channel per day (#leadership, #marketing, #legal-marketing; 49 messages, Oct 1 - Nov 13, 2026) | Yes | `slack_messages` |
| `slack/NorthPlay_Slack_Transcript.md` | Human-readable version of the same Slack history | Optional (for people) | n/a |
| `demo_ads/` | The 3 ads uploaded live during the demo | **No.** Upload through the UI | n/a |
| (answer keys) | Expected demo outcomes + the 6 planted Slack decisions are deliberately **not** in this repo so the agent can never read them. Ask Alton. | n/a | n/a |

## Historical ads (15)

| ID | Status | Key rule(s) |
|---|---|---|
| NP-H01 Saturday night odds | approved | REG-14, REG-09 |
| NP-H02 Set your limits | approved | REG-06 |
| NP-H03 Marcus Doyle RG quote | approved | REG-03 (RG exception) |
| NP-H04 Parlay builder | approved | REG-09 |
| NP-H05 Opted-in bonus email | approved | REG-12, REG-13, REG-15 |
| NP-H06 $500 sign-up bonus | rejected | REG-12 |
| NP-H07 Risk-free first bet | rejected | REG-12, REG-13 |
| NP-H08 Jake Moreau "Bet with Jake" | rejected | REG-03, REG-11 |
| NP-H09 Rent due? parlay | rejected | REG-07, REG-09, REG-06 |
| NP-H10 Win it all back | rejected | REG-08, REG-06 |
| NP-H11 Lock / easy money | rejected | REG-09 |
| NP-H12 Pucky mascot + slang | rejected | REG-02, REG-01, REG-11 |
| NP-H13 Missing disclaimer | approved_with_changes | REG-14 |
| NP-H14 Turned 19? | approved_with_changes | REG-11, REG-05 |
| NP-H15 Illegible disclaimer | approved_with_changes | REG-14 |

## Context hierarchy (important for the agent)

The strategy decks are **slightly out of date**. Slack holds newer decisions that are **stricter than the regulations**. As the 2027 strategy deck states, decisions in #legal-marketing are binding and take effect immediately. The agent should treat the most recent Slack decision as overriding the decks, and internal decisions as stacking on top of AGCO rules.

## Live demo ads (3)

| File | Story |
|---|---|
| `demo_01_hockey_night_live.png` | Clean ad. Should be approved. |
| `demo_02_big_game_bonus.png` | Obvious violation. Should be rejected on regulations and Slack. |
| `demo_03_play_smart_breaks.png` | Passes the regulations and matches an approved precedent. Should be rejected **only** because of Slack context. |

Expected outcomes and reasoning are kept outside the repo (ask Alton).
