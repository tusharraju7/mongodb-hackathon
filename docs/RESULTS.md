# Review results against the expected outcomes

Generated 2026-11-14 19:47 UTC by `python -m scripts.dry_run --suite --report`. Prompt version `2026-11-14.3`; verdict model `anthropic:claude-opus-5-5` at effort `low`; fast model `anthropic:claude-haiku-5-5`.

## Where the expected results come from

- **15 past ads.** `northplay-demo-data/historical_ads/historical_ads.json` records, for each, the decision that was made and the rules it cited. That record is the expected result.
- **3 demo ads.** The data set's README states what each should come out as. The detailed answer keys are held outside the repo.

Each past ad is reviewed without the memory of its own decision, so the result is not simply read back. Slack decisions made after an ad was decided are in view, so an ad can correctly come back stricter today than it was decided then.

## The three demo ads

Submitted for the channel "Instagram (paid social)", which is an assumption: the channel is chosen at upload.

| Ad | Expected | Agent | Match | Regulations cited | Slack decisions cited | Without memory | Confidence | Time |
|---|---|---|---|---|---|---|---|---|
| `demo_01_hockey_night_live.png` | approved | approved | yes | none | none | approved | 80 | 12 s |
| `demo_02_big_game_bonus.png` | rejected | rejected | yes | REG-06, REG-12, REG-13 | #legal-marketing-2026-11-04 | rejected | 76 | 18 s |
| `demo_03_play_smart_breaks.png` | rejected | rejected | yes | none | #legal-marketing-2026-10-30 | approved | 76 | 14 s |

**`demo_01_hockey_night_live.png`** — Clean ad.

> Approved as submitted: the ad shows live odds as plain facts, with no offer, no promise of winning, no people or logos, and city names only for the teams. It matches the earlier approved live-odds ads NP-H01 and NP-H13 and the team's city-names-only decision. No changes are needed.

**`demo_02_big_game_bonus.png`** — Rejected on regulations and on Slack.

> Rejected: this Instagram ad advertises a deposit bonus, and bonuses may not be advertised on public channels, the same outcome as past ads NP-H06 and NP-H07. It also calls the bet 'free' even though a deposit is required, and NorthPlay has separately banned the word 'free' in all marketing, even where the rules would allow it. The corrected version removes the offer and the urgency and keeps the brand, the Big Game theme and the required responsible gambling lines; the offer itself can go to opted-in players by email using the approved H05 template.

Conflicts the agent reported between sources:

- REG-13 allows 'free' when the offer is literally free and runs on a permitted channel, but Legal's later binding decision bans 'free' everywhere, and binding decisions may add requirements stricter than policy.

**`demo_03_play_smart_breaks.png`** — Passes the regulations and matches an approved precedent; rejected only because of Slack.

> Rejected: the ad features Jake Moreau, and his partnership was terminated on 2026-10-30. Internal legal has barred any use of his name or quotes, even in responsible gambling messaging that Ontario's athlete rule would otherwise allow. The corrected version removes him and his quote and keeps a responsible-gambling-only message with the limits call to action.

Conflicts the agent reported between sources:

- REG-03's exception allows an athlete in a message made only to promote responsible gambling, which this ad is, but the later binding decision bans any use of Jake Moreau because the partnership was terminated, and a stricter binding decision adds to policy.

## The 15 past ads

**14 of 15 match the recorded decision; 1 stricter; 0 looser.** Whole run: 160 s, 188,516 input tokens of which 114,525 were served from the prompt cache.

| Ad | Recorded | Agent | Match | Rules recorded | Cited by the agent | Confidence |
|---|---|---|---|---|---|---|
| NP-H01 Saturday night. Every play, live. | approved | approved | yes | REG-14, REG-09, REG-12 | none | 80 |
| NP-H02 Set your limits. Then enjoy the game. | approved | approved | yes | REG-14, REG-06 | none | 80 |
| NP-H03 Know your limit before kickoff. | approved | approved | yes | REG-03, REG-14 | none | 80 |
| NP-H04 Build your parlay in seconds. | approved | approved | yes | REG-09, REG-14 | none | 80 |
| NP-H05 Bet $50, get $50 in bonus bets | approved | approved with changes | **stricter** | REG-12, REG-13, REG-15, REG-14 | REG-15, #legal-marketing-2026-10-20 | 52 |
| NP-H06 Get $500 in bonus bets when you sign up! | rejected | rejected | yes | REG-12 | REG-12, #marketing-2026-11-11 | 76 |
| NP-H07 Your first bet is RISK-FREE. | rejected | rejected | yes | REG-12, REG-13 | REG-12, REG-13, #legal-marketing-2026-11-04 | 76 |
| NP-H08 Get in the game with Jake Moreau. | rejected | rejected | yes | REG-03, REG-11 | REG-03, #legal-marketing-2026-10-30 | 76 |
| NP-H09 Rent due? Your next parlay could cover it. | rejected | rejected | yes | REG-07, REG-09, REG-06 | REG-07, REG-09 | 76 |
| NP-H10 Rough Sunday? Win it all back Monday night. | rejected | rejected | yes | REG-08, REG-06 | REG-07, REG-08, REG-09, #legal-marketing-2026-10-05 | 76 |
| NP-H11 Tonight's LOCK: Toronto ML. Easy money. | rejected | rejected | yes | REG-09 | REG-06, REG-09, #marketing-2026-10-10 | 76 |
| NP-H12 No cap, this parlay is bussin. | rejected | rejected | yes | REG-02, REG-01, REG-11 | REG-01, REG-02, REG-09, REG-11, #marketing-2026-10-17 | 76 |
| NP-H13 Ottawa vs. Edmonton. Odds are live. | approved with changes | approved with changes | yes | REG-14 | REG-14 | 80 |
| NP-H14 Turned 19? Welcome to the big leagues. | approved with changes | approved with changes | yes | REG-11, REG-05 | REG-06, REG-11 | 76 |
| NP-H15 Tip-off is tonight. | approved with changes | approved with changes | yes | REG-14 | REG-14 | 60 |

Reading the rule columns: for an approved ad the record lists the rules it was checked against, and the agent cites none because it found no breach. For a rejected ad, the agent's citations should include the recorded ones; extra citations are further breaches it found, and `#channel-date` entries are Slack decisions.

## Where it differs

- **NP-H05 Bet $50, get $50 in bonus bets** — recorded approved, agent says approved with changes. This opted-in email can carry the $50 bonus bet offer: inducements are allowed in consented direct marketing, the material terms are shown, and it correctly says 'bonus bets' rather than 'free'. Two points need a person to confirm: that the email includes an unsubscribe option, and whether Legal's decision on NFL marks covers the league name 'NFL'. The corrected version adds an unsubscribe line and uses neutral football wording.
