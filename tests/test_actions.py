# -*- coding: utf-8 -*-
import asyncio
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "unifai-guard"))

from numbers_toolkit.actions import ACTIONS, describe_all, run_action
from numbers_toolkit import server


class TestDescriptions(unittest.TestCase):
    def test_every_action_describes_itself(self):
        d = describe_all()
        self.assertEqual(len(d), len(ACTIONS))
        for name, spec in d.items():
            self.assertEqual(spec["action"], name)
            self.assertTrue(spec["actionDescription"].strip())
            self.assertTrue(spec["payloadDescription"])

    def test_payload_description_is_the_shape_unifai_wants(self):
        for spec in describe_all().values():
            for field, fs in spec["payloadDescription"].items():
                self.assertEqual(set(fs), {"type", "description"})
                self.assertIn(fs["type"],
                              ("string", "number", "integer", "boolean", "array", "object"))

    def test_constraints_are_written_into_the_sentence(self):
        """The reason the schema generates the description instead of duplicating it."""
        d = describe_all()["position_size"]["payloadDescription"]
        self.assertIn("at most 100", d["risk_pct"]["description"])
        self.assertIn("Required", d["entry"]["description"])
        self.assertIn("Optional", d["side"]["description"])
        self.assertIn('"long", "short"', d["side"]["description"])

    def test_optional_fields_state_their_default(self):
        d = describe_all()["swap_output"]["payloadDescription"]
        self.assertIn("30", d["fee_bps"]["description"])

    def test_json_schema_is_available_too(self):
        js = describe_all()["position_size"]["jsonSchema"]
        self.assertEqual(js["additionalProperties"], False)
        self.assertIn("equity", js["required"])
        self.assertNotIn("side", js["required"])

    def test_descriptions_are_not_empty_boilerplate(self):
        for name, desc, _s, _f, _i in ACTIONS:
            self.assertGreater(len(desc), 60, name)


