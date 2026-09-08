# -*- coding: utf-8 -*-
import os
import sys
import unittest
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "unifai-guard"))

from numbers_toolkit import math_core as m
from numbers_toolkit.math_core import D, NumbersError


def close(a, b, places=8):
    return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal(10) ** -places


class TestPositionSize(unittest.TestCase):
    def test_worked_example(self):
        # 10000 equity, 1% risk = 100 at risk. Entry 50, stop 45 -> 5 per unit.
        r = m.position_size(10000, 1, 50, 45)
        self.assertEqual(r.values["units"], Decimal(20))
        self.assertEqual(r.values["notional"], Decimal(1000))
        self.assertEqual(r.values["risk_amount"], Decimal(100))

    def test_short_side(self):
        r = m.position_size(10000, 2, 100, 105, side="short")
        self.assertEqual(r.values["units"], Decimal(40))

    def test_leverage_required_is_reported(self):
        r = m.position_size(1000, 1, 100, 99)
        # 10 at risk / 1 per unit = 10 units = 1000 notional on 1000 equity
        self.assertEqual(r.values["leverage_required"], Decimal(1))

    def test_tighter_stop_means_bigger_position(self):
        wide = m.position_size(10000, 1, 100, 90).values["units"]
        tight = m.position_size(10000, 1, 100, 99).values["units"]
        self.assertGreater(tight, wide)

    def test_refuses_stop_on_the_wrong_side_of_entry(self):
        with self.assertRaises(NumbersError) as c:
            m.position_size(10000, 1, 50, 55, side="long")
        self.assertIn("target", str(c.exception))
        with self.assertRaises(NumbersError):
            m.position_size(10000, 1, 50, 45, side="short")

    def test_refuses_zero_distance(self):
        with self.assertRaises(NumbersError):
            m.position_size(10000, 1, 50, 50)

    def test_refuses_absurd_risk(self):
        for bad in (0, -1, 101):
            with self.assertRaises(NumbersError):
                m.position_size(10000, bad, 50, 45)

    def test_carries_its_own_formula_and_caveats(self):
        r = m.position_size(10000, 1, 50, 45)
        self.assertIn("units =", r.formula)
        self.assertTrue(any("stop fills" in a for a in r.assumptions))


class TestLiquidation(unittest.TestCase):
    def test_long_matches_the_derivation(self):
        # E=100, L=10, mmr=0 -> P = 100*(1-0.1)/1 = 90
        r = m.liquidation_price(100, 10, "long", 0)
        self.assertEqual(r.values["liquidation_price"], Decimal(90))

    def test_short_matches_the_derivation(self):
        # E=100, L=10, mmr=0 -> P = 100*(1+0.1)/1 = 110
        r = m.liquidation_price(100, 10, "short", 0)
        self.assertEqual(r.values["liquidation_price"], Decimal(110))

    def test_maintenance_margin_moves_liquidation_closer(self):
        without = m.liquidation_price(100, 10, "long", 0).values["liquidation_price"]
        with_mm = m.liquidation_price(100, 10, "long", "0.005").values["liquidation_price"]
        self.assertGreater(with_mm, without)  # closer to entry from below

    def test_one_times_leverage_liquidates_at_zero_without_mmr(self):
        r = m.liquidation_price(100, 1, "long", 0)
        self.assertEqual(r.values["liquidation_price"], Decimal(0))

    def test_higher_leverage_is_closer(self):
        far = m.liquidation_price(100, 2, "long").values["distance_pct"]
        near = m.liquidation_price(100, 50, "long").values["distance_pct"]
        self.assertGreater(far, near)

    def test_exact_form_differs_from_the_common_shortcut_at_high_leverage(self):
        """The reason the derivation is in the docstring."""
        entry, lev, mmr = Decimal(100), Decimal(100), Decimal("0.005")
        exact = m.liquidation_price(entry, lev, "long", mmr).values["liquidation_price"]
        shortcut = entry * (Decimal(1) - Decimal(1) / lev + mmr)
        self.assertNotEqual(exact, shortcut)
        self.assertLess(abs(exact - shortcut), Decimal("0.01"))  # small, not zero

    def test_refuses_leverage_below_one(self):
        with self.assertRaises(NumbersError):
            m.liquidation_price(100, "0.5")

    def test_names_its_model(self):
        r = m.liquidation_price(100, 10)
        self.assertIn("isolated", r.model)
        self.assertTrue(any("cross" in a.lower() for a in r.assumptions))


