"""Regression tests for the demo output layout (no Blender required)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from model_loop import demo
from model_loop.blender import BlenderConfig


class DemoLayoutTests(unittest.TestCase):
    def test_run_demo_leaves_no_empty_renders_directory(self) -> None:
        """Renders belong under work/renders.

        The demo used to create <outdir>/renders up front and never write into
        it: the evaluator only sees workdir (= <outdir>/work), so users were
        left with an empty directory that looked like output while the real
        PNGs sat one level deeper.
        """
        with tempfile.TemporaryDirectory(prefix="bas-demo-") as tmp:
            outdir = Path(tmp) / "run"

            def fake_run_script(config, script, args=(), **kwargs):
                png = Path(args[1])
                png.parent.mkdir(parents=True, exist_ok=True)
                png.write_bytes(b"")
                return mock.MagicMock()

            with (
                mock.patch.object(demo, "require_blender", lambda config: None),
                mock.patch.object(demo, "run_script", fake_run_script),
                mock.patch.object(demo, "load_mask", lambda path: object()),
                mock.patch.object(demo, "silhouette_metrics", lambda a, b: {"iou": 0.5}),
                mock.patch.object(demo, "render_report", lambda result, path, **kw: Path(path)),
            ):
                demo.run_demo(BlenderConfig(binary="blender"), outdir, rounds=1, budget=24)

            self.assertFalse(
                (outdir / "renders").exists(),
                "run_demo must not leave an empty <outdir>/renders directory",
            )
            renders = sorted((outdir / "work" / "renders").glob("eval_*.png"))
            self.assertTrue(renders, "evaluation renders must be written under work/renders")
            self.assertTrue((outdir / "history.json").is_file())
            self.assertTrue((outdir / "target.png").is_file())


if __name__ == "__main__":
    unittest.main()
