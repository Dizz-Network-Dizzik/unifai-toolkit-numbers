# -*- coding: utf-8 -*-
"""Wiring to the UnifAI network.

Everything that matters is in :mod:`math_core` and :mod:`actions`, and both run
without this file, without a key and without a network. That is deliberate: the
part that can be wrong is the arithmetic, and arithmetic should be testable
without an account.

This module is the thin part. It reads the action declarations, hands UnifAI the
generated ``payload_description`` for each, and routes calls back into the same
validation the tests use.

Signatures follow unifai-sdk-py's own README (read 08.09.2026):

    import unifai
    toolkit = unifai.Toolkit(api_key='xxx')
    await toolkit.update_toolkit(name=..., description=...)

    @toolkit.action(action=..., action_description=..., payload_description={...})
    async def echo(ctx: unifai.ActionContext, payload={}):
        return ctx.Result(...)

    await toolkit.run()

If the SDK's shape has moved since, this file fails loudly with the name that did
not resolve rather than guessing around it.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, Dict, Optional

from .actions import ACTIONS, describe_all, run_action

TOOLKIT_NAME = "Numbers"
TOOLKIT_DESCRIPTION = (
    "Exact decimal arithmetic for the numbers that decide a trade: position size "
    "from risk, liquidation price, AMM output and price impact, impermanent loss, "
    "PnL after fees, APR/APY, slippage bounds, breakeven. Every answer carries the "
    "formula it used, the inputs it used, and the assumptions that would change it. "
    "Refuses inconsistent inputs instead of returning a plausible number."
)

_CONSOLE = "https://console.unifai.network"


class SetupError(RuntimeError):
    """Something about the environment is missing, and guessing would not help."""


def _import_sdk():
    try:
        import unifai  # noqa: F401
    except ImportError:
        raise SetupError(
            "the unifai SDK is not installed.\n"
            "    pip install unifai-sdk\n"
            "Everything except serving works without it: try --dry-run."
        )
    for name in ("Toolkit", "ActionContext"):
        if not hasattr(unifai, name):
            raise SetupError(
                "the installed unifai SDK has no %r. This file was written against "
                "the API documented in unifai-sdk-py's README on 08.09.2026; the "
                "SDK has moved. Check the current README rather than trusting "
                "this wiring." % name
            )
    return unifai


def _api_key(explicit: Optional[str] = None) -> str:
    key = explicit or os.environ.get("UNIFAI_TOOLKIT_API_KEY", "").strip()
    if not key:
        raise SetupError(
            "no toolkit API key.\n"
            "    1. open %s and create a toolkit (it is free)\n"
            "    2. copy the toolkit API key\n"
            "    3. set UNIFAI_TOOLKIT_API_KEY, or pass --key\n"
            "The key is not needed to run the tests or --dry-run." % _CONSOLE
        )
    return key


def _handler_for(name: str):
    """One closure per action.

    Bound through a factory rather than in the loop body: a late-binding closure
    would register eight handlers that all answer as the last action, and every
    one of them would look fine in a smoke test.
    """

    async def handler(ctx: Any, payload: Optional[Dict[str, Any]] = None) -> Any:
        result = run_action(name, payload or {})
        return ctx.Result(json.dumps(result, ensure_ascii=False))

    handler.__name__ = "action_%s" % name
    return handler


async def build(api_key: Optional[str] = None):
    """Create the toolkit and register every action. Returns it, unstarted."""
    unifai = _import_sdk()
    toolkit = unifai.Toolkit(api_key=_api_key(api_key))
    await toolkit.update_toolkit(name=TOOLKIT_NAME, description=TOOLKIT_DESCRIPTION)

    for name, description, schema, _fn, _irr in ACTIONS:
        toolkit.action(
            action=name,
            action_description=description,
            payload_description=schema.to_payload_description(),
        )(_handler_for(name))

    return toolkit


async def serve(api_key: Optional[str] = None) -> None:
    toolkit = await build(api_key)
    print("  %s is live with %d actions. Ctrl+C to stop." % (TOOLKIT_NAME, len(ACTIONS)))
    await toolkit.run()


def dry_run() -> int:
    """Show exactly what would be registered. No key, no network, no SDK."""
    described = describe_all()
    print("")
    print("  TOOLKIT  %s" % TOOLKIT_NAME)
    print("  %s" % TOOLKIT_DESCRIPTION)
    print("")
    print("  %d actions, every description generated from its own schema:" % len(described))
    for name, spec in described.items():
        print("")
        print("  " + "-" * 70)
        print("  %s" % name)
        print("  " + "-" * 70)
        for line in _wrap(spec["actionDescription"], 68):
            print("    %s" % line)
        for field, fs in spec["payloadDescription"].items():
            print("")
            print("    %s  (%s)" % (field, fs["type"]))
            for line in _wrap(fs["description"], 64):
                print("        %s" % line)
    print("")
    print("  " + "-" * 70)
    print("  Nothing above needed a key. To serve it: set UNIFAI_TOOLKIT_API_KEY")
    print("  (free at %s) and run without --dry-run." % _CONSOLE)
    print("")
    return 0


def _wrap(text: str, width: int):
    words, line, out = text.split(), "", []
    for w in words:
        if len(line) + len(w) + 1 > width:
            out.append(line)
            line = w
        else:
            line = (line + " " + w).strip()
    if line:
        out.append(line)
    return out


def main(argv: Optional[list] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--help" in argv or "-h" in argv:
        print(__doc__)
        return 0
    if "--dry-run" in argv:
        return dry_run()

    key = None
    if "--key" in argv:
        i = argv.index("--key")
        if i + 1 >= len(argv):
            print("  --key needs a value")
            return 2
        key = argv[i + 1]

    try:
        asyncio.run(serve(key))
    except SetupError as exc:
        print("")
        print("  Not started: %s" % exc)
        print("")
        return 1
    except KeyboardInterrupt:
        print("\n  stopped.")
    return 0
