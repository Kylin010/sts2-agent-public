# Separate public HP summaries from legacy damage samples

Legacy `combats[].dmg` accumulates positive HP differences at combat-play
observations. It is not net loss and misses the transition from the last action
to the first postcombat observation. In 160 completed mainline games, all 159
combat deaths omit that final HP drop: 1730 HP total, including 701 in Act 2.

`combat_hp_metrics` defaults to false. When enabled, an independent
`hp_metrics` object records first/last public HP, sampled positive drops,
observation count and the first postcombat HP endpoint. It reports net loss
only if that endpoint is valid. Missing endpoints stay incomplete; the runtime
does not infer HP zero from an outcome flag. The metric includes combat card
selection observations, and postcombat HP may include healing or rewards.

Existing `dmg`, `hp`, training `turns`, decisions and commands are preserved.
This is optional telemetry, not a measured policy improvement or an exact
engine `DamageTaken` counter. Damage plus healing inside one visible
transition cannot be reconstructed from HP endpoints.

Validation: `python3 tests/test_public_combat_hp_metrics.py -v` passes six
synthetic public-transport tests with subprocess creation blocked. It covers
death, healing/card selection, final-action self-damage, net gains, legacy
behavior parity, malformed/missing endpoints and missing prior observations.
No native game ran.

The completed-history audit reproduces 2101 legacy combat metrics exactly.
Inferred retrospective death endpoints and the missing victorious endpoint
are kept separate from actual public HP observations. Raw files are untouched.

Report:
`/opt/slay-the-spire-2/codex-agent/research/normal-strategy-20261005/05-战损口径与致死终态遗漏.md`.
