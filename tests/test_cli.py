"""Tests for the command line surface (no Blender, no subprocesses)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from model_loop import __version__, cli
from model_loop.blender import BlenderConfig, BlenderError
from model_loop.params import ParamSpec, SearchSpace
from model_loop.pipeline import Evaluation, LoopResult


def run(argv: list[str]) -> tuple[int, str, str]:
    """Run main() and capture (code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv)
    return code, out.getvalue(), err.getvalue()


BENCH_REPORT = {
    "blender_version": "Blender 4.2.9 LTS",
    "measured": {
        "renders": [
            {"resolution": 256, "samples": 1, "seconds": 0.03},
            {"resolution": 512, "samples": 16, "seconds": 0.26},
        ],
        "boolean": {"seconds": 0.23, "vertices": 29000},
    },
}


class ParserTests(unittest.TestCase):
    def test_prog_name_is_the_product(self) -> None:
        self.assertEqual(cli.build_parser().prog, "blender-automation-skill")

    def test_version_flag_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main(["--version"])
        self.assertEqual(ctx.exception.code, 0)

    def test_missing_subcommand_is_a_usage_error(self) -> None:
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as ctx:
            cli.main([])
        self.assertEqual(ctx.exception.code, 2)


class VersionCommandTests(unittest.TestCase):
    def test_version_prints_json(self) -> None:
        code, out, _ = run(["version"])
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {"name": "blender-automation-skill", "version": __version__},
        )


class ConfigTests(unittest.TestCase):
    def test_blender_arguments_map_to_the_config(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "bench",
                "--blender",
                "/opt/blender",
                "--memory-mb",
                "2048",
                "--timeout",
                "30",
                "--lock",
                "/tmp/lock",
            ]
        )
        config = cli._config(args)
        self.assertIsInstance(config, BlenderConfig)
        self.assertEqual(config.binary, "/opt/blender")
        self.assertEqual(config.memory_mb, 2048)
        self.assertEqual(config.timeout_s, 30.0)
        self.assertEqual(config.lock_path, Path("/tmp/lock"))


class BenchCommandTests(unittest.TestCase):
    def test_bench_summarises_the_report(self) -> None:
        with mock.patch.object(cli, "run_benchmark", return_value=BENCH_REPORT) as bench:
            code, out, _ = run(["bench", "--out", "out/bench"])
        self.assertEqual(code, 0)
        bench.assert_called_once()
        self.assertIn("Blender: Blender 4.2.9 LTS", out)
        self.assertIn("render  256px/ 1spp: 0.030s", out)
        self.assertIn("exact boolean: 0.230s (29000 verts)", out)

    def test_bench_reports_a_missing_blender_as_exit_code_2(self) -> None:
        with mock.patch.object(cli, "run_benchmark", side_effect=BlenderError("no blender")):
            code, _, err = run(["bench"])
        self.assertEqual(code, 2)
        self.assertIn("error: no blender", err)


class DemoCommandTests(unittest.TestCase):
    def test_demo_prints_summary_and_paths(self) -> None:
        result = LoopResult(best=Evaluation(params={"width": 1.4}, score=0.93))
        with (
            mock.patch.object(cli, "run_demo", return_value=result) as demo,
            mock.patch.object(cli, "demo_summary", return_value="best score (IoU): 0.9300"),
        ):
            code, out, _ = run(["demo", "--out", "out/demo", "--rounds", "2", "--budget", "10"])
        self.assertEqual(code, 0)
        demo.assert_called_once()
        self.assertEqual(demo.call_args.kwargs["rounds"], 2)
        self.assertEqual(demo.call_args.kwargs["budget"], 10)
        self.assertIn("best score (IoU): 0.9300", out)
        self.assertIn("history -> out/demo/history.json", out)
        self.assertIn("report  -> out/demo/report.html", out)


class ReportCommandTests(unittest.TestCase):
    def test_report_renders_a_history_file(self) -> None:
        space = SearchSpace([ParamSpec("width", 0.4, 2.0, default=1.0)])
        result = LoopResult(
            best=Evaluation(params={"width": 1.2}, score=0.5),
            history=[Evaluation(params={"width": 1.0}, score=0.4)],
            space=space,
        )
        with tempfile.TemporaryDirectory(prefix="bas-cli-") as tmp:
            history = result.save(Path(tmp) / "history.json")
            out = Path(tmp) / "report.html"
            code, stdout, _ = run(
                ["report", "--history", str(history), "--out", str(out), "--title", "CLI test"]
            )
            self.assertEqual(code, 0)
            self.assertTrue(out.exists())
            self.assertIn("report ->", stdout)
            self.assertIn("CLI test", out.read_text(encoding="utf-8"))
