# Hackathon brief and submission checklist

Agents in Context Toronto: a MongoDB Hackathon. Verified November 14, 2026. All event times below are EST (UTC-05:00).

## Official sources

- [Event details, rules and judging](https://cerebralvalley.ai/e/mongodb-toronto-hackathon/details)
- [Participant resource guide](https://docs.google.com/document/d/1rrsNKU3guyvExg_oBPpfOrZF9Ypr5xPLFQ9yYJ2C60o/edit)
- [Cerebral Valley submission form](https://cerebralvalley.ai/e/mongodb-toronto-hackathon/hackathon/submit)
- [Discord rules](https://discord.com/channels/1556837758490906634/1556837759254134958/1570144860936347659)
- [Discord questions and organizer clarifications](https://discord.com/channels/1556837758490906634/1556837759694409830)

## Schedule and eligibility

| Milestone | November 14, EST |
| --- | --- |
| Doors and team formation | 9:00 AM |
| Kickoff, per organizer email | 10:00 AM |
| Hacking begins, per resource guide | 10:45 AM |
| Lunch | 1:00 PM |
| Submit on Cerebral Valley; public repository ready | 5:00 PM |
| First-round live judging | 5:15–6:45 PM |
| Dinner | 6:00 PM |
| Top-six final demos | 7:00–8:00 PM |
| Winners announced | 8:15 PM |
| Doors close | 9:00 PM |

- Venue: The Quay, 100 Queens Quay E, third floor, Toronto. Lobby entrance is right of the LCBO doors off Queens Quay East. Bring government-issued photo ID.
- Leaving and reentering is allowed; retain the event wristband.
- Up to four members. Each participant must be approved on Cerebral Valley; Luma registration alone is insufficient. Organizer email set registration close to November 13 at 11:59 PM ET.
- For finalist eligibility, the project and cluster must be built in the provided MongoDB Atlas Hackathon Sandbox. A successful connection to a personal Atlas cluster is not enough.
- All judging demos are live and in person. Keep the GitHub repository public through judging and ensure demo links are accessible.
- Check-in before 11:00 AM is required for ElevenLabs credit eligibility, per organizer email.

## Submission checklist

Nothing is submitted by this checklist. Use the Cerebral Valley form.

- [ ] Team name and all team members.
- [ ] Project description, maximum 3,000 characters.
- [ ] Public GitHub repository URL; check access while signed out.
- [ ] One-minute demo video showing code and functionality built during this event; verify audio, video, and link permissions.
- [ ] One of the three problem statements selected.
- [ ] Description of MongoDB product use, maximum 3,000 characters.
- [ ] Partner technologies selected: ElevenLabs, LangChain, or N/A.
- [ ] MongoDB feedback, maximum 150 characters, if provided.
- [ ] Original contributions and reused materials clearly disclosed.
- [ ] Submission completed before 5:00 PM and confirmation verified.

PM suggested internal targets, not organizer deadlines: freeze scope at 3:30 PM, record by 4:00 PM, check links and team list by 4:30 PM, submit by 4:45 PM.

## Choose one track and prove its behavior

| Track | Required core | Demo evidence |
| --- | --- | --- |
| Agents You Can Audit | Atlas identity, policy, audit layer; actions across systems | Policy enforced before action; identity and authority recorded; reconstruct action; stop or rollback |
| Memory You Can Govern | Atlas and Vector Search for persistent governed memory | Memory changes a later run; tenant isolation; correction, expiry and forgetting |
| Finish the Job | Atlas verified task state plus Vector Search for prior experience | Distinguish dispatched from completed action; resume after a crash; adapt to system changes |

## Originality and excluded projects

Originality is a required review gate, not a claim that no similar product exists. The rules require original event work, no presentation of an existing project as new work, and clear identification of the team's contributions. Failure to distinguish original contributions can cause immediate disqualification.

The [organizer's 10:10 AM Discord clarification](https://discord.com/channels/1556837758490906634/1556837759694409830/1571180458190839860) says code must be written during the build window, empty repository creation is allowed, earlier scaffolding must not be preloaded, and pre-existing libraries, datasets and starter templates must be listed in the README. The reported first-commit wording should be clarified with organizers if a repository already has setup-only commits. Preserve truthful history.

Before approving an idea:
1. State its user, concrete problem, primary track, and one behavior the live demo will prove.
2. Reject prohibited project categories.
3. Search existing products, public repositories and past hackathon entries for the same workflow. Record links, overlaps, and concrete differences. A search can assess similarity; it cannot prove universal uniqueness.
4. Separate reused dependencies, templates, datasets and assets from code built during the event; record licenses and attribution.
5. Keep an honest build/contribution log. Demo only the new contribution.
6. Resolve ambiguous rule conflicts with organizers before treating the project as eligible.

The official page's STRICTLY NO list:
- AI Mental Health Advisor
- Basic RAG Applications
- Streamlit Applications
- Image Analyzers
- "AI for Education" Chatbot
- AI Job Application Screener
- AI Nutrition Coach
- Personality Analyzers
- Any project using AI to generate and give medical advice
- Any project where a dashboard is the main feature
- Sports analyzers or coaches

Do not treat a renamed prohibited idea as compliant. A UI or retrieval feature must support a qualifying agent workflow, and an ambiguous boundary still needs organizer clarification.

Originality review status: OPEN. The team's final idea has not yet been confirmed to the project manager. Earlier brainstorms are not approved selections.

## Judging

First round: technical demo 35%, implementation difficulty 30%, creativity 15%, impact 20%. Plan about three minutes of live demo and one to two minutes of Q&A.

Final round: top six teams, three minutes live demo plus two minutes Q&A. The same four categories are equally weighted.

The one-minute submission video is separate from the longer live judging demo.

## Resources

Use the participant guide for current links and eligibility:
- MongoDB Agent Skills, MCP Server, data modeling, Vector Search, LangGraph checkpoints, sample data, and disclosed starter examples.
- ElevenLabs: one month Creator plan, 131k credits; redemption through its Discord coupon workflow with the Cerebral Valley registration email.
- LangSmith: $50 credits plus Deployments access; redemption within ten days of the event. The guide says a card is required to display credits. Confirm terms in the provider UI before adding payment details.
- Voyage AI: guide advertises 200 million free tokens. Keep keys in local ignored environment settings; check usage and provider limits.
- Discord organizer reply says sandbox clusters last one week after the event; do not assume long-term hosting.

Prizes in the guide: MongoDB USD 7,000 / 5,000 / 3,000 plus LangSmith credits 3,000 / 2,000 / 1,000; first place also receives three months ElevenLabs Pro. Best ElevenLabs project receives three months Scale.

## Coverage

The participant guide, official event details and blank submission form were read. Organizer email supplied check-in and approval logistics. Discord coverage: rules, announcements, general, all three track channels, MongoDB channel (empty on inspection), and latest questions plus pins through 10:23 AM. One pinned message could not load. Historical questions were not exhaustively traversed. Intros, team-search, join logs, DMs and unrelated servers were excluded. This is a sourced operational brief, not a complete server archive. Later organizer announcements can change logistics. No external messages or submission were sent as part of this review.
