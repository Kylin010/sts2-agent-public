# Recognize Body Slam's block payoff in route strength

Legacy static card knowledge stores Body Slam damage as zero, so both deck
evaluators omit its output even with enough block. The optional route-only
component estimates marginal damage using paired five-card hands: both versions
share a three-energy budget, but one permits Body Slam. Block must precede the
attack, upgraded Slam costs zero, and True Grit's chosen/random exhaustion is
modeled. It never reads the actual draw order or game RNG.

`route_body_slam_strength` defaults to false and applies to Act 2 only. The
component adds its mean marginal to route DPT and readiness, while global deck,
reward and combat scoring stay unchanged. Normality decks and Snecko Eye owners
retain the old estimate. Samples use a private stream and canonical card order.

Eight new pure tests and eleven existing route regressions pass with native
process creation blocked. No game or measured win-rate evaluation ran. In 77
historical public snapshots from 14 runs, the average DPT increment is about
0.92. Snapshot counts are not game counts or actual changed map choices.

The component omits setup, draws/generated cards, relic modifiers and enemy
mechanisms. Generic card upgrades still use legacy approximations. Missing
alternative actions can overvalue its marginal; this is not a conservative
bound or an exact complete combat model. Mainline must compare the flag alone
on paired complete games, prioritizing Act 2 and reporting full victories.

Report:
`/opt/slay-the-spire-2/codex-agent/research/normal-strategy-20261005/07-路线忽略全身撞击的格挡输出.md`.
