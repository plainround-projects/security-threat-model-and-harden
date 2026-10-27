import io
import json
import logging

from notes_app.infrastructure.logging import REDACTED, JsonFormatter, configure_logging, redact


def test_sensitive_field_names_are_redacted_and_others_are_kept():
    fields = {
        "password": "p",
        "new_password": "p",
        "csrf_token": "t",
        "Authorization": "Bearer x",
        "cookie": "c",
        "session_id": "s",
        "api_key": "k",
        "client_secret": "s",
        "user_id": 7,
        "path": "/notes/1",
    }
    cleaned = redact(fields)
    assert {key for key, value in cleaned.items() if value == REDACTED} == set(fields) - {"user_id", "path"}
    assert cleaned["user_id"] == 7


def test_the_formatter_writes_one_json_object_with_extra_fields_redacted():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.json")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    logger.info("signed in", extra={"user_id": 7, "password": "hunter2-hunter2"})
    line = json.loads(stream.getvalue())
    assert line["message"] == "signed in"
    assert line["level"] == "INFO"
    assert line["user_id"] == 7
    assert line["password"] == REDACTED
    assert "hunter2" not in stream.getvalue()


def test_exceptions_are_included_as_text():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("test.exc")
    logger.handlers[:] = [handler]
    logger.propagate = False
    try:
        raise ValueError("boom")
    except ValueError:
        logger.exception("failed")
    assert "ValueError: boom" in json.loads(stream.getvalue())["exception"]


def test_configure_logging_installs_the_json_handler_on_the_root_logger():
    configure_logging("WARNING")
    root = logging.getLogger()
    assert root.level == logging.WARNING
    assert isinstance(root.handlers[0].formatter, JsonFormatter)
