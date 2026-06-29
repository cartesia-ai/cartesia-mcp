"""
Map MCP tool request_options onto cartesia-python v3 method kwargs.

MCP tools still accept Fern v2-style RequestOptions dicts for backward compatibility.
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from cartesia.pagination import SyncCursorIDPage


def _merge_extra_body(
    kwargs: dict[str, typing.Any],
    extra_fields: dict[str, typing.Any],
) -> None:
    if not extra_fields:
        return
    existing = kwargs.get("extra_body")
    if isinstance(existing, dict):
        kwargs["extra_body"] = {**existing, **extra_fields}
    else:
        kwargs["extra_body"] = extra_fields


def sdk_kwargs_from_request_options(
    request_options: typing.Optional[typing.Mapping[str, typing.Any]] = None,
    *,
    extra_query: typing.Optional[typing.Mapping[str, typing.Any]] = None,
) -> dict[str, typing.Any]:
    kwargs: dict[str, typing.Any] = {}
    query = dict(extra_query or {})

    if request_options:
        if "timeout_in_seconds" in request_options:
            kwargs["timeout"] = request_options["timeout_in_seconds"]
        elif "timeout" in request_options:
            kwargs["timeout"] = request_options["timeout"]

        for key in ("extra_headers", "extra_query", "extra_body"):
            if key in request_options:
                if key == "extra_query":
                    query.update(request_options[key])
                else:
                    kwargs[key] = request_options[key]

        if "additional_headers" in request_options:
            existing = kwargs.get("extra_headers")
            headers = dict(request_options["additional_headers"])
            kwargs["extra_headers"] = {**existing, **headers} if isinstance(existing, dict) else headers
        elif "headers" in request_options:
            existing = kwargs.get("extra_headers")
            headers = dict(request_options["headers"])
            kwargs["extra_headers"] = {**existing, **headers} if isinstance(existing, dict) else headers

        if "additional_query_parameters" in request_options:
            query.update(request_options["additional_query_parameters"])
        elif "params" in request_options:
            query.update(request_options["params"])

        if "additional_body_parameters" in request_options:
            body = request_options["additional_body_parameters"]
            if isinstance(body, dict):
                _merge_extra_body(kwargs, body)

        if "extra_json" in request_options:
            extra_json = request_options["extra_json"]
            if isinstance(extra_json, dict):
                _merge_extra_body(kwargs, extra_json)

        if "idempotency_key" in request_options:
            existing = kwargs.get("extra_headers")
            headers = {"Idempotency-Key": request_options["idempotency_key"]}
            kwargs["extra_headers"] = (
                {**existing, **headers} if isinstance(existing, dict) else headers
            )

    if query:
        kwargs["extra_query"] = query
    return kwargs
