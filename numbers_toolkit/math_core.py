# -*- coding: utf-8 -*-
"""Exact arithmetic for the numbers that decide real money.

A language model can reason about a trade and cannot reliably compute one. Ask
for a liquidation price and you get a plausible number; plausible is worth
nothing when the position closes. Every function here is ordinary decimal
arithmetic, done with :mod:`decimal` rather than binary floats, so ``0.1 + 0.2``
is ``0.3`` and a fee of 0.0005 is a fee of 0.0005.

Three rules hold throughout:

1. **Show the work.** Every result carries the formula it used and the inputs it
   used it on. A number an agent cannot check is a number nobody should act on.
2. **Refuse rather than guess.** A stop above entry on a long is not a small
   input error to be normalised away -- it means the caller and the callee
   disagree about what is being asked. That is a stop, not a shrug.
3. **Name the model.** A liquidation price depends on isolated vs cross margin,
   linear vs inverse contracts, flat vs tiered maintenance rates, and whether
   fees are charged on entry. Every function says which case it computed, so the
   answer can be checked against the venue instead of trusted.
"""
from __future__ import annotations

from dataclasses import dataclass, field as _dc_field
from decimal import Decimal, InvalidOperation, getcontext, localcontext
from typing import Any, Dict, List, Union

getcontext().prec = 34

Num = Union[int, float, str, Decimal]

__all__ = [
    "NumbersError", "Result", "D",
    "position_size", "liquidation_price", "swap_output", "impermanent_loss",
    "pnl", "apr_apy", "slippage_bounds", "breakeven_move",
]


class NumbersError(ValueError):
    """The inputs do not describe a situation that has an answer."""


@dataclass
class Result:
    values: Dict[str, Decimal]
    formula: str
    model: str
    assumptions: List[str] = _dc_field(default_factory=list)
    inputs: Dict[str, Decimal] = _dc_field(default_factory=dict)

    def as_dict(self, places: int = 10) -> Dict[str, Any]:
        return {
            "values": {k: _fmt(v, places) for k, v in self.values.items()},
            "inputs": {k: _fmt(v, places) for k, v in self.inputs.items()},
            "formula": self.formula,
            "model": self.model,
            "assumptions": list(self.assumptions),
        }


def D(x: Num, name: str = "value") -> Decimal:
    """Decimal from anything sane; a clear error from anything else."""
    if isinstance(x, Decimal):
        d = x
    elif isinstance(x, bool):
        raise NumbersError("%s: a boolean is not a number" % name)
    else:
        try:
            d = Decimal(str(x))
        except (InvalidOperation, ValueError, TypeError):
            raise NumbersError("%s: %r is not a number" % (name, x))
    if not d.is_finite():
        raise NumbersError("%s: must be finite, got %s" % (name, d))
    return d


def _fmt(d: Decimal, places: int) -> str:
    """A string, not a float: the caller must not silently lose the precision."""
    q = d.quantize(Decimal(1).scaleb(-places)) if d == d.to_integral_value() or True else d
    q = q.normalize()
    return format(q, "f")


def _positive(x: Decimal, name: str) -> Decimal:
    if x <= 0:
        raise NumbersError("%s must be greater than zero, got %s" % (name, x))
    return x


def _side(side: str) -> str:
    s = str(side).strip().lower()
    if s in ("long", "buy", "l"):
        return "long"
    if s in ("short", "sell", "s"):
        return "short"
    raise NumbersError("side must be 'long' or 'short', got %r" % side)