class TestRunAction(unittest.TestCase):
    def test_happy_path(self):
        out = run_action("position_size",
                         {"equity": 10000, "risk_pct": 1, "entry": 50, "stop": 45})
        self.assertTrue(out["ok"])
        self.assertEqual(out["values"]["units"], "20")
        self.assertIn("formula", out)
        self.assertIn("assumptions", out)

    def test_unknown_action_lists_what_exists(self):
        out = run_action("drain_wallet", {})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "unknown_action")
        self.assertIn("position_size", out["message"])

    def test_missing_required_field(self):
        out = run_action("position_size", {"equity": 10000})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "invalid_payload")
        fields = {p["field"] for p in out["problems"]}
        self.assertIn("risk_pct", fields)
        self.assertIn("entry", fields)

    def test_all_problems_come_back_at_once(self):
        out = run_action("position_size",
                         {"equity": -1, "risk_pct": 200, "entry": 50, "stop": 45})
        codes = {p["code"] for p in out["problems"]}
        self.assertIn("minimum", codes)
        self.assertIn("maximum", codes)

    def test_hallucinated_field_is_rejected(self):
        out = run_action("position_size",
                         {"equity": 10000, "risk_pct": 1, "entry": 50, "stop": 45,
                          "leverage": 10})
        self.assertFalse(out["ok"])
        self.assertEqual([p["code"] for p in out["problems"]], ["unknown_field"])

    def test_wrong_type_is_rejected(self):
        out = run_action("position_size",
                         {"equity": "lots", "risk_pct": 1, "entry": 50, "stop": 45})
        self.assertFalse(out["ok"])
        self.assertEqual(out["problems"][0]["code"], "type")

    def test_bad_enum_value(self):
        out = run_action("position_size",
                         {"equity": 1000, "risk_pct": 1, "entry": 50, "stop": 45,
                          "side": "sideways"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["problems"][0]["code"], "enum")

    def test_inconsistent_inputs_refuse_rather_than_guess(self):
        out = run_action("position_size",
                         {"equity": 10000, "risk_pct": 1, "entry": 50, "stop": 55,
                          "side": "long"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["error"], "inconsistent_inputs")
        self.assertIn("target", out["message"])
        self.assertIn("Refusing is deliberate", out["hint"])

    def test_defaults_are_applied(self):
        out = run_action("swap_output",
                         {"amount_in": 1000, "reserve_in": 100000, "reserve_out": 100000})
        self.assertEqual(out["inputs"]["fee_bps"], "30")

    def test_never_raises_on_anything(self):
        """A model on the other end cannot act on a traceback."""
        for payload in ({}, {"equity": None}, {"a": [1, 2]}, {"equity": {"x": 1}}):
            for name, *_ in ACTIONS:
                out = run_action(name, payload)
                self.assertIn("ok", out)

    def test_none_payload(self):
        self.assertFalse(run_action("pnl", None)["ok"])

    def test_every_action_answers_a_good_payload(self):
        good = {
            "position_size": {"equity": 10000, "risk_pct": 1, "entry": 50, "stop": 45},
            "liquidation_price": {"entry": 100, "leverage": 10},
            "swap_output": {"amount_in": 100, "reserve_in": 10000, "reserve_out": 10000},
            "impermanent_loss": {"price_ratio": 2},
            "pnl": {"entry": 100, "exit": 110, "units": 2},
            "apr_apy": {"rate_pct": 100},
            "slippage_bounds": {"expected_out": 1000},
            "breakeven_move": {},
        }
        self.assertEqual(set(good), {a[0] for a in ACTIONS},
                         "an action was added without a smoke test")
        for name, payload in good.items():
            out = run_action(name, payload)
            self.assertTrue(out["ok"], "%s: %s" % (name, out))
            self.assertTrue(out["values"])

    def test_output_is_json_serialisable(self):
        """It goes over the wire as JSON; Decimal would not survive."""
        for name, *_ in ACTIONS:
            out = run_action(name, {})
            json.dumps(out)


class TestServerWiring(unittest.TestCase):
    def test_dry_run_needs_nothing(self):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = server.dry_run()
        text = buf.getvalue()
        self.assertEqual(rc, 0)
        for name, *_ in ACTIONS:
            self.assertIn(name, text)
        self.assertIn("Nothing above needed a key", text)

    def test_missing_sdk_says_so_clearly(self):
        try:
            import unifai  # noqa: F401
            self.skipTest("the SDK is installed here")
        except ImportError:
            pass
        with self.assertRaises(server.SetupError) as c:
            server._import_sdk()
        self.assertIn("pip install", str(c.exception))
        self.assertIn("--dry-run", str(c.exception))

    def test_missing_key_points_at_the_console(self):
        old = os.environ.pop("UNIFAI_TOOLKIT_API_KEY", None)
        try:
            with self.assertRaises(server.SetupError) as c:
                server._api_key(None)
            self.assertIn("console.unifai.network", str(c.exception))
            self.assertIn("free", str(c.exception))
        finally:
            if old is not None:
                os.environ["UNIFAI_TOOLKIT_API_KEY"] = old

    def test_explicit_key_wins(self):
        self.assertEqual(server._api_key("abc123"), "abc123")

    def test_env_key_is_read(self):
        os.environ["UNIFAI_TOOLKIT_API_KEY"] = " envkey "
        try:
            self.assertEqual(server._api_key(None), "envkey")
        finally:
            del os.environ["UNIFAI_TOOLKIT_API_KEY"]

    def test_each_handler_answers_as_its_own_action(self):
        """Guards against the late-binding closure bug in the registration loop.

        Bound wrongly, all eight handlers answer as the last action -- and every
        one of them still returns valid JSON, so a smoke test would pass.
        """
        class FakeCtx:
            agent_id = "test"

            @staticmethod
            def Result(text):
                return text

        for name, *_ in ACTIONS:
            handler = server._handler_for(name)
            out = json.loads(asyncio.run(handler(FakeCtx(), {})))
            self.assertEqual(out.get("action", name if out["ok"] else name), name)
            # unknown_action would mean the name did not survive the closure
            self.assertNotEqual(out.get("error"), "unknown_action")

    def test_main_dry_run_returns_zero(self):
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            self.assertEqual(server.main(["--dry-run"]), 0)


if __name__ == "__main__":
    unittest.main()
