# -*- coding: utf-8 -*-
"""The eight actions, each declared once.

Every schema below produces both the ``payloadDescription`` UnifAI serves to
agents and the validation that runs before the handler sees anything. That is
the whole argument for ``unifai-guard`` in practice: this file is short *because*
the descriptions are generated, not despite it.

Handlers never raise into the transport. A bad input comes back as a structured
``ok: false`` with the reason, because an agent can act on a reason and cannot
act on a stack trace.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple

from unifai_guard import Field, Schema

from . import math_core as m
from .math_core import NumbersError

__all__ = ["ACTIONS", "run_action", "describe_all", "Action"]


# --------------------------------------------------------------------------- #
#  Shared field pieces
# --------------------------------------------------------------------------- #
# NB: kein monetary=True irgendwo in dieser Datei. Das Flag laesst unifai-guard
# den Satz "this field moves value" in die Beschreibung schreiben und laesst die
# Betrags-Tore greifen. Beides waere hier unwahr: dieses Toolkit rechnet, es
# bewegt nichts. Ein falscher Satz in einer Beschreibung, die ein Agent liest,
# ist genau die Sorte Fehler, gegen die das Paket nebenan gebaut wurde.
def _price(what: str, example: float = 150.25) -> Field:
    return Field.number(what, minimum=0, exclusive_minimum=True,
                        examples=[example])


def _side() -> Field:
    return Field.string(
        "Direction of the position.",
        enum=["long", "short"], required=False, default="long",
    )


def _bps(what: str, default: int, cap: int = 10000) -> Field:
    return Field.integer(
        what + " Expressed in basis points: 1 bp = 0.01%, so 50 means 0.5%.",
        minimum=0, maximum=cap - 1, required=False, default=default,
    )


# --------------------------------------------------------------------------- #
#  Schemas
# --------------------------------------------------------------------------- #
S_POSITION_SIZE = Schema(
    equity=Field.number(
        "Total account equity in quote currency, e.g. USDT.",
        minimum=0, exclusive_minimum=True, examples=[5000],
    ),
    risk_pct=Field.number(
        "Percentage of equity to lose if the stop is hit. Typical values are 0.5 "
        "to 2. This is a percentage, not a fraction: pass 1 for one percent.",
        minimum=0, exclusive_minimum=True, maximum=100, examples=[1],
    ),
    entry=_price("Intended entry price.", 150.25),
    stop=_price("Stop-loss price. Must be below entry for a long, above for a "
                "short. Never equal to entry.", 142.50),
    side=_side(),
)

S_LIQUIDATION = Schema(
    entry=_price("Entry price of the position."),
    leverage=Field.number(
        "Leverage as a multiple, e.g. 10 for 10x.",
        minimum=1, maximum=1000, examples=[10],
    ),
    side=_side(),
    maintenance_margin_rate=Field.number(
        "Maintenance margin rate as a fraction, e.g. 0.005 for 0.5%. Read it from "
        "the venue's own margin tier table for your position size; the default is "
        "a common small-tier value and is not a promise about your venue.",
        minimum=0, maximum=0.5, required=False, default=0.005,
    ),
)

S_SWAP = Schema(
    amount_in=Field.number(
        "Amount of the input token, in the token's own units.",
        minimum=0, exclusive_minimum=True, examples=[1000],
    ),
    reserve_in=Field.number(
        "Pool reserve of the input token, read at the current block.",
        minimum=0, exclusive_minimum=True, examples=[500000],
    ),
    reserve_out=Field.number(
        "Pool reserve of the output token, read at the current block.",
        minimum=0, exclusive_minimum=True, examples=[250000],
    ),
    fee_bps=_bps("Pool fee.", 30),
)

S_IL = Schema(
    price_ratio=Field.number(
        "Current price of the pair's assets relative to each other, divided by "
        "what it was at deposit. 2 means one asset doubled against the other; 0.5 "
        "means it halved. The result is the same for both.",
        minimum=0, exclusive_minimum=True, examples=[2],
    ),
)

S_PNL = Schema(
    entry=_price("Entry price.", 150.25),
    exit=_price("Exit price.", 163.00),
    units=Field.number(
        "Position size in base units, not in quote currency.",
        minimum=0, exclusive_minimum=True, examples=[2.5],
    ),
    side=_side(),
    fee_bps=_bps("Fee rate charged on each leg.", 0, cap=1000),
    funding_paid=Field.number(
        "Total funding paid over the holding period, in quote currency. Negative "
        "if you received funding.",
        required=False, default=0,
    ),
    leverage=Field.number(
        "Leverage used, for the return-on-margin figure.",
        minimum=1, required=False, default=1,
    ),
)

S_APR = Schema(
    rate_pct=Field.number(
        "The quoted rate as a percentage, e.g. 12.5 for 12.5%.",
        minimum=-99.999999, examples=[100],
    ),
    periods_per_year=Field.integer(
        "Compounding periods per year: 365 daily, 52 weekly, 12 monthly.",
        minimum=1, maximum=525600, required=False, default=365,
    ),
    direction=Field.string(
        "Which way to convert.",
        enum=["apr_to_apy", "apy_to_apr"], required=False, default="apr_to_apy",
    ),
)

S_SLIPPAGE = Schema(
    expected_out=Field.number(
        "Expected output amount at the quoted price.",
        minimum=0, exclusive_minimum=True, examples=[1000],
    ),
    slippage_bps=_bps("Tolerance you are willing to accept.", 50),
)

S_BREAKEVEN = Schema(
    fee_bps=_bps("Fee rate charged on each leg.", 10, cap=5000),
    funding_pct=Field.number(
        "Total funding cost over the holding period, as a percentage of notional.",
        required=False, default=0,
    ),
    side=_side(),
)


# --------------------------------------------------------------------------- #
#  Wiring
# --------------------------------------------------------------------------- #
Action = Tuple[str, str, Schema, Callable[..., m.Result], bool]

#  (name, one-line description, schema, function, irreversible)
ACTIONS: List[Action] = [
    ("position_size",
     "Given account equity, a risk percentage, an entry and a stop, return the "
     "position size that loses exactly that percentage if the stop is hit. Exact "
     "decimal arithmetic; returns the formula and the assumptions alongside the "
     "number.",
     S_POSITION_SIZE, m.position_size, False),

    ("liquidation_price",
     "Liquidation price of an isolated linear perpetual position, derived rather "
     "than approximated. Returns the distance in percent and names every "
     "assumption that would move it.",
     S_LIQUIDATION, m.liquidation_price, False),

    ("swap_output",
     "Constant-product AMM output for a given input and pool reserves, with the "
     "fee applied and the price impact stated separately. Price impact is the "
     "number worth reading.",
     S_SWAP, m.swap_output, False),

    ("impermanent_loss",
     "Loss of a 50/50 constant-product LP position against simply holding, for a "
     "given price ratio change. Fees earned are not included and often exceed it.",
     S_IL, m.impermanent_loss, False),

    ("pnl",
     "Realised profit or loss after fees on both legs and funding, plus the "
     "return on margin.",
     S_PNL, m.pnl, False),

    ("apr_apy",
     "Convert between a simple annual rate and a compounded one. Protocols quote "
     "whichever number is larger; comparing a quoted APY against a quoted APR "
     "compares two different things.",
     S_APR, m.apr_apy, False),

    ("slippage_bounds",
     "Minimum acceptable output for a given expected output and slippage "
     "tolerance, i.e. the number to sign for.",
     S_SLIPPAGE, m.slippage_bounds, False),

    ("breakeven_move",
     "How far price must move before a round trip is worth nothing, given fees "
     "and funding.",
     S_BREAKEVEN, m.breakeven_move, False),
]

_BY_NAME: Dict[str, Action] = {a[0]: a for a in ACTIONS}


def describe_all() -> Dict[str, Dict[str, Any]]:
    """Everything a toolkit registration needs, generated from the declarations."""
    return {
        name: {
            "action": name,
            "actionDescription": desc,
            "payloadDescription": schema.to_payload_description(),
            "jsonSchema": schema.to_json_schema(),
            "irreversible": irreversible,
        }
        for name, desc, schema, _fn, irreversible in ACTIONS
    }


def run_action(name: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Validate, compute, and answer in a shape an agent can use.

    Never raises. A refusal is an answer with a reason in it -- the caller is a
    model, and a model that receives a traceback will invent what it means.
    """
    entry = _BY_NAME.get(name)
    if entry is None:
        return {
            "ok": False,
            "error": "unknown_action",
            "message": "no action named %r; available: %s"
                       % (name, ", ".join(sorted(_BY_NAME))),
        }
    _n, _d, schema, fn, _irr = entry

    problems = schema.validate(payload or {})
    if problems:
        return {
            "ok": False,
            "error": "invalid_payload",
            "message": "the payload does not match this action's schema",
            "problems": [{"field": p.path, "code": p.code, "detail": p.message}
                         for p in problems],
        }

    clean = schema.validate_or_raise(payload or {})
    try:
        result = fn(**clean)
    except NumbersError as exc:
        return {
            "ok": False,
            "error": "inconsistent_inputs",
            "message": str(exc),
            "hint": "These inputs do not describe a situation with an answer. "
                    "Refusing is deliberate: a plausible number here would be "
                    "acted on.",
        }
    except (ArithmeticError, ValueError) as exc:  # pragma: no cover - safety net
        return {"ok": False, "error": "arithmetic", "message": str(exc)}

    out = result.as_dict()
    out["ok"] = True
    out["action"] = name
    return out
