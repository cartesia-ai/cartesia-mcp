from cartesia_mcp.request_options import sdk_kwargs_from_request_options


def test_sdk_kwargs_forwards_extra_json_as_extra_body() -> None:
    kwargs = sdk_kwargs_from_request_options({"extra_json": {"duration": 12.0}})
    assert kwargs["extra_body"] == {"duration": 12.0}


def test_sdk_kwargs_merges_additional_body_parameters() -> None:
    kwargs = sdk_kwargs_from_request_options(
        {
            "additional_body_parameters": {"duration": 10.0},
            "extra_json": {"save": True},
        }
    )
    assert kwargs["extra_body"] == {"duration": 10.0, "save": True}


def test_sdk_kwargs_forwards_native_v3_keys() -> None:
    kwargs = sdk_kwargs_from_request_options(
        {
            "timeout": 30,
            "extra_headers": {"X-Test": "1"},
            "extra_query": {"foo": "bar"},
        }
    )
    assert kwargs["timeout"] == 30
    assert kwargs["extra_headers"] == {"X-Test": "1"}
    assert kwargs["extra_query"] == {"foo": "bar"}
