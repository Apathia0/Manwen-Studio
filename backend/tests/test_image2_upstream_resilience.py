"""图片上游 5xx / 过载时的重试退避与并发闸门。"""

import asyncio

import pytest

from services import image2
from services.errors import MangaImageGenerationError


def _error(code="upstream_server_error", status=500, message="Upstream gateway error", retryable=True):
    return MangaImageGenerationError(code=code, user_message="x", retryable=retryable, provider_message=message, status_code=status)


def test_upstream_5xx_backs_off_longer_each_time_with_jitter():
    delays = [[image2.retry_delay_seconds(attempt, _error()) for _ in range(30)] for attempt in (1, 2, 3)]
    for attempt, samples in zip((1, 2, 3), delays):
        base = image2.UPSTREAM_BACKOFF_SECONDS[attempt - 1]
        assert all(base <= value <= base * 1.3 for value in samples)
        assert len(set(samples)) > 1, "必须带随机抖动，避免多路请求同时重试"
    assert min(delays[1]) > max(delays[0]) * 0.9 and min(delays[2]) > max(delays[1]) * 0.9


def test_overload_and_503_wait_longer_than_a_plain_500():
    plain = image2.UPSTREAM_BACKOFF_SECONDS[0]
    busy = [image2.retry_delay_seconds(1, _error(status=503, message="system cpu overloaded (current: 92.5%, threshold: 90%)")) for _ in range(20)]
    assert all(plain * 1.5 <= value <= plain * 1.5 * 1.3 for value in busy)


def test_other_retryable_errors_keep_the_fixed_interval():
    assert image2.retry_delay_seconds(1, _error(code="network_error", status=None, message="timeout")) == image2.RETRY_DELAY
    assert image2.retry_delay_seconds(2, None) == image2.RETRY_DELAY


def test_gateway_limits_concurrent_reference_generations(monkeypatch):
    monkeypatch.setattr(image2, "IMAGE_API_MAX_CONCURRENCY", 2)
    image2._UPSTREAM_SEMAPHORES.clear()
    running = 0
    peak = 0

    async def fake_unbounded(*args, **kwargs):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "ok"

    monkeypatch.setattr(image2, "_generate_reference_image_unbounded", fake_unbounded)

    async def main():
        return await asyncio.gather(*(image2.generate_reference_image(prompt=str(i)) for i in range(6)))

    assert asyncio.run(main()) == ["ok"] * 6
    assert peak == 2


def test_zero_disables_the_gateway(monkeypatch):
    monkeypatch.setattr(image2, "IMAGE_API_MAX_CONCURRENCY", 0)
    peak = 0
    running = 0

    async def fake_unbounded(*args, **kwargs):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return "ok"

    monkeypatch.setattr(image2, "_generate_reference_image_unbounded", fake_unbounded)

    async def main():
        await asyncio.gather(*(image2.generate_reference_image(prompt=str(i)) for i in range(5)))

    asyncio.run(main())
    assert peak == 5


def test_backoff_sequence_gives_the_gateway_time_to_recover_and_allows_a_fourth_attempt():
    """日志里三次重试在约 45 秒内用完且全部撞上同一时段的 500/502/503；现在累计等待数十秒，并多给一次机会。"""
    assert image2.MAX_RETRIES >= 4
    errors = [_error(), _error(status=502, message="<html>502 Bad Gateway</html>"), _error(status=503, message="system cpu overloaded")]
    waits = [image2.retry_delay_seconds(attempt, err) for attempt, err in enumerate(errors, start=1)]
    assert waits[0] < waits[1] < waits[2]
    assert sum(waits) > 40
