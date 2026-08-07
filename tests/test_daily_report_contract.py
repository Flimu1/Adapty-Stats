import unittest


class TestDailyPortfolioContract(unittest.TestCase):
    def test_loads_exact_three_canonical_slots_and_hides_keys_from_repr(self):
        from daily_report_contract import CANONICAL_APP_NAMES, load_daily_portfolio

        env = {
            "ADAPTY_API_KEY_APP1": "secret-one",
            "ADAPTY_APP_NAME_1": CANONICAL_APP_NAMES[0],
            "ADAPTY_API_KEY_APP2": "secret-two",
            "ADAPTY_APP_NAME_2": CANONICAL_APP_NAMES[1],
            "ADAPTY_API_KEY_APP3": "secret-three",
            "ADAPTY_APP_NAME_3": CANONICAL_APP_NAMES[2],
        }

        portfolio = load_daily_portfolio(env)

        self.assertEqual(tuple(slot.name for slot in portfolio.slots), CANONICAL_APP_NAMES)
        self.assertEqual(portfolio.issues, ())
        self.assertNotIn("secret-one", repr(portfolio))

    def test_wrong_or_missing_slot_is_not_fetchable(self):
        from daily_report_contract import load_daily_portfolio

        portfolio = load_daily_portfolio({
            "ADAPTY_API_KEY_APP1": "key-one",
            "ADAPTY_APP_NAME_1": "Wrong App",
        })

        self.assertIsNone(portfolio.slots[0].api_key)
        self.assertIsNone(portfolio.slots[1].api_key)
        self.assertIsNone(portfolio.slots[2].api_key)
        self.assertIn("config.wrong_name", {issue.code for issue in portfolio.issues})
        self.assertIn("config.missing_key", {issue.code for issue in portfolio.issues})

    def test_extra_slots_and_visibility_are_ignored_and_flagged(self):
        from daily_report_contract import CANONICAL_APP_NAMES, load_daily_portfolio

        env = {
            **{f"ADAPTY_API_KEY_APP{i}": f"key-{i}" for i in range(1, 5)},
            **{
                f"ADAPTY_APP_NAME_{i}": name
                for i, name in enumerate(CANONICAL_APP_NAMES, start=1)
            },
            "ADAPTY_APP_NAME_4": "TeaNote",
            "ADAPTY_APP_VISIBLE_3": "false",
        }

        portfolio = load_daily_portfolio(env)

        self.assertEqual(len(portfolio.slots), 3)
        self.assertTrue(all(slot.is_visible for slot in portfolio.slots))
        self.assertEqual(
            {issue.code for issue in portfolio.issues},
            {"config.extra_slot", "config.visibility_override"},
        )


if __name__ == "__main__":
    unittest.main()
