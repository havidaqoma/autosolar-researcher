# T12b: structured output in the Meta client

Status: spec by the orchestrator. Builder edits `autosolar/meta_client.py` only. T02 stays in force except where
this spec changes it.

## Why

The paper check asks Muse Spark for a large JSON answer. In 5 of 6 measured runs on the Hiron paper the answer was
not usable: twice every number came back as a string, and twice the JSON broke where the statements end and the
schedule starts (stray words such as `mid{` between two objects; runs paper-20261028T033333-6db02f and
paper-20261028T033641-b0a01a). Meta Model API can constrain decoding to a JSON Schema (docs, "Structured output":
the Responses API parameter is `text.format`), so the answer always parses and always has the schema's types.

## Change

`MetaClient.respond` gains one last keyword argument `text_format: Any | None = None`.

- When it is not None, the request body gets `"text": {"format": text_format}`, added after every other optional
  field (so the key order in the body is: model, input, tools, reasoning, include, metadata, text, with the absent
  ones left out).
- When it is None, the body has no `"text"` key (the body is exactly as before).
- `text_format` must be a dict whose `"type"` is `"json_schema"` and which holds a str `"name"` and a dict
  `"schema"`; anything else raises `ValueError("text_format must be a json_schema dict")` before the ledger check
  and before any request.
- Nothing else changes: cost, ledger rows, retries and the parsed `Result` are the same.

## Done when

- `tests/test_meta_client_format.py` passes, and every test that passed before still passes.
- `tools/check_text.py` passes on `autosolar/meta_client.py`; it stays ASCII.

## Test check by the orchestrator

- Reference build in scratch (the change applied to a copy of `meta_client.py`): all 11 tests in
  `tests/test_meta_client_format.py` pass, and the 20 old client tests still pass.
- 6 planted faults, each caught: field never added; format not wrapped in `text`; no validation; validation after
  the budget check; name not checked; `text` placed before the other optional fields.
