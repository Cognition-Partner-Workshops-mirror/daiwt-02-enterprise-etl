import importlib.util
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location("estate", Path(__file__).with_name("estate.py"))
estate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(estate)


class EstateTests(unittest.TestCase):
    def test_quote_identifier(self):
        self.assertEqual(estate.quote_identifier("Stock Item"), "[Stock Item]")
        self.assertEqual(estate.quote_identifier("a]b"), "[a]]b]")

    def test_seeds_are_only_the_two_shared_databases(self):
        self.assertEqual([s["name"] for s in estate.SEEDS["databases"]],
                         ["WideWorldImporters", "WideWorldImportersDW"])
        self.assertTrue(all(len(s["sha256"]) == 64 for s in estate.SEEDS["databases"]))

    def test_restore_success(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"lifecycle": "SUCCESS"}
        estate.wait_restore(cursor, 3)

    def test_restore_failure_is_not_success(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"lifecycle": "ERROR", "task_info": "restore failed"}
        with self.assertRaisesRegex(RuntimeError, "restore failed"):
            estate.wait_restore(cursor, 3)

    def test_reset_requires_confirmation_before_any_connection(self):
        with patch("sys.argv", ["estate.py", "reset"]), patch.object(estate, "connect") as conn:
            with self.assertRaises(SystemExit) as error:
                estate.main()
            self.assertEqual(error.exception.code, 2)
            conn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
