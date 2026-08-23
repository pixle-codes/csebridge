import io
import json
import os
import shutil
import tempfile
import textwrap
import unittest
from contextlib import redirect_stderr, redirect_stdout

from csebridge import cli
from csebridge.scan import CUTOFF, RULES, scan_path


def write_tree(files):
    tmp = tempfile.mkdtemp(prefix="cbscan-")
    for rel, content in files.items():
        path = os.path.join(tmp, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        mode = "wb" if isinstance(content, bytes) else "w"
        with open(path, mode) as fh:
            fh.write(content)
    return tmp


class TempRepoCase(unittest.TestCase):
    def make_repo(self, files):
        tmp = write_tree(files)
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return tmp


SAMPLES = {
    "py-cse-client": (
        "search.py",
        textwrap.dedent(
            """\
            from googleapiclient.discovery import build

            svc = build("customsearch", "v1", developerKey=KEY)
            res = svc.cse().list(q="x", cx=CX).execute()
            """
        ),
    ),
    "js-customsearch": (
        "app.js",
        "const { customsearch } = require('googleapis');\n"
        "const res = await customsearch.cse.list({ q: 'x', cx });\n",
    ),
    "http-endpoint": (
        "fetch.py",
        'url = "https://www.googleapis.com/customsearch/v1?key=K&cx=C&q=hi"\n',
    ),
    "gcse-embed": (
        "index.html",
        '<script async src="https://cse.google.com/cse.js?cx=abc"></script>\n'
        '<div class="gcse-search"></div>\n',
    ),
    "env-var": (
        ".env.example",
        "GOOGLE_CSE_ID=abc123\nGOOGLE_API_KEY=k\n",
    ),
}

ALL_FILES = {name: body for name, body in SAMPLES.values()}


class TestRulesFire(TempRepoCase):
    def _scan_sample(self, key):
        root = self.make_repo({SAMPLES[key][0]: SAMPLES[key][1]})
        result = scan_path(root)
        rules = {f["rule"] for f in result["findings"]}
        self.assertEqual(rules, {key}, f"{key} sample should fire only its rule")
        self.assertTrue(result["findings"], f"{key} sample should fire")
        return result

    def test_python_client(self):
        r = self._scan_sample("py-cse-client")
        self.assertEqual(
            [f["line"] for f in r["findings"]], [1, 3, 4]
        )  # import, build(), .cse().list
        self.assertIn("googleapiclient.discovery", r["findings"][0]["match"])
        self.assertIn("csebridge", r["findings"][0]["checklist"])

    def test_js_client(self):
        r = self._scan_sample("js-customsearch")
        self.assertEqual([f["line"] for f in r["findings"]], [1, 2])

    def test_raw_url(self):
        r = self._scan_sample("http-endpoint")
        self.assertEqual(r["findings"][0]["line"], 1)
        self.assertIn("customsearch/v1", r["findings"][0]["match"])

    def test_gcse_embed(self):
        r = self._scan_sample("gcse-embed")
        self.assertEqual([f["line"] for f in r["findings"]], [1, 2])

    def test_env_var(self):
        r = self._scan_sample("env-var")
        self.assertEqual([f["line"] for f in r["findings"]], [1])
        self.assertIn("GOOGLE_CSE_ID", r["findings"][0]["match"])

    def test_every_rule_has_checklist_pointing_at_csebridge(self):
        for rule in RULES:
            self.assertTrue(rule.checklist.strip())
            self.assertIn("csebridge", rule.checklist)

    def test_rules_fire_without_extension_discrimination(self):
        # A README snippet is just as dead as the code it documents.
        root = self.make_repo({
            "README.md": "GET https://www.googleapis.com/customsearch/v1?q=x\n"
        })
        result = scan_path(root)
        self.assertEqual(
            [f["rule"] for f in result["findings"]], ["http-endpoint"]
        )


class TestPrecedenceAndNoise(TempRepoCase):
    def test_specific_rule_claims_line_before_url_rule(self):
        root = self.make_repo({
            "x.py": 'requests.get("https://www.googleapis.com/customsearch/v1")  # via googleapiclient.discovery\n'
        })
        result = scan_path(root)
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["rule"], "py-cse-client")

    def test_no_false_positive_on_other_google_apis(self):
        root = self.make_repo({
            "ok.py": 'drive = build("drive", "v3"); requests.get("https://www.googleapis.com/drive/v3/files")\n',
            "ok.js": "import { google } from 'googleapis-core';\n",
            "ok.env": "GOOGLE_API_KEY=k\nDATABASE_URL=postgres://x\n",
        })
        result = scan_path(root)
        self.assertEqual(result["findings"], [])
        self.assertEqual(result["files_scanned"], 3)