# --------------------------------------------------------------------------- #
def position_size(equity: Num, risk_pct: Num, entry: Num, stop: Num,
                  side: str = "long") -> Result:
    """How many units to buy so that being wrong costs exactly ``risk_pct``.

    The single most useful calculation in trading and the one most often done in
    someone's head, wrongly. The answer does not depend on leverage: leverage
    decides the margin, the stop decides the loss.
    """
    e = _positive(D(equity, "equity"), "equity")
    r = D(risk_pct, "risk_pct")
    en = _positive(D(entry, "entry"), "entry")
    st = _positive(D(stop, "stop"), "stop")
    sd = _side(side)

    if not (0 < r <= 100):
        raise NumbersError("risk_pct must be between 0 and 100, got %s" % r)
    if en == st:
        raise NumbersError("entry and stop are the same price -- risk per unit is zero "
                           "and the position size would be unbounded")
    if sd == "long" and st > en:
        raise NumbersError("long with a stop above entry (%s > %s) -- that is not a "
                           "stop, it is a target; check the side" % (st, en))
    if sd == "short" and st < en:
        raise NumbersError("short with a stop below entry (%s < %s) -- that is not a "
                           "stop, it is a target; check the side" % (st, en))

    risk_amount = e * r / Decimal(100)
    risk_per_unit = abs(en - st)
    units = risk_amount / risk_per_unit
    notional = units * en

    return Result(
        values={
            "units": units,
            "notional": notional,
            "risk_amount": risk_amount,
            "risk_per_unit": risk_per_unit,
            "stop_distance_pct": risk_per_unit / en * Decimal(100),
            "leverage_required": notional / e,
        },
        inputs={"equity": e, "risk_pct": r, "entry": en, "stop": st},
        formula="units = (equity * risk_pct / 100) / |entry - stop|",
        model="risk-based sizing, fees and slippage excluded",
        assumptions=[
            "The stop fills at the stop price. In a fast market it does not, and the "
            "real loss is larger than risk_pct.",
            "Fees are not included; add roughly two fee legs on the notional.",
            "leverage_required is notional/equity -- if it exceeds what the venue "
            "allows, the stop is too tight for this account, not the other way round.",
        ],
    )


# --------------------------------------------------------------------------- #
def liquidation_price(entry: Num, leverage: Num, side: str = "long",
                      maintenance_margin_rate: Num = "0.005") -> Result:
    """Where an isolated linear position is closed by the venue.

    Derived, not approximated. Equity is initial margin plus unrealised PnL;
    liquidation is where equity meets the maintenance requirement:

        long :  M + S(P-E) = S*P*mmr   ->  P = E(1 - 1/L) / (1 - mmr)
        short:  M + S(E-P) = S*P*mmr   ->  P = E(1 + 1/L) / (1 + mmr)

    with M = S*E/L. The common shortcut ``E(1 - 1/L + mmr)`` is the same thing to
    first order and drifts at high leverage, which is precisely where it matters.
    """
    en = _positive(D(entry, "entry"), "entry")
    lev = _positive(D(leverage, "leverage"), "leverage")
    mmr = D(maintenance_margin_rate, "maintenance_margin_rate")
    sd = _side(side)

    if lev < 1:
        raise NumbersError("leverage below 1 is not a leveraged position, got %s" % lev)
    if not (0 <= mmr < 1):
        raise NumbersError("maintenance_margin_rate must be in [0, 1), got %s" % mmr)

    one = Decimal(1)
    if sd == "long":
        liq = en * (one - one / lev) / (one - mmr)
        formula = "liq = entry * (1 - 1/leverage) / (1 - mmr)"
    else:
        liq = en * (one + one / lev) / (one + mmr)
        formula = "liq = entry * (1 + 1/leverage) / (1 + mmr)"

    distance = abs(liq - en)
    return Result(
        values={
            "liquidation_price": liq,
            "distance": distance,
            "distance_pct": distance / en * Decimal(100),
            "initial_margin_per_unit": en / lev,
        },
        inputs={"entry": en, "leverage": lev, "mmr": mmr},
        formula=formula,
        model="isolated margin, linear (quote-margined) contract, flat maintenance rate",
        assumptions=[
            "Isolated margin. Under cross margin the whole balance backs the position "
            "and this number is wrong.",
            "Flat maintenance rate. Most venues use tiers that rise with position size; "
            "read the venue's own table and pass the rate for your tier.",
            "Entry and exit fees, funding payments and unrealised PnL from other "
            "positions are excluded. Each of them moves the real liquidation closer.",
            "Treat the result as a boundary you should never approach, not a level you "
            "may trade against.",
        ],
    )


