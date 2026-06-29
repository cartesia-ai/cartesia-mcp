"""
Map MCP tool request_options onto cartesia-python v3 method kwargs.

MCP tools still accept Fern v2-style RequestOptions dicts for backward compatibility.
"""

from __future__ import annotations

import typing

if typing.TYPE_CHECKING:
    from cartesia.pagination import SyncCursorIDPage


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

        if "additional_headers" in request_options:
            kwargs["extra_headers"] = dict(request_options["additional_headers"])
        elif "headers" in request_options:
            kwargs["extra_headers"] = dict(request_options["headers"])

        if "additional_query_parameters" in request_options:
            query.update(request_options["additional_query_parameters"])
        elif "params" in request_options:
            query.update(request_options["params"])

    if query:
        kwargs["extra_query"] = query
    return kwargs
