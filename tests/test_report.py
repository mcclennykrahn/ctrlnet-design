"""设计报告 Markdown / HTML / DOCX 生成测试。"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from ctrlnet.reportgen import (
    build_report,
    main as report_main,
    render_html_report,
    write_report,
)
from ctrlnet.store import save_project, snapshot

ROOT = Path(__file__).resolve().parents[1]


def _project() -> dict:
    return {
        "id": "report-project",
        "name": "报告测试工程",
        "crs": "EPSG:32650",
        "metadata": {
            "datum": "fixed",
            "default_scenario": "base",
            "terrain": {
                "dem": {
                    "path": "data/sample/dem_sample.tif",
                    "crs": "EPSG:32650",
                    "shape": [374, 289],
                    "resolution_m": [30.0, 30.0],
                    "source": "synthetic",
                    "vertical_datum": "EGM2008",
                },
                "analysis": {
                    "k": 0.13,
                    "R_m": 6371000.0,
                    "instrument_height_m": 1.5,
                    "target_height_m": 1.5,
                },
            },
        },
        "points": [
            {"name": "A", "E": 0.0, "N": 0.0, "fixed": True, "elevation_m": 100.0},
            {"name": "B", "E": 100.0, "N": 0.0, "fixed": True, "elevation_m": 101.0},
            {"name": "C", "E": 0.0, "N": 100.0, "fixed": False, "elevation_m": 102.0},
            {"name": "D", "E": 100.0, "N": 100.0, "fixed": False, "elevation_m": 103.0},
        ],
        "scenarios": [
            {
                "id": "base",
                "name": "基准方案",
                "version": 1,
                "metadata": {
                    "datum": "fixed",
                    "points": ["A", "B", "C", "D"],
                    "visibility": [
                        {
                            "from": "A",
                            "to": "B",
                            "distance_m": 100.0,
                            "status": "visible",
                            "visible": True,
                            "min_clearance_m": 12.5,
                            "min_distance_m": 50.0,
                            "samples": 31,
                        },
                        {
                            "from": "A",
                            "to": "D",
                            "distance_m": 141.4,
                            "status": "blocked",
                            "visible": False,
                            "min_clearance_m": -3.2,
                            "min_distance_m": 70.0,
                            "obstruction": {"E": 50.0, "N": 50.0, "elevation_m": 110.0},
                            "samples": 41,
                        },
                    ],
                },
                "observations": [
                    {"id": "d1", "kind": "distance", "from": "A", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d2", "kind": "distance", "from": "B", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d3", "kind": "distance", "from": "A", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d4", "kind": "distance", "from": "B", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d5", "kind": "distance", "from": "C", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "a1", "kind": "angle", "backsight": "C", "station": "A", "foresight": "B", "sigma_arcsec": 1.0},
                    {"id": "a2", "kind": "angle", "backsight": "A", "station": "B", "foresight": "D", "sigma_arcsec": 1.0},
                ],
            },
            {
                "id": "added",
                "name": "增补方案",
                "version": 2,
                "parent_id": "base",
                "description": "增加角 D-C-A",
                "metadata": {"datum": "fixed", "points": ["A", "B", "C", "D"]},
                "observations": [
                    {"id": "d1", "kind": "distance", "from": "A", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d2", "kind": "distance", "from": "B", "to": "C", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d3", "kind": "distance", "from": "A", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d4", "kind": "distance", "from": "B", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "d5", "kind": "distance", "from": "C", "to": "D", "a_m": 0.002, "b_ppm": 2.0},
                    {"id": "a1", "kind": "angle", "backsight": "C", "station": "A", "foresight": "B", "sigma_arcsec": 1.0},
                    {"id": "a2", "kind": "angle", "backsight": "A", "station": "B", "foresight": "D", "sigma_arcsec": 1.0},
                    {"id": "a3", "kind": "angle", "backsight": "D", "station": "C", "foresight": "A", "sigma_arcsec": 1.0},
                ],
            },
        ],
    }


@pytest.fixture()
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "report.sqlite"
    save_project(path, _project())
    return path


def test_markdown_and_html_report(db_path: Path, tmp_path: Path):
    out = tmp_path / "out"
    data = write_report(db_path, out, scenario="added", docx=False)
    md = Path(data["markdown_path"])
    html = Path(data["html_path"])
    assert md.exists() and html.exists()
    assert md.name == "design_report.md"
    assert html.name == "design_report.html"

    text = md.read_text(encoding="utf-8")
    for heading in (
        "## 1. 工程概况",
        "## 2. 点与观测清单",
        "## 3. 先验精度模型",
        "## 4. 基准",
        "## 5. 点位精度与误差椭圆",
        "## 6. 边相对精度",
        "## 7. 可靠性",
        "## 8. 方案对比",
        "## 9. 优化建议",
        "## 10. 通视结果",
        "## 11. 图表",
        "## 12. 复现与数据版本",
    ):
        assert heading in text
    assert "增补方案" in text
    assert data["snapshot"]["input_hash"] in text
    assert "1.310" in text  # 增补方案最大 mp
    assert "1:81608" in text  # 最弱边相对精度
    assert "A–B" in text or "A-B" in text
    assert "![网图与 95% 误差椭圆](assets/design_network.png)" in text
    assert (out / "assets" / "design_network.png").exists()

    page = html.read_text(encoding="utf-8")
    assert "<!doctype html>" in page
    assert "data:image/png;base64," in page
    assert 'src="assets/' not in page
    assert "设计报告" in page
    assert "pandoc" not in data.get("docx_error", "")


def test_html_report_is_self_contained(db_path: Path):
    page = render_html_report(db_path, scenario="base")
    assert page.startswith("<!doctype html>")
    assert page.count("data:image/png;base64,") >= 2
    assert "基准方案" in page
    assert "r_i" in page


def test_report_defaults_to_project_default_scenario(db_path: Path):
    data = build_report(db_path, out_dir=db_path.parent / "report-default")
    assert data["scenario_id"] == "base"
    assert data["selected"]["summary"]["n_observations"] == 7
    assert data["comparison_rows"]
    assert data["comparison_rows"][0]["parent"] == "base"
    assert data["comparison_rows"][0]["candidate"] == "added"


def test_report_cli(db_path: Path, tmp_path: Path):
    out = tmp_path / "cli-out"
    code = report_main(
        [
            "--project",
            str(db_path),
            "--out",
            str(out),
            "--scenario",
            "added",
            "--no-docx",
        ]
    )
    assert code == 0
    assert (out / "design_report.md").exists()
    assert (out / "design_report.html").exists()


def test_docx_optional(db_path: Path, tmp_path: Path):
    out = tmp_path / "docx-out"
    data = write_report(db_path, out, scenario="base", docx=True)
    if shutil.which("pandoc"):
        assert data["docx_path"] is not None
        docx = Path(data["docx_path"])
        assert docx.exists() and docx.stat().st_size > 0
        assert docx.read_bytes().startswith(b"PK")
    else:  # pragma: no cover - 本机通常有 pandoc
        assert data["docx_path"] is None
        assert "pandoc" in data.get("docx_error", "")


def test_unknown_scenario_raises(db_path: Path, tmp_path: Path):
    with pytest.raises(KeyError):
        write_report(db_path, tmp_path / "bad", scenario="missing", docx=False)


def test_report_contains_visibility_and_reliability(db_path: Path, tmp_path: Path):
    data = write_report(db_path, tmp_path / "out2", scenario="base", docx=False)
    text = data["markdown"]
    assert "通视结果" in text
    assert "遮挡" in text and "通视" in text
    assert "最小净空" in text
    assert "MDB" in text and "外部" in text
    # 表格中的观测类型应为中文，而不是 None。
    assert "| 距离 |" in text
    assert "| 水平角 |" in text
