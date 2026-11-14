from services import deconstruction


def test_stage2_uses_five_parallel_chapter_requests():
    assert deconstruction.STAGE2_CHAPTER_CONCURRENCY == 5


def test_stage2_progress_flushes_in_batches_and_at_completion():
    flushed = [
        completed
        for completed in range(1, 26)
        if deconstruction.should_flush_stage2_progress(completed, 25)
    ]

    assert flushed == [10, 20, 25]


def test_stage2_progress_flushes_at_completion_for_small_books():
    flushed = [
        completed
        for completed in range(1, 4)
        if deconstruction.should_flush_stage2_progress(completed, 3)
    ]

    assert flushed == [3]
