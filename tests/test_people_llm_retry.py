from types import SimpleNamespace

from openai import APIConnectionError, APIStatusError, APITimeoutError
import pytest

from company_gtm_enricher.people.llm_retry import call_with_retries
from company_gtm_enricher.people.providers import FatalProviderError


def request():
    return SimpleNamespace(url="https://api.openai.com/v1/responses", headers={})


def status_error(status, body=None):
    return APIStatusError(
        "Upstream error with secret-fixture-value",
        response=SimpleNamespace(status_code=status, request=request(), headers={}),
        body=body,
    )


class Attempts:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.events = []

    def before_attempt(self):
        self.events.append("count")

    def call(self):
        self.events.append("call")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def sleep(self, seconds):
        self.events.append(("sleep", seconds))

    def run(self, **overrides):
        return call_with_retries(self.call, before_attempt=self.before_attempt,
                                 sleep=self.sleep, **overrides)


def test_success_counts_once_and_returns_the_original_response():
    response = object()
    attempts = Attempts(response)
    assert attempts.run() is response
    assert attempts.events == ["count", "call"]


@pytest.mark.parametrize("error", [
    APITimeoutError(request()),
    APIConnectionError(request=request()),
    *[status_error(status) for status in (408, 409, 429, 500, 502, 503, 504, 599)],
])
def test_transient_request_failure_retries_and_counts_the_failed_attempt(error):
    response = object()
    attempts = Attempts(error, response)
    assert attempts.run() is response
    assert attempts.events == ["count", "call", ("sleep", 1), "count", "call"]


def test_two_retries_are_bounded_with_one_then_two_second_delays():
    attempts = Attempts(status_error(503), APITimeoutError(request()), "done")
    assert attempts.run() == "done"
    assert attempts.events == ["count", "call", ("sleep", 1), "count", "call",
                               ("sleep", 2), "count", "call"]


@pytest.mark.parametrize("max_retries", [0, 1, 2])
def test_exhausted_retries_propagate_the_final_exception_without_an_extra_sleep(max_retries):
    errors = [status_error(503) for _ in range(max_retries + 1)]
    attempts = Attempts(*errors, "must not be reached")
    with pytest.raises(APIStatusError) as caught:
        attempts.run(max_retries=max_retries)
    assert caught.value is errors[-1]
    assert attempts.events.count("count") == attempts.events.count("call") == max_retries + 1
    assert [event for event in attempts.events if isinstance(event, tuple)] == [
        ("sleep", 2 ** index) for index in range(max_retries)
    ]
    assert attempts.outcomes == ["must not be reached"]


@pytest.mark.parametrize("error", [
    *[status_error(status) for status in (400, 401, 402, 403, 404, 422, 499, 600)],
    ValueError("malformed output"),
    RuntimeError("response refused"),
    TimeoutError("non-SDK timeout"),
    ConnectionError("non-SDK connection error"),
])
def test_nontransient_failures_do_not_retry(error):
    attempts = Attempts(error, "must not be reached")
    with pytest.raises(type(error)) as caught:
        attempts.run()
    assert caught.value is error
    assert attempts.events == ["count", "call"]


def test_fatal_provider_error_never_retries_even_if_it_has_a_transient_status():
    error = FatalProviderError("Account configuration failed.")
    error.status_code = 503
    attempts = Attempts(error)
    with pytest.raises(FatalProviderError) as caught:
        attempts.run()
    assert caught.value is error
    assert attempts.events == ["count", "call"]


@pytest.mark.parametrize("body", [
    {"code": "insufficient_quota"},
    {"error": {"code": "insufficient_quota"}},
    {"code": "rate_limit", "error": {"code": "insufficient_quota"}},
])
@pytest.mark.parametrize("status", [429, 503])
def test_quota_codes_at_either_body_level_prevent_retries(body, status):
    error = status_error(status, body)
    attempts = Attempts(error)
    with pytest.raises(APIStatusError) as caught:
        attempts.run()
    assert caught.value is error
    assert attempts.events == ["count", "call"]


def test_quota_code_on_the_exception_prevents_even_a_connection_retry():
    error = APIConnectionError(request=request())
    error.code = "insufficient_quota"
    attempts = Attempts(error)
    with pytest.raises(APIConnectionError):
        attempts.run()
    assert attempts.events == ["count", "call"]


def test_account_failure_status_takes_precedence_over_a_transport_error_type():
    error = APIConnectionError(request=request())
    error.status_code = 403
    attempts = Attempts(error)
    with pytest.raises(APIConnectionError):
        attempts.run()
    assert attempts.events == ["count", "call"]


@pytest.mark.parametrize("response", [
    {"status": "completed", "output_text": "not JSON"},
    {"status": "incomplete", "output": []},
    {"status": "completed", "output": [{"type": "refusal"}]},
])
def test_unusable_model_responses_are_returned_once_for_caller_validation(response):
    attempts = Attempts(response)
    assert attempts.run() is response
    assert attempts.events == ["count", "call"]


@pytest.mark.parametrize("invalid", [-1, 3, True, False, 1.0, "2", None])
def test_retry_bound_validation_happens_before_callbacks_requests_or_sleep(invalid):
    attempts = Attempts("must not be reached")
    with pytest.raises(ValueError, match="integer from 0 to 2"):
        attempts.run(max_retries=invalid)
    assert attempts.events == []


@pytest.mark.parametrize("kwargs,message", [
    ({"call": None}, "Model request must be callable"),
    ({"before_attempt": False}, "attempt callback must be callable"),
    ({"sleep": None}, "retry sleep function must be callable"),
])
def test_invalid_callbacks_are_rejected_before_a_request(kwargs, message):
    events = []
    arguments = {"call": lambda: events.append("call"),
                 "before_attempt": lambda: events.append("count"),
                 "sleep": lambda seconds: events.append("sleep")}
    arguments.update(kwargs)
    with pytest.raises(ValueError, match=message):
        call_with_retries(**arguments)
    assert events == []


def test_callback_failure_does_not_make_or_retry_a_request():
    error = status_error(503)
    events = []

    def fail_before_attempt():
        events.append("callback")
        raise error

    with pytest.raises(APIStatusError) as caught:
        call_with_retries(lambda: events.append("call"), before_attempt=fail_before_attempt,
                          sleep=lambda seconds: events.append("sleep"))
    assert caught.value is error
    assert events == ["callback"]


def test_retry_helper_does_not_log_or_print_upstream_messages_or_bodies(capsys, caplog):
    error = status_error(503, {"error": {"message": "secret-fixture-body"}})
    attempts = Attempts(error, error, error)
    with pytest.raises(APIStatusError):
        attempts.run()
    output = capsys.readouterr()
    assert output.out == output.err == ""
    assert caplog.records == []
