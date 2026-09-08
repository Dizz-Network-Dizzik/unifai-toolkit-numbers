# -*- coding: utf-8 -*-
"""Start here.

    python run.py --dry-run     see all eight actions, no key needed
    python run.py               serve (needs UNIFAI_TOOLKIT_API_KEY)
    python run.py --key XYZ     serve with the key passed directly
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# unifai-guard is a sibling checkout until it is installed from an index.
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "unifai-guard"))

try:
    from numbers_toolkit.server import main
except ImportError as exc:
    print("")
    print("  Could not import the toolkit: %s" % exc)
    print("  unifai-guard must sit next to this folder, or be installed:")
    print("      pip install -e ../unifai-guard")
    print("")
    raise SystemExit(1)

if __name__ == "__main__":
    raise SystemExit(main())
