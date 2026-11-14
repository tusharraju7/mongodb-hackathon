# Local Codex versus Claude: three demo ads

Generated 2026-11-14T20:36:45.747495+00:00. Prompt 2026-11-14.3.

Assessment: `codex:gpt-5.6-sol`; smaller steps: `codex:gpt-5.6-luna`; both low reasoning.

Same image inputs, channel, policy pipeline and scoped seed memory. Claude baseline: [RESULTS.md](RESULTS.md).
These are fixture-source pipeline runs, not authenticated browser uploads. No Atlas records or memories were changed.

| Ad | Claude decision | Codex decision | Confidence | Time |
|---|---|---|---|---|
| demo_01_hockey_night_live.png | approved | approved | 80 | 52.43s |
| demo_02_big_game_bonus.png | rejected | rejected | 76 | 63.15s |
| demo_03_play_smart_breaks.png | rejected | rejected | 76 | 59.57s |

Confidence is computed by the existing backend; it is not a risk score or a probability. Timing includes CLI startup, image reading, extraction, retrieval and assessment. Single runs are not a speed benchmark.

Full image readings, findings, source references, timings and CLI token counts: [JSON results](results/codex-demos.json).

## demo_01_hockey_night_live.png

The ad is compliant as submitted. It presents live odds factually without an inducement or promise of winning, uses city names only, shows no people or youth-oriented elements, and includes the required legible responsible gambling line.

## demo_02_big_game_bonus.png

Rejected: this public Instagram ad advertises a deposit-linked bonus bet, and it impermissibly calls the offer “FREE.” The corrected version removes the entire offer and its offer-specific call to action while retaining the acceptable event heading and required responsible-gambling line.

- REG-12: The ad promotes a deposit-linked bonus bet on public paid social, where inducement advertising is prohibited.
- REG-13: The bet is described as free even though obtaining it requires the player to deposit their own money.
- slack-legal-marketing-2026-11-04: NorthPlay's binding decision prohibits the word “free” in all marketing, regardless of channel or offer terms.
## demo_03_play_smart_breaks.png

Reject as submitted because a binding internal decision prohibits using Jake Moreau’s name or quotes in any creative. The responsible-gambling-only athlete exception would otherwise permit this message, but the later partnership decision is stricter. The corrected version removes Jake Moreau and his attributed quote while retaining the Play Smart branding, limits call to action, and required disclaimer.

- slack-legal-marketing-2026-10-30: The ad uses Jake Moreau’s name and attributed quote after NorthPlay terminated the partnership and prohibited his use in any creative.
## Comparison limits

All decisions match, but the findings are not identical: Claude also cited REG-06 on the bonus ad; Codex did not. The Codex no-memory ablation was not run. CLI context overhead is included in token counts. See [local adapter setup](CODEX_LOCAL.md).
