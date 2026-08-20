"""Account-state API errors must translate into an actionable next step."""

from demand_radar.providers.llm.anthropic import _friendly_api_error


class _FakeAPIError(Exception):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code


def test_low_credit_balance_points_at_billing_and_clears_search_spend():
    msg = _friendly_api_error(
        _FakeAPIError(
            "Error code: 400 - {'error': {'message': 'Your credit balance is "
            "too low to access the Anthropic API.'}}",
            status_code=400,
        )
    )
    assert "console.anthropic.com" in msg
    assert "does NOT include API credits" in msg
    assert "No search spend occurred" in msg


def test_bad_key_explains_env_precedence():
    msg = _friendly_api_error(_FakeAPIError("authentication_error", status_code=401))
    assert "sk-ant-" in msg
    assert "override the file" in msg


def test_rate_limit_suggests_reuse_of_saved_evidence():
    msg = _friendly_api_error(_FakeAPIError("rate_limit_error", status_code=429))
    assert "demand-radar analyze" in msg


def test_unrecognized_error_passes_through_verbatim():
    msg = _friendly_api_error(_FakeAPIError("overloaded_error: try again", 529))
    assert msg == "Anthropic API error: overloaded_error: try again"
