# T12c: store flag in the Meta client

Status: spec by the orchestrator. Builder edits `autosolar/meta_client.py` only. T02 and T12b stay in force except
where this spec changes them.

## Why

The paper 2 PDF is 16 MB. Sent inline it makes a request of about 20 MB, and Meta Model API refused it (measured,
HTTP 413 `payload_too_large`: the request is too large to persist with `store=true`). A probe with `"store": false`
in the request body was accepted (measured, HTTP 200, 117,105 input tokens). The paper check does not need the
server to keep its responses, so it will send `store: false`.

## Change

`MetaClient.respond` gains one last keyword argument `store: bool | None = None`.

- When it is not None, the request body gets `"store": store`, added after every other optional field (body key
  order: model, input, tools, reasoning, include, metadata, text, store; absent ones left out).
- It must be a real `bool` (True or False) when given; anything else (0, 1, "false", None is fine) raises
  `ValueError("store must be a bool")` before the ledger check and before any request.
- When it is None the body has no `"store"` key. Nothing else changes.

## Done when

- `tests/test_meta_client_store.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/meta_client.py`; it stays ASCII.

## Test check by the orchestrator

- Reference build in scratch (the change applied to a copy of `meta_client.py`): all 10 tests in
  `tests/test_meta_client_store.py` pass, and the 31 other client tests still pass.
- 5 planted faults, each caught: flag never added; no type check; check after the budget; flag placed before
  `text`; ints accepted.