class TestSwapOutput(unittest.TestCase):
    def test_no_fee_constant_product(self):
        # in=1000, Rin=100000, Rout=100000 -> out = 100000*1000/101000
        r = m.swap_output(1000, 100000, 100000, 0)
        self.assertTrue(close(r.values["amount_out"], Decimal(100000000) / Decimal(101000), 6))

    def test_fee_reduces_output(self):
        free = m.swap_output(1000, 100000, 100000, 0).values["amount_out"]
        paid = m.swap_output(1000, 100000, 100000, 30).values["amount_out"]
        self.assertLess(paid, free)

    def test_price_impact_grows_with_size(self):
        small = m.swap_output(100, 100000, 100000).values["price_impact_pct"]
        big = m.swap_output(10000, 100000, 100000).values["price_impact_pct"]
        self.assertGreater(big, small * 10)

    def test_output_never_drains_the_pool(self):
        r = m.swap_output(10 ** 12, 1000, 1000, 0)
        self.assertLess(r.values["amount_out"], Decimal(1000))

    def test_fee_paid_is_reported(self):
        r = m.swap_output(1000, 100000, 100000, 30)
        self.assertEqual(r.values["fee_paid"], Decimal(3))

    def test_refuses_bad_fee(self):
        with self.assertRaises(NumbersError):
            m.swap_output(1000, 100000, 100000, 10000)


class TestImpermanentLoss(unittest.TestCase):
    def test_no_change_no_loss(self):
        self.assertEqual(m.impermanent_loss(1).values["impermanent_loss_pct"], Decimal(0))

    def test_known_values(self):
        # r=2 -> 2*sqrt(2)/3 - 1 = -0.0572 -> -5.72%
        r2 = m.impermanent_loss(2).values["impermanent_loss_pct"]
        self.assertTrue(close(r2, Decimal("-5.7190958417936"), 8))
        # r=4 -> 2*2/5 - 1 = -0.2 -> -20%
        self.assertEqual(m.impermanent_loss(4).values["impermanent_loss_pct"], Decimal(-20))

    def test_symmetric_in_r_and_one_over_r(self):
        a = m.impermanent_loss(2).values["impermanent_loss_pct"]
        b = m.impermanent_loss("0.5").values["impermanent_loss_pct"]
        self.assertTrue(close(a, b, 20))

    def test_always_a_loss(self):
        for r in ("0.1", "0.5", "1.5", 3, 10):
            self.assertLessEqual(m.impermanent_loss(r).values["impermanent_loss_pct"],
                                 Decimal(0))

    def test_says_fees_are_excluded(self):
        self.assertTrue(any("Fees earned" in a
                            for a in m.impermanent_loss(2).assumptions))

    def test_refuses_non_positive_ratio(self):
        with self.assertRaises(NumbersError):
            m.impermanent_loss(0)


class TestPnl(unittest.TestCase):
    def test_long_profit(self):
        r = m.pnl(100, 110, 2)
        self.assertEqual(r.values["gross_pnl"], Decimal(20))
        self.assertEqual(r.values["net_pnl"], Decimal(20))

    def test_short_profit(self):
        r = m.pnl(100, 90, 2, side="short")
        self.assertEqual(r.values["gross_pnl"], Decimal(20))

    def test_fees_on_both_legs(self):
        r = m.pnl(100, 110, 2, fee_bps=10)
        # (200 + 220) * 0.001 = 0.42
        self.assertEqual(r.values["fees"], Decimal("0.42"))
        self.assertEqual(r.values["net_pnl"], Decimal("19.58"))

    def test_return_on_margin_uses_leverage(self):
        flat = m.pnl(100, 110, 2, leverage=1).values["return_on_margin_pct"]
        levd = m.pnl(100, 110, 2, leverage=10).values["return_on_margin_pct"]
        self.assertEqual(levd, flat * 10)

    def test_funding_is_subtracted(self):
        r = m.pnl(100, 110, 2, funding_paid=5)
        self.assertEqual(r.values["net_pnl"], Decimal(15))

    def test_decimal_exactness(self):
        """The reason this module exists: 0.1 + 0.2 must be 0.3."""
        r = m.pnl("0.1", "0.4", 1)
        self.assertEqual(r.values["gross_pnl"], Decimal("0.3"))


