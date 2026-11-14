# Review results against the expected outcomes

Generated 2026-11-14 20:45 UTC by `python -m scripts.dry_run --suite --report`. Prompt version `2026-11-14.3`; verdict model `anthropic:claude-opus-5-5` at effort `low`; fast model `anthropic:claude-haiku-5-5`.

## Where the expected results come from

- **15 past ads.** `northplay-demo-data/historical_ads/historical_ads.json` records, for each, the decision that was made and the rules it cited. That record is the expected result.
- **3 demo ads.** The data set's README states what each should come out as. The detailed answer keys are held outside the repo.

Each past ad is reviewed without the memory of its own decision, so the result is not simply read back. Slack decisions made after an ad was decided are in view, so an ad can correctly come back stricter today than it was decided then.

## The three demo ads

Submitted for the channel "Instagram (paid social)", which is an assumption: the channel is chosen at upload.

| Ad | Expected | Agent | Match | Regulations cited | Slack decisions cited | Without memory | Confidence | Time |
|---|---|---|---|---|---|---|---|---|
| `demo_01_hockey_night_live.png` | approved | approved | yes | none | none | approved | 80 | 14 s |
| `demo_02_big_game_bonus.png` | rejected | rejected | yes | REG-06, REG-12, REG-13 | #legal-marketing-2026-11-04 | rejected | 76 | 18 s |
| `demo_03_play_smart_breaks.png` | rejected | rejected | yes | none | #legal-marketing-2026-10-30 | approved | 76 | 37 s |

**`demo_01_hockey_night_live.png`** — Clean ad.

> Approved as submitted: the ad shows live odds as plain facts, with no offer, no promise of winning, no people or mascots, and city names only for the teams. It follows the precedent set for the similar live-odds ad NP-H01, and the colours and disclaimer meet team guidance. No changes are needed.

**`demo_02_big_game_bonus.png`** — Rejected on regulations and on Slack.

> This ad would be rejected: it advertises a deposit bonus on Instagram, a public channel, and calls the bet 'free' even though a $50 deposit is required. Policy might allow 'free' when it is literally true, but Legal's November 4 decision bans the word in all NorthPlay marketing. The corrected version removes the offer, the 'free' wording and the urgency, leaving a brand message plus the required responsible gambling line.

Conflicts the agent reported between sources:

- REG-13 allows 'free' where it is literally true on a permitted channel, but the later binding decision bans 'free' in all NorthPlay marketing, and a binding decision may add requirements stricter than policy.

**`demo_03_play_smart_breaks.png`** — Passes the regulations and matches an approved precedent; rejected only because of Slack.

> This ad should be rejected because it names and quotes Jake Moreau. Policy would normally allow a former athlete in a responsible-gambling-only message, but Legal ended his partnership on 2026-10-30 and banned his name and quotes from all creative, including Play Smart. The corrected version keeps the limits message and removes his name and the quote attribution.

Conflicts the agent reported between sources:

- REG-03 allows an athlete in a message made only for responsible gambling, which this ad is, but the later binding internal decision bans Jake Moreau from all creative because the partnership has ended, and a stricter binding decision adds to policy.

## The 15 past ads

**14 of 15 match the recorded decision; 1 stricter; 0 looser.** Whole run: 148 s, 188,917 input tokens of which 114,525 were served from the prompt cache.

| Ad | Recorded | Agent | Match | Rules recorded | Cited by the agent | Confidence |
|---|---|---|---|---|---|---|
| NP-H01 Saturday night. Every play, live. | approved | approved | yes | REG-14, REG-09, REG-12 | none | 80 |
| NP-H02 Set your limits. Then enjoy the game. | approved | approved | yes | REG-14, REG-06 | none | 80 |
| NP-H03 Know your limit before kickoff. | approved | approved | yes | REG-03, REG-14 | none | 80 |
| NP-H04 Build your parlay in seconds. | approved | approved | yes | REG-09, REG-14 | none | 80 |
| NP-H05 Bet $50, get $50 in bonus bets | approved | approved with changes | **stricter** | REG-12, REG-13, REG-15, REG-14 | REG-15, #legal-marketing-2026-10-20 | 52 |
| NP-H06 Get $500 in bonus bets when you sign up! | rejected | rejected | yes | REG-12 | REG-06, REG-12 | 76 |
| NP-H07 Your first bet is RISK-FREE. | rejected | rejected | yes | REG-12, REG-13 | REG-12, REG-13, #legal-marketing-2026-11-04 | 76 |
| NP-H08 Get in the game with Jake Moreau. | rejected | rejected | yes | REG-03, REG-11 | REG-03, REG-11, #legal-marketing-2026-10-30 | 76 |
| NP-H09 Rent due? Your next parlay could cover it. | rejected | rejected | yes | REG-07, REG-09, REG-06 | REG-07, REG-09 | 76 |
| NP-H10 Rough Sunday? Win it all back Monday night. | rejected | rejected | yes | REG-08, REG-06 | REG-07, REG-08, REG-10, #legal-marketing-2026-10-05 | 76 |
| NP-H11 Tonight's LOCK: Toronto ML. Easy money. | rejected | rejected | yes | REG-09 | REG-09, #marketing-2026-10-10 | 76 |
| NP-H12 No cap, this parlay is bussin. | rejected | rejected | yes | REG-02, REG-01, REG-11 | REG-01, REG-02, REG-11 | 76 |
| NP-H13 Ottawa vs. Edmonton. Odds are live. | approved with changes | approved with changes | yes | REG-14 | REG-14 | 80 |
| NP-H14 Turned 19? Welcome to the big leagues. | approved with changes | approved with changes | yes | REG-11, REG-05 | REG-06, REG-11 | 76 |
| NP-H15 Tip-off is tonight. | approved with changes | approved with changes | yes | REG-14 | REG-14 | 60 |

Reading the rule columns: for an approved ad the record lists the rules it was checked against, and the agent cites none because it found no breach. For a rejected ad, the agent's citations should include the recorded ones; extra citations are further breaches it found, and `#channel-date` entries are Slack decisions.

## Where it differs

- **NP-H05 Bet $50, get $50 in bonus bets** — recorded approved, agent says approved with changes. The offer may run because this is an opted-in email, it uses 'bonus bets' rather than 'free', and the key terms are shown up front. Two points need a person to confirm: whether the name 'NFL' may be used, given Legal's 2026-10-20 note that NorthPlay holds no NFL marks, and whether the email includes an unsubscribe link. The corrected version swaps 'NFL' for 'pro football' and adds an unsubscribe line.
