import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.video_duration import normalize_video_duration


# ── 空/非法输入 → default ──

@pytest.mark.parametrize("bad", [None, "", "  ", "abc", "7s", [], {}, object()])
def test_invalid_inputs_fall_back_to_default(bad):
    assert normalize_video_duration(bad, default_seconds=5) == 5


def test_none_uses_custom_default():
    assert normalize_video_duration(None, default_seconds=8) == 8


def test_negative_clamps_to_lower_bound():
    assert normalize_video_duration(-3, default_seconds=5) == 2


def test_numeric_string_is_converted():
    assert normalize_video_duration("7", default_seconds=5) == 7
    assert normalize_video_duration(" 7 ", default_seconds=5) == 7


@pytest.mark.parametrize("bad_type", [[7], {"a": 1}, True])
def test_non_numeric_types_fall_back_to_default(bad_type):
    assert normalize_video_duration(bad_type, default_seconds=5) == 5


# ── clamp 边界 ──

def test_clamp_lower_bound_one_becomes_two():
    assert normalize_video_duration(1) == 2


def test_clamp_boundary_two_stays_two():
    assert normalize_video_duration(2) == 2


def test_clamp_boundary_fifty_nine_stays():
    assert normalize_video_duration(59) == 59


def test_clamp_upper_bound_sixty_stays():
    assert normalize_video_duration(60) == 60


def test_clamp_above_sixty_becomes_sixty():
    assert normalize_video_duration(100) == 60


# ── Seedance 1.x 兜底（无档位配置）──

@pytest.mark.parametrize("model", ["seedance-1-0-pro", "seedance2.0-1.0", "sd-2-vip-seedance-1.5", "seedance-1-5-lite"])
def test_seedance_1x_fifteen_clamped_to_twelve(model):
    assert normalize_video_duration(15, model=model) == 12


def test_seedance_1x_seven_stays_seven():
    assert normalize_video_duration(7, model="seedance-1-0-pro") == 7


def test_seedance_2x_not_capped_at_twelve():
    assert normalize_video_duration(15, model="seedance-2-0-fast") == 15


def test_non_seedance_fifteen_stays_fifteen():
    assert normalize_video_duration(15, model="sd-2-vip") == 15
    assert normalize_video_duration(15, model="") == 15


# ── duration_options 档位归一 ──

def test_options_top_level_snaps_to_nearest_smaller():
    caps = {"duration_options": [5, 10]}
    assert normalize_video_duration(7, capabilities=caps) == 5
    assert normalize_video_duration(12, capabilities=caps) == 10


def test_options_under_wire_subdict():
    caps = {"wire": {"duration_options": [5, 10]}}
    assert normalize_video_duration(7, capabilities=caps) == 5
    assert normalize_video_duration(12, capabilities=caps) == 10


def test_options_exact_match():
    caps = {"duration_options": [5, 10, 15]}
    assert normalize_video_duration(10, capabilities=caps) == 10


def test_options_tie_picks_smaller():
    caps = {"duration_options": [5, 9]}
    # 7 与 5/9 距离相等 → 取小者
    assert normalize_video_duration(7, capabilities=caps) == 5


def test_options_take_precedence_over_seedance_cap():
    caps = {"duration_options": [5, 10, 15]}
    # 有显式档位配置时不套用 Seedance 1.x 的 12 秒兜底
    assert normalize_video_duration(15, model="seedance-1-0-pro", capabilities=caps) == 15


def test_options_are_clamped_first():
    caps = {"duration_options": [5, 10]}
    # 100 先 clamp 到 60，再就近归到 10
    assert normalize_video_duration(100, capabilities=caps) == 10


@pytest.mark.parametrize("caps", [
    None,
    {},
    {"duration_options": []},
    {"duration_options": "5,10"},
    {"duration_options": [0, 5]},
    {"duration_options": ["a", "b"]},
    {"wire": "not-a-dict"},
])
def test_invalid_options_configs_are_ignored(caps):
    assert normalize_video_duration(7, capabilities=caps) == 7


# ── float 输入 ──

def test_float_rounds_to_nearest_int():
    assert normalize_video_duration(7.4) == 7
    assert normalize_video_duration(7.6) == 8
