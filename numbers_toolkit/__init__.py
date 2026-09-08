# -*- coding: utf-8 -*-
"""Numbers -- exact decimal arithmetic for the numbers that decide a trade.

An unofficial community toolkit for the UnifAI network. Not affiliated.

Two things at once:
  * a capability the ecosystem does not have -- a model can reason about a trade
    and cannot reliably compute one;
  * a worked example of `unifai-guard`, where each action's payloadDescription
    and its validation come from the same declaration.
"""
from .actions import ACTIONS, describe_all, run_action
from .math_core import NumbersError, Result

__version__ = "0.1.0"
__all__ = ["ACTIONS", "describe_all", "run_action", "NumbersError", "Result",
           "__version__"]
