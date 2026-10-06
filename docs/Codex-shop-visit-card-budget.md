# Limit card purchases over a whole merchant visit

With `shop_max_cards=2`, the calibrated planner caps each recomputed bundle at
two cards. Because it returns one action and replans after each purchase, a
visit can still buy three or four. In 160 completed mainline games, 13 of 340
visits exceeded two cards (12 in Act 1, one in Act 2).

`shop_visit_card_cap` defaults to false. When enabled, both planners subtract
card entries in the existing visit ledger from the configured budget. Removal,
relics and potions use their existing rules; leaving clears the visit ledger.
The ledger records selected attempts before command acknowledgement, so an
unsuccessful purchase that is allowed to continue conservatively uses budget.
The patch keeps existing slot/restocking semantics.

Validation: `python3 tests/test_shop_visit_card_budget.py -v` passes six tests
covering sequential replanning in both modes, legacy behavior with the flag
off, next-visit reset, noncard purchases, and remaining/zero bundle budgets.
These are pure checks with subprocess creation blocked, not game outcomes.

Mainline should compare only this flag on the same fresh100/dev60 seeds and
report Act 2 and complete victories separately. Win-rate gain is unproven.
Community winners and losers obtain approximately one card per Act 2 shop;
our observed rate is lower. The implementation mismatch does not prove that
the cap itself improves strategy. A third synergistic card may be beneficial.

The full Chinese report and source-hashed data are in
`/opt/slay-the-spire-2/codex-agent/research/normal-strategy-20261005/03-商店买牌预算与赢家输家对比.md`.
