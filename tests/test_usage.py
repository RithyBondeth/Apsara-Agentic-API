from apsara_cli.engine.usage import add_usage, normalize_usage


def test_estimates_remain_separate_from_reported_totals():
    usage = normalize_usage({
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "estimated_input_tokens": 99,
        "unreported_calls": 1,
    })

    assert usage["total_tokens"] == 15
    assert usage["estimated_input_tokens"] == 99


def test_usage_metadata_aggregates_without_inflating_tokens():
    aggregate = {}
    add_usage(aggregate, {
        "prompt_tokens": 10,
        "completion_tokens": 5,
        "provider_reported_calls": 1,
        "auxiliary_calls": 1,
    })
    add_usage(aggregate, {
        "estimated_input_tokens": 50,
        "unreported_calls": 1,
        "interrupted_calls": 1,
    })

    assert aggregate["total_tokens"] == 15
    assert aggregate["estimated_input_tokens"] == 50
    assert aggregate["provider_reported_calls"] == 1
    assert aggregate["unreported_calls"] == 1
    assert aggregate["interrupted_calls"] == 1
    assert aggregate["auxiliary_calls"] == 1