# --------------------------------------------------------------------------- #
def swap_output(amount_in: Num, reserve_in: Num, reserve_out: Num,
                fee_bps: Num = 30) -> Result:
    """Constant-product AMM output, with the price impact spelled out.

    ``out = Rout * a' / (Rin + a')`` where ``a' = a * (1 - fee)``. The number
    worth reading is not the output -- it is ``price_impact_pct``, which is how
    much worse than the quoted mid price the trade actually executes, and which
    grows with the square of size.
    """
    a = _positive(D(amount_in, "amount_in"), "amount_in")
    ri = _positive(D(reserve_in, "reserve_in"), "reserve_in")
    ro = _positive(D(reserve_out, "reserve_out"), "reserve_out")
    fee = D(fee_bps, "fee_bps")

    if not (0 <= fee < 10000):
        raise NumbersError("fee_bps must be in [0, 10000), got %s" % fee)

    fee_rate = fee / Decimal(10000)
    a_after = a * (Decimal(1) - fee_rate)
    out = ro * a_after / (ri + a_after)

    if out >= ro:  # unreachable with positive reserves, kept as a tripwire
        raise NumbersError("computed output drains the pool -- inputs are inconsistent")

    mid = ro / ri
    exec_price = out / a
    impact = (mid - exec_price) / mid * Decimal(100)

    return Result(
        values={
            "amount_out": out,
            "fee_paid": a * fee_rate,
            "mid_price": mid,
            "execution_price": exec_price,
            "price_impact_pct": impact,
            "pool_share_pct": a / ri * Decimal(100),
        },
        inputs={"amount_in": a, "reserve_in": ri, "reserve_out": ro, "fee_bps": fee},
        formula="out = reserve_out * a' / (reserve_in + a'),  a' = amount_in * (1 - fee)",
        model="constant product (x*y=k), single pool, no routing",
        assumptions=[
            "Reserves are read at one instant. Anything that trades before you moves "
            "them; the output you get is not the output computed here.",
            "No routing across pools and no concentrated liquidity. For a v3-style "
            "pool this understates available depth near the current tick.",
            "Gas, MEV and sandwich risk are not modelled. Large price_impact_pct is "
            "itself the invitation to be sandwiched.",
        ],
    )


# --------------------------------------------------------------------------- #
def impermanent_loss(price_ratio: Num) -> Result:
    """Loss of a 50/50 constant-product LP against simply holding.

    ``IL = 2*sqrt(r)/(1+r) - 1``, where r is the price of one asset relative to
    the other, divided by what it was at deposit. It is symmetric: a halving and
    a doubling hurt equally, which is the part people do not expect.
    """
    r = _positive(D(price_ratio, "price_ratio"), "price_ratio")
    with localcontext() as ctx:
        ctx.prec = 40
        il = Decimal(2) * r.sqrt() / (Decimal(1) + r) - Decimal(1)
    return Result(
        values={"impermanent_loss_pct": il * Decimal(100),
                "value_vs_hold": Decimal(1) + il},
        inputs={"price_ratio": r},
        formula="IL = 2*sqrt(r)/(1+r) - 1",
        model="50/50 constant-product pool, fees excluded",
        assumptions=[
            "Fees earned are NOT included and often exceed this loss -- the number "
            "alone is not a reason to leave a position.",
            "'Impermanent' only if the ratio returns; on withdrawal it is realised.",
            "Symmetric in r and 1/r: r=0.5 and r=2 give the same loss.",
        ],
    )


# --------------------------------------------------------------------------- #
def pnl(entry: Num, exit: Num, units: Num, side: str = "long",
        fee_bps: Num = 0, funding_paid: Num = 0, leverage: Num = 1) -> Result:
    """Realised profit after fees on both legs, and the return on margin."""
    en = _positive(D(entry, "entry"), "entry")
    ex = _positive(D(exit, "exit"), "exit")
    u = _positive(D(units, "units"), "units")
    lev = _positive(D(leverage, "leverage"), "leverage")
    fee = D(fee_bps, "fee_bps")
    fund = D(funding_paid, "funding_paid")
    sd = _side(side)

    if fee < 0:
        raise NumbersError("fee_bps cannot be negative, got %s" % fee)

    gross = u * (ex - en) if sd == "long" else u * (en - ex)
    fee_rate = fee / Decimal(10000)
    fees = (u * en + u * ex) * fee_rate
    net = gross - fees - fund
    margin = u * en / lev

    return Result(
        values={
            "gross_pnl": gross,
            "fees": fees,
            "funding_paid": fund,
            "net_pnl": net,
            "margin_used": margin,
            "return_on_margin_pct": net / margin * Decimal(100),
            "price_change_pct": (ex - en) / en * Decimal(100),
        },
        inputs={"entry": en, "exit": ex, "units": u, "fee_bps": fee, "leverage": lev},
        formula=("gross = units*(exit-entry) [long] ; "
                 "net = gross - (units*entry + units*exit)*fee - funding"),
        model="linear contract, fees charged on both legs at the same rate",
        assumptions=[
            "Maker and taker fees usually differ; pass the one you actually paid.",
            "funding_paid is a total you supply, not a rate this function projects.",
            "return_on_margin_pct is on margin, not on account equity.",
        ],
    )