class TestWalkSemantics(TempRepoCase):
    def test_skips_vcs_and_dep_dirs_and_hidden_dirs(self):
        files = {SAMPLES["env-var"][0]: SAMPLES["env-var"][1]}
        for junk in (".git/hooks", "node_modules/x", "__pycache__", ".venv/lib"):
            files[junk + "/leak.env"] = "CUSTOMSEARCH_API_KEY=x\n"
        root = self.make_repo(files)
        result = scan_path(root)
        self.assertEqual(result["files_scanned"], 1)
        self.assertEqual(result["summary"]["total"], 1)

    def test_binary_files_skipped(self):
        root = self.make_repo({"blob.bin": b"CUSTOMSEARCH\x00KEY=x"})
        result = scan_path(root)
        self.assertEqual(result["files_scanned"], 0)
        self.assertEqual(result["findings"], [])

    def test_single_file_target(self):
        root = self.make_repo(ALL_FILES)
        result = scan_path(os.path.join(root, SAMPLES["http-endpoint"][0]))
        self.assertEqual(result["files_scanned"], 1)
        self.assertEqual(result["summary"]["by_rule"], {"http-endpoint": 1})

    def test_missing_path_raises_valueerror(self):
        with self.assertRaises(ValueError):
            scan_path("/nonexistent/csebridge-scan-probe")


class TestResultShape(TempRepoCase):
    def test_json_shape_and_summary(self):
        root = self.make_repo(ALL_FILES)
        result = scan_path(root)
        self.assertEqual(
            sorted(result.keys()),
            ["cutoff", "files_scanned", "findings", "summary", "target"],
        )
        self.assertEqual(result["cutoff"], CUTOFF)
        self.assertGreaterEqual(len(result["findings"]), len(SAMPLES))
        by_rule = result["summary"]["by_rule"]
        self.assertEqual(sum(by_rule.values()), len(result["findings"]))
        for f in result["findings"]:
            self.assertEqual(
                sorted(f.keys()), ["checklist", "line", "match", "path", "rule"]
            )
            self.assertLessEqual(len(f["match"]), 160)

    def test_findings_are_json_serializable(self):
        root = self.make_repo(ALL_FILES)
        roundtrip = json.loads(json.dumps(scan_path(root)))
        self.assertEqual(roundtrip["summary"]["total"], len(roundtrip["findings"]))


class TestCli(TempRepoCase):
    def setUp(self):
        self.root = self.make_repo(ALL_FILES)

    def run_scan_cli(self, argv):
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with redirect_stdout(out), redirect_stderr(err):
                cli.main(argv)
        except SystemExit as exc:
            code = exc.code
        return code, out.getvalue(), err.getvalue()

    def test_exit_1_when_findings_text_mode(self):
        code, out, err = self.run_scan_cli(["scan", self.root])
        self.assertEqual(code, 1)
        self.assertIn("Custom Search call site(s)", out)
        self.assertIn("[py-cse-client]", out)
        self.assertIn("Jan 1 2027", out)
        self.assertIn("fix:", out)

    def test_exit_0_clean_repo(self):
        clean = self.make_repo({"app.py": "print('hello')\n"})
        code, out, err = self.run_scan_cli(["scan", clean])
        self.assertEqual(code, 0)
        self.assertIn("No Custom Search usage found", out)

    def test_json_mode_emits_report_object(self):
        code, out, err = self.run_scan_cli(["scan", self.root, "--json"])
        self.assertEqual(code, 1)
        report = json.loads(out)
        self.assertEqual(report["target"], self.root)
        self.assertEqual(report["cutoff"], CUTOFF)
        self.assertTrue(report["findings"])

    def test_missing_path_exits_2_with_stderr(self):
        code, out, err = self.run_scan_cli(["scan", "/nonexistent/csebridge"])
        self.assertEqual(code, 2)
        self.assertIn("no such file or directory", err)
        self.assertEqual(out, "")

    def test_scan_bad_usage_exits_2(self):
        code, out, err = self.run_scan_cli(["scan"])
        self.assertEqual(code, 2)


class TestSearchUnaffected(unittest.TestCase):
    def test_search_still_works_after_scan_dispatch(self):
        # argv[0] == "scan" dispatch must not leak into the search parser path.
        from .helpers import load_fixture, ok
        from .test_cli import run_cli

        code, out, err, _ = run_cli(
            ["q=test", "--json"], responder=ok(load_fixture("brave_web"))
        )
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertIn("items", payload)
