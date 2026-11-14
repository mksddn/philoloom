"""Protect provenance ledger coverage and uncertainty labels.

This test does not establish quote attribution or translation accuracy.
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUOTE_DIR = ROOT / "content" / "notion" / "Философия" / "Цитаты"
PROVENANCE = ROOT / "content" / "quote-provenance.json"
ID_RE = re.compile(r"([a-f0-9]{32})\.md$")


class QuoteProvenanceTests(unittest.TestCase):
    def test_all_current_quotes_have_provenance_record(self):
        ledger = json.loads(PROVENANCE.read_text(encoding="utf-8"))
        self.assertEqual(ledger["version"], 1)
        ids = {ID_RE.search(path.name).group(1) for path in QUOTE_DIR.glob("*.md")}
        self.assertEqual(set(ledger["quotes"]), ids)
        self.assertEqual(len(ids), 11)
        statuses = {"source_located", "paraphrase_review", "unverified"}
        for pid, info in ledger["quotes"].items():
            with self.subTest(pid=pid):
                self.assertIn(info["status"], statuses)
                self.assertTrue(info["author"].strip())
                self.assertTrue(info["short"].strip())
                self.assertTrue(info["note"].strip())
                if info["status"] != "unverified":
                    self.assertTrue(info["work"])
                    self.assertTrue(info["locator"])
                    self.assertTrue(info["source_url"].startswith("https://"))
        self.assertEqual(
            {status: sum(q["status"] == status for q in ledger["quotes"].values())
             for status in statuses},
            {"source_located": 9, "paraphrase_review": 2, "unverified": 0},
        )


if __name__ == "__main__":
    unittest.main()