class TestAprApy(unittest.TestCase):
    def test_hundred_percent_apr_daily(self):
        r = m.apr_apy(100, 365, "apr_to_apy")
        self.assertTrue(close(r.values["apy_pct"], Decimal("171.4567482"), 5))

    def test_round_trip(self):
        apy = m.apr_apy(37, 12, "apr_to_apy").values["apy_pct"]
        apr = m.apr_apy(apy, 12, "apy_to_apr").values["apr_pct"]
        self.assertTrue(close(apr, Decimal(37), 12))

    def test_apy_always_at_least_apr_for_positive_rates(self):
        for rate in (1, 5, 50, 200):
            apy = m.apr_apy(rate, 365).values["apy_pct"]
            self.assertGreaterEqual(apy, Decimal(rate))

    def test_single_period_is_identity(self):
        self.assertTrue(close(m.apr_apy(10, 1).values["apy_pct"], Decimal(10), 20))

    def test_refuses_unknown_direction(self):
        with self.assertRaises(NumbersError):
            m.apr_apy(10, 365, "sideways")

    def test_refuses_rate_at_minus_hundred(self):
        with self.assertRaises(NumbersError):
            m.apr_apy(-100)


class TestSlippageAndBreakeven(unittest.TestCase):
    def test_min_out(self):
        r = m.slippage_bounds(1000, 50)
        self.assertEqual(r.values["min_out"], Decimal(995))
        self.assertEqual(r.values["max_give_up"], Decimal(5))

    def test_zero_tolerance(self):
        self.assertEqual(m.slippage_bounds(1000, 0).values["min_out"], Decimal(1000))

    def test_calls_a_wide_bound_what_it_is(self):
        self.assertTrue(any("sandwich" in a for a in m.slippage_bounds(1000).assumptions))

    def test_breakeven_exact(self):
        # f = 0.001 -> 2f/(1-f) = 0.002002002... -> 0.2002002...%
        r = m.breakeven_move(10)
        self.assertTrue(close(r.values["breakeven_move_pct"], Decimal("0.2002002002"), 8))

    def test_breakeven_with_funding(self):
        r = m.breakeven_move(10, funding_pct=1)
        self.assertTrue(close(r.values["breakeven_with_funding_pct"],
                              Decimal("1.2002002002"), 8))

    def test_zero_fee_zero_move(self):
        self.assertEqual(m.breakeven_move(0).values["breakeven_move_pct"], Decimal(0))

    def test_says_leverage_does_not_change_the_move(self):
        self.assertTrue(any("Leverage does not change" in a
                            for a in m.breakeven_move(10).assumptions))


class TestInputHandling(unittest.TestCase):
    def test_accepts_strings_ints_floats_decimals(self):
        for v in ("100", 100, 100.0, Decimal(100)):
            self.assertEqual(D(v), Decimal(100))

    def test_rejects_booleans(self):
        with self.assertRaises(NumbersError):
            D(True, "amount")

    def test_rejects_nonsense(self):
        for bad in ("abc", None, [1], {"a": 1}):
            with self.assertRaises(NumbersError):
                D(bad, "x")

    def test_rejects_infinity_and_nan(self):
        for bad in ("Infinity", "-Infinity", "NaN"):
            with self.assertRaises(NumbersError):
                D(bad, "x")

    def test_side_aliases(self):
        self.assertEqual(m.position_size(1000, 1, 50, 45, "buy").values["units"],
                         m.position_size(1000, 1, 50, 45, "long").values["units"])

    def test_bad_side(self):
        with self.assertRaises(NumbersError):
            m.position_size(1000, 1, 50, 45, "sideways")

    def test_every_result_carries_formula_model_and_inputs(self):
        results = [
            m.position_size(1000, 1, 50, 45), m.liquidation_price(100, 10),
            m.swap_output(10, 1000, 1000), m.impermanent_loss(2),
            m.pnl(100, 110, 1), m.apr_apy(10), m.slippage_bounds(100),
            m.breakeven_move(10),
        ]
        for r in results:
            self.assertTrue(r.formula, r)
            self.assertTrue(r.model, r)
            self.assertTrue(r.inputs, r)
            self.assertTrue(r.assumptions, r)

    def test_as_dict_returns_strings_not_floats(self):
        """A float in the response would undo the whole point."""
        d = m.position_size(10000, 1, 50, 45).as_dict()
        for v in d["values"].values():
            self.assertIsInstance(v, str)


if __name__ == "__main__":
    unittest.main()
