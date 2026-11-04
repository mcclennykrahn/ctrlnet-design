"""六参数仿射配准测试：精确恢复、噪声 RMS、共线/不足报错、世界文件。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ctrlnet.registration import (
    ControlPoint,
    RegistrationError,
    read_world_file,
    register_affine,
    register_image,
    world_file_path,
    write_world_file,
)
from ctrlnet.terrain import AffineTransform

TRUE = (3.0, 0.2, 500_000.0, -0.1, -2.5, 4_000_000.0)
GRID = [
    (0.0, 0.0),
    (800.0, 0.0),
    (800.0, 600.0),
    (0.0, 600.0),
    (400.0, 300.0),
    (200.0, 500.0),
    (600.0, 100.0),
    (100.0, 250.0),
]


def ground_truth(col: float, row: float) -> tuple[float, float]:
    a, b, c, d, e, f = TRUE
    return a * col + b * row + c, d * col + e * row + f


def make_points(noise: float = 0.0, seed: int = 42) -> list[ControlPoint]:
    rng = np.random.default_rng(seed)
    points = []
    for index, (col, row) in enumerate(GRID):
        E, N = ground_truth(col, row)
        if noise:
            E += float(rng.normal(0.0, noise))
            N += float(rng.normal(0.0, noise))
        points.append(ControlPoint(col, row, E, N, label=f"C{index + 1}"))
    return points


def test_exact_affine_recovered():
    points = make_points()
    result = register_affine(points)
    assert result.n_points == len(points)
    assert result.transform.to_tuple() == pytest.approx(TRUE, rel=0.0, abs=1e-6)
    assert result.rms < 1e-6
    assert result.rms_e < 1e-6
    assert result.rms_n < 1e-6
    assert result.max_residual < 2e-6
    assert np.allclose(result.residual_e, 0.0, atol=1e-6)
    assert np.allclose(result.residual_n, 0.0, atol=1e-6)

    # 字典与元组输入也应可用。
    tuples = [(p.col, p.row, p.E, p.N) for p in points[:3]]
    dicts = [
        {"col": c, "row": r, "E": E, "N": N}
        for c, r, E, N in tuples
    ]
    tuple_result = register_affine(tuples)
    dict_result = register_affine(dicts)
    assert tuple_result.transform.to_tuple() == pytest.approx(TRUE, abs=1e-6)
    assert dict_result.transform.to_tuple() == pytest.approx(TRUE, abs=1e-6)


def test_noisy_rms_reasonable_and_check_points_independent():
    points = make_points(noise=0.3, seed=7)
    # 独立检查点不参与参数求解，但会进入检查点 RMS。
    checks = make_points(noise=0.3, seed=99)[:3]
    result = register_affine(points, checks)
    assert 0.08 < result.rms < 0.8
    assert 0.05 < result.rms_e < 0.6
    assert 0.05 < result.rms_n < 0.8
    assert result.rms == pytest.approx(
        float(np.sqrt(np.mean(result.residual_e ** 2 + result.residual_n ** 2)))
    )
    assert result.check_rms is not None and result.check_rms > 0.0

    no_check = register_affine(points)
    assert no_check.transform.to_tuple() == pytest.approx(result.transform.to_tuple())
    assert no_check.check_rms is None


def test_requires_three_points():
    with pytest.raises(RegistrationError, match="至少需要 3"):
        register_affine([(0.0, 0.0, 1.0, 2.0), (10.0, 0.0, 31.0, 2.0)])


def test_collinear_points_rejected():
    collinear = [
        (0.0, 0.0, 500_000.0, 4_000_000.0),
        (10.0, 20.0, 500_030.0, 3_999_950.0),
        (20.0, 40.0, 500_060.0, 3_999_900.0),
        (40.0, 80.0, 500_120.0, 3_999_800.0),
    ]
    with pytest.raises(RegistrationError, match="共线"):
        register_affine(collinear)
    # 同一像素点重复也退化。
    repeated = [(5.0, 5.0, 1.0, 2.0)] * 4
    with pytest.raises(RegistrationError):
        register_affine(repeated)


def test_invalid_weights_and_points_rejected():
    with pytest.raises(RegistrationError, match="weights"):
        register_affine(make_points()[:4], weights=[1.0, -2.0, 1.0, 1.0])
    with pytest.raises(RegistrationError):
        register_affine([(0.0, 0.0, float("nan"), 0.0)] * 3)


def test_world_files_and_image_registration(tmp_path: Path):
    from PIL import Image

    image_path = tmp_path / "scan.png"
    Image.new("RGB", (100, 80), (240, 235, 220)).save(image_path)
    points = [
        (0.0, 0.0, *ground_truth(0.0, 0.0)),
        (100.0, 0.0, *ground_truth(100.0, 0.0)),
        (100.0, 80.0, *ground_truth(100.0, 80.0)),
        (0.0, 80.0, *ground_truth(0.0, 80.0)),
    ]
    result = register_image(image_path, points, write_world=True)
    world = Path(result.world_file)
    assert world.suffix == ".pgw"
    assert world.exists()
    restored = read_world_file(world)
    assert restored.to_tuple() == pytest.approx(TRUE, abs=1e-9)
    assert result.image_size == (100, 80)

    tif_path = tmp_path / "scan.tif"
    Image.new("RGB", (100, 80), (240, 235, 220)).save(tif_path)
    tif_result = register_image(tif_path, points, write_world=True)
    tif_world = Path(tif_result.world_file)
    assert tif_world.suffix == ".tfw"
    assert tif_world.exists()
    assert read_world_file(tif_world).to_tuple() == pytest.approx(TRUE, abs=1e-9)
    assert tif_result.image_size == (100, 80)
    assert world_file_path(tmp_path / "a.tiff").suffix == ".tfw"
    assert world_file_path(tmp_path / "a.png").suffix == ".pgw"

    # 世界文件第 5/6 行使用左上像素中心。
    raw = world.read_text(encoding="utf-8").split()
    expected_center = (
        TRUE[2] + 0.5 * (TRUE[0] + TRUE[1]),
        TRUE[5] + 0.5 * (TRUE[3] + TRUE[4]),
    )
    assert float(raw[4]) == pytest.approx(expected_center[0], abs=1e-9)
    assert float(raw[5]) == pytest.approx(expected_center[1], abs=1e-9)
    assert AffineTransform.coerce(result.transform) == result.transform


def test_unsupported_image_suffix(tmp_path: Path):
    with pytest.raises(RegistrationError, match="不支持"):
        register_image(tmp_path / "map.txt", make_points()[:4])
    assert world_file_path(tmp_path / "map.png").name == "map.pgw"
