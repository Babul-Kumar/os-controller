import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from automation import draw_engine
from automation.draw_engine import DrawableCandidate, PipelineMode


class TestDrawEngine(unittest.TestCase):
    def test_detect_best_mode_prefers_sketch_for_snake(self):
        self.assertEqual(draw_engine._detect_best_mode("snake"), PipelineMode.SKETCH)

    def test_auto_attempt_chain_includes_simpler_fallbacks(self):
        chain = draw_engine._build_attempt_chain(PipelineMode.AUTO)
        self.assertEqual(chain, [PipelineMode.AUTO, PipelineMode.SKETCH, PipelineMode.LOGO])

    def test_pick_better_candidate_prefers_sketch_over_logo_for_sketch_requests(self):
        logo_candidate = DrawableCandidate(
            processed_path=Path("C:/temp/logo.png"),
            mode=PipelineMode.LOGO,
            trace_source=Path("C:/temp/logo.png"),
            density={"total_contours": 4},
            estimate={"estimated_seconds": 1.0, "point_count": 80, "contour_count": 4},
        )
        sketch_candidate = DrawableCandidate(
            processed_path=Path("C:/temp/sketch.png"),
            mode=PipelineMode.SKETCH,
            trace_source=Path("C:/temp/sketch.png"),
            density={"total_contours": 3},
            estimate={"estimated_seconds": 3.0, "point_count": 180, "contour_count": 3},
        )

        best = draw_engine._pick_better_candidate(logo_candidate, sketch_candidate, PipelineMode.SKETCH)
        self.assertIs(best, sketch_candidate)

    def test_find_local_asset_ignores_generated_versioned_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "snake_sketch_135541a9c0f4_v10.png").write_bytes(b"x")
            manual = tmp_path / "snake.png"
            manual.write_bytes(b"y")

            with patch.object(draw_engine, "ASSETS_DIR", tmp_path):
                found = draw_engine._find_local_asset("snake", PipelineMode.SKETCH)

            self.assertEqual(found, manual)

    @patch("automation.draw_engine._build_outline_fallback")
    @patch("automation.draw_engine._evaluate_drawable_candidate")
    def test_resolve_candidate_uses_outline_rescue(self, mock_evaluate, mock_outline):
        raw_path = Path("C:/temp/snake.png")
        outline_path = Path("C:/temp/snake_outline.png")
        mock_outline.return_value = outline_path

        rescued = DrawableCandidate(
            processed_path=outline_path,
            mode=PipelineMode.LOGO,
            trace_source=outline_path,
            density={"total_contours": 1},
            estimate={"estimated_seconds": 2.0, "point_count": 20, "contour_count": 1},
        )

        def _side_effect(path, mode, label):
            if path == outline_path and mode == PipelineMode.LOGO:
                return rescued
            return None

        mock_evaluate.side_effect = _side_effect

        result = draw_engine._resolve_drawable_candidate(raw_path, PipelineMode.AUTO, "Attempt 1")

        self.assertIs(result, rescued)
        attempted = [(call.args[0], call.args[1]) for call in mock_evaluate.call_args_list]
        self.assertEqual(
            attempted,
            [
                (raw_path, PipelineMode.AUTO),
                (raw_path, PipelineMode.SKETCH),
                (raw_path, PipelineMode.LOGO),
                (outline_path, PipelineMode.SKETCH),
                (outline_path, PipelineMode.AUTO),
                (outline_path, PipelineMode.LOGO),
            ],
        )


if __name__ == "__main__":
    unittest.main()
