# Numbers

**Exact decimal arithmetic for the numbers that decide a trade.**
A toolkit for the UnifAI network. Eight actions, 81 tests, no dependencies beyond
[`unifai-guard`](https://github.com/Dizz-Network-Dizzik/unifai-guard).

> Unofficial and unaffiliated community work. Not financial advice: it computes, it does not recommend.

---

## Why

A language model can reason about a trade and cannot reliably compute one. Ask it
for a liquidation price and you get a plausible number. Plausible is worth nothing
when the position closes.

The failure is not exotic. It is `0.1 + 0.2`, it is basis points read as percent,
it is `1e18` wei quietly treated as one ether, it is a maintenance-margin rate
approximated with a formula that drifts exactly where leverage makes it matter.
Each of these is a number somebody acts on.

Everything here is ordinary decimal arithmetic done with `decimal`, not with
binary floats. That is the whole trick, and it is enough.

## Thirty seconds, no key

```bash
python run.py --dry-run                  # all eight actions and their descriptions
python -m unittest discover -s tests     # 81 tests
```

To serve it: get a free toolkit key at <https://console.unifai.network>, set
`UNIFAI_TOOLKIT_API_KEY`, run `python run.py`. Windows users can double-click
`START.cmd`, which does the dry run when no key is set.

## The eight actions

| Action | What it answers |
|---|---|
| `position_size` | Given equity, a risk percentage, an entry and a stop — how many units lose exactly that percentage if the stop is hit. |
| `liquidation_price` | Where an isolated linear perpetual gets closed. Derived, not approximated. |
| `swap_output` | Constant-product AMM output, fee applied, **price impact stated separately**. |
| `impermanent_loss` | LP loss against holding, for a given price ratio change. |
| `pnl` | Realised P&L after fees on both legs and funding, plus return on margin. |
| `apr_apy` | Convert between simple and compounded rates. At 100% APR, daily compounding is 171.46% APY. |
| `slippage_bounds` | The minimum output to actually sign for. |
| `breakeven_move` | How far price must move before a round trip is worth nothing. |

## Three rules, in every answer

**1. Show the work.** Every result carries the formula it used, the inputs it used
it on, and the assumptions that would change it. A number an agent cannot check is
a number nobody should act on.

```json
{
  "ok": true,
  "values": {"units": "20", "notional": "1000", "leverage_required": "0.1"},
  "inputs": {"equity": "10000", "risk_pct": "1", "entry": "50", "stop": "45"},
  "formula": "units = (equity * risk_pct / 100) / |entry - stop|",
  "model": "risk-based sizing, fees and slippage excluded",
  "assumptions": [
    "The stop fills at the stop price. In a fast market it does not, and the real loss is larger than risk_pct.",
    "Fees are not included; add roughly two fee legs on the notional."
  ]
}
```

Values come back as **strings**, not floats. Returning `20.000000000000004` over
JSON would undo the entire point.

**2. Refuse rather than guess.** A stop above entry on a long is not an input to be
normalised away — it means caller and callee disagree about what is being asked:

```json
{
  "ok": false,
  "error": "inconsistent_inputs",
  "message": "long with a stop above entry (55 > 50) -- that is not a stop, it is a target; check the side",
  "hint": "Refusing is deliberate: a plausible number here would be acted on."
}
```

Same for a hallucinated parameter. An agent inventing a `leverage` field on
`position_size` is telling you something, and the answer is a rejection naming the
field, not a silent shrug.

**3. Name the model.** A liquidation price depends on isolated vs cross margin,
linear vs inverse contracts, flat vs tiered maintenance rates. Every action says
which case it computed, so the answer can be checked against the venue instead of
trusted.

On that last point specifically — the derivation is in the source, because the
common shortcut is wrong where it matters:

```
equity = maintenance  ->  M + S(P-E) = S*P*mmr,  M = S*E/L
long :  P = E(1 - 1/L) / (1 - mmr)
short:  P = E(1 + 1/L) / (1 + mmr)
```

The usual `E(1 - 1/L + mmr)` agrees to first order and drifts as leverage rises —
which is precisely the regime where somebody is looking the number up. There is a
test asserting the two differ.

## Also a worked example of unifai-guard

Every schema in `actions.py` is declared once and produces **both** the
natural-language `payload_description` UnifAI serves to agents **and** the
validation that runs before the handler sees anything:

```python
risk_pct = Field.number(
    "Percentage of equity to lose if the stop is hit. Typical values are 0.5 to 2. "
    "This is a percentage, not a fraction: pass 1 for one percent.",
    minimum=0, exclusive_minimum=True, maximum=100, examples=[1],
)
```

becomes, for the agent:

> Percentage of equity to lose if the stop is hit. Typical values are 0.5 to 2.
> This is a percentage, not a fraction: pass 1 for one percent. **Required. Must be
> greater than 0 and at most 100. Example: 1.**

and, for the code, the check that enforces exactly that. They cannot drift apart,
because there is only one of them. `actions.py` is short *because* of this, not
despite it.

**What this toolkit does not use from `unifai-guard`:** the spend gates and the
audit ledger. Nothing here moves value — it is a calculator — so wiring up
approval thresholds would be theatre. The `monetary=True` flag is deliberately
absent from every field; it makes the guard write *"this field moves value"* into
the description, and that sentence would be false. A false sentence in a
description an agent reads is the exact failure the guard exists to prevent, so it
would be a poor place to start lying.

## What this does not do

- **No prices, no chain reads, no network.** You pass reserves and rates in; it
  does arithmetic. It cannot tell you whether the numbers you passed are current,
  and the moment you act on them they are not.
- **No routing, no concentrated liquidity.** `swap_output` is a single
  constant-product pool. Against a v3-style pool it understates depth near the
  current tick.
- **No venue-specific margin tiers.** Pass the maintenance rate for your tier from
  the venue's own table. The default is a common small-tier value and is not a
  promise about your venue.
- **No advice.** These are formulas. What to do with them is not a function call.

## Disclosure

The author holds UAI and has received no payment, tokens or other consideration
from UnifAI for this work (as of 2026-10-08). The holding is a reason to disclose,
not a reason to withhold the work. Nothing here is investment advice.

## License

Licensed under the Apache License, Version 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE).
