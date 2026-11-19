from types import SimpleNamespace

import pytest

from dreamgoods.core import presets, settings


@pytest.mark.parametrize("quality", [None, *presets.QUALITY])
def test_generation_quality_respects_qc_opt_in(quality):
    preset = None if quality is None else SimpleNamespace(
        id=1, name="Test", quality=quality, custom={}, plan_mode="auto",
        plan={}, market={}, strictness="strict", block_models={},
    )
    for overrides, expected in [({}, False), ({"qc_enabled": True}, True), ({"qc_enabled": False}, False)]:
        effective = settings.effective(SimpleNamespace(settings=overrides), None)
        assert presets.apply(effective, preset)["qc_enabled"] is expected
