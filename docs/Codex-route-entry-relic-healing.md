# Include owned room-entry healing in route projections

The route planner currently treats a shop as shopping value and a camp as
healing or upgrading. It omits Meal Ticket's 15 HP on merchant entry and
Eternal Feather's 3 HP per full group of five cards on camp entry. These
effects happen before the camp choice and use current visible inventory.

`route_entry_relic_heal` defaults to false; `route_entry_relic_heal_acts`
defaults to `[2]`. Enabled projections cap healing at maximum HP and keep
nonpositive projected HP unchanged. Feather uses the current public deck
size for future camps. The patch does not predict future acquisitions or
question-mark outcomes, and does not change actual HP or rest decisions.

Seven pure tests pass with subprocess creation blocked, including an actual
route fork, missing relics, default behavior, act scope, deck-size rounding,
HP caps and entry-before-camp timing. No game or win-rate evaluation ran.

Completed mainline histories contain ten positive Act 2 map-to-shop healing
transitions in final Meal Ticket holders, totaling 120 HP. Final inventory
locates those records but does not certify inventory at every earlier fork.
Human winner and loser histories are both analyzed with prior-history relic
acquisition tracking. Human room healing totals include other effects.

Mainline should test this flag alone on fresh100/dev60 paired complete games,
using Act 2 as the primary outcome and reporting complete victories separately.
Do not call the mechanism correction a measured win-rate improvement.

If combined later with `codex/route-rest-consistency`, preserve entry healing,
then the Boss-proximity threshold, then the projected camp action.

Full report and source-hashed data:
`/opt/slay-the-spire-2/codex-agent/research/normal-strategy-20261005/04-第二幕路线漏算进门回血.md`.