# --------------------------------------------------------------------------- #
def apr_apy(rate_pct: Num, periods_per_year: Num = 365,
            direction: str = "apr_to_apy") -> Result:
    """Convert between a simple rate and a compounded one.

    Protocols quote whichever number is larger. At 100% APR daily compounding
    gives 171% APY; the gap is not a rounding difference, and comparing a quoted
    APY against a quoted APR is comparing two different things.
    """
    rate = D(rate_pct, "rate_pct")
    n = D(periods_per_year, "periods_per_year")
    d = str(direction).strip().lower()

    if rate <= -100:
        raise NumbersError("rate_pct must be greater than -100, got %s" % rate)
    if d not in ("apr_to_apy", "apy_to_apr"):
        raise NumbersError("direction must be 'apr_to_apy' or 'apy_to_apr', got %r"
                           % direction)

    with localcontext() as ctx:
        ctx.prec = 40
        r = rate / Decimal(100)
        if str(periods_per_year).strip().lower() in ("continuous", "inf"):
            raise NumbersError("for continuous compounding pass a large periods_per_year "
                               "explicitly, so the answer stays checkable")
        _positive(n, "periods_per_year")
        if d == "apr_to_apy":
            out = ((Decimal(1) + r / n) ** int(n) - Decimal(1)) if n == int(n) else \
                  (((Decimal(1) + r / n).ln() * n).exp() - Decimal(1))
            formula = "APY = (1 + APR/n)^n - 1"
            key = "apy_pct"
        else:
            base = Decimal(1) + r
            out = n * ((base.ln() / n).exp() - Decimal(1))
            formula = "APR = n * ((1 + APY)^(1/n) - 1)"
            key = "apr_pct"

    return Result(
        values={key: out * Decimal(100), "growth_factor": Decimal(1) + out},
        inputs={"rate_pct": rate, "periods_per_year": n},
        formula=formula,
        model="discrete compounding, %s periods per year" % n,
        assumptions=[
            "Assumes the rate holds for a full year. Most DeFi rates do not hold "
            "for a week.",
            "Rewards paid in a volatile token are quoted at today's price; the "
            "realised return depends on that price when you sell.",
        ],
    )


# --------------------------------------------------------------------------- #
def slippage_bounds(expected_out: Num, slippage_bps: Num = 50) -> Result:
    """The minimum output to sign for, given a tolerance."""
    e = _positive(D(expected_out, "expected_out"), "expected_out")
    s = D(slippage_bps, "slippage_bps")
    if not (0 <= s < 10000):
        raise NumbersError("slippage_bps must be in [0, 10000), got %s" % s)
    min_out = e * (Decimal(1) - s / Decimal(10000))
    return Result(
        values={"min_out": min_out, "max_give_up": e - min_out},
        inputs={"expected_out": e, "slippage_bps": s},
        formula="min_out = expected_out * (1 - slippage_bps/10000)",
        model="output-bounded swap",
        assumptions=[
            "A wide tolerance is what a sandwich attack spends. It is not a "
            "convenience setting; it is the size of the gift.",
            "If the trade fails at a tight bound, the honest response is a smaller "
            "trade, not a wider bound.",
        ],
    )


# --------------------------------------------------------------------------- #
def breakeven_move(fee_bps: Num = 10, funding_pct: Num = 0,
                   side: str = "long") -> Result:
    """How far price must move before a round trip is worth nothing.

    ``P(1-f) = E(1+f)`` for a long, so the move is ``2f/(1-f)`` of entry -- before
    funding. Small per trade, decisive over many.
    """
    fee = D(fee_bps, "fee_bps")
    fund = D(funding_pct, "funding_pct")
    sd = _side(side)
    if fee < 0 or fee >= 5000:
        raise NumbersError("fee_bps must be in [0, 5000), got %s" % fee)

    f = fee / Decimal(10000)
    move = Decimal(2) * f / (Decimal(1) - f) * Decimal(100)
    total = move + fund if sd == "long" else move + fund

    return Result(
        values={"breakeven_move_pct": move,
                "breakeven_with_funding_pct": total,
                "round_trip_fee_pct": Decimal(2) * f * Decimal(100)},
        inputs={"fee_bps": fee, "funding_pct": fund},
        formula="move = 2f/(1-f), f = fee_bps/10000",
        model="one round trip, same fee rate both legs",
        assumptions=[
            "Leverage does not change the required price move; it changes what that "
            "move is worth.",
            "funding_pct is a total you supply for the holding period.",
            "Slippage is not included and is often larger than the fee.",
        ],
    )
