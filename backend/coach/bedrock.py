"""Amazon Bedrock: Claude Haiku 5.5 in your own AWS account, the coach's default model.

Two quirks of Claude Haiku 5.5 shape the settings here (both seen live on 2026-10-07):
- It rejects the temperature parameter ("`temperature` is deprecated for this model"), so no
  call sends one. Every Claude model on Bedrock has sensible defaults.
- It reasons before it answers, and those hidden tokens count against max_tokens: a 700-token
  chat limit ran out on a 170-word reply. The limits in llm.BUDGETS are roomy; you pay only for
  the tokens the model actually writes.

A brand-new AWS account needs two one-time things before Claude answers: Anthropic's use-case
form, and a payment method on the paid plan (Claude is sold through AWS Marketplace). Bedrock may
also hold a new account for a few days while AWS verifies it. explain() turns each of Bedrock's
errors into the fix.
"""

from __future__ import annotations

import re
import threading
import time
from typing import Any

from .config import DEFAULT_BEDROCK_MODEL, Settings

PROFILE_PREFIX = re.compile(r"^(us|eu|apac|jp|au|ca|global|us-gov)\.")
CLAUDE_ID = re.compile(r"anthropic\.claude-([a-z]+)-(\d+)-(\d+)")
CREDENTIAL_ERRORS = {
    "NoCredentialsError", "PartialCredentialsError", "CredentialRetrievalError", "NoAuthTokenError",
    "UnauthorizedSSOTokenError", "SSOTokenLoadError", "TokenRetrievalError",
}
CREDENTIAL_CODES = {
    "ExpiredTokenException", "ExpiredToken", "UnrecognizedClientException", "InvalidSignatureException",
    "InvalidClientTokenId",
}
BUSY_CODES = {"ThrottlingException", "throttlingException", "ServiceQuotaExceededException", "TooManyRequestsException"}
FLAKY_CODES = {"ModelNotReadyException", "ServiceUnavailableException", "InternalServerException", "ModelErrorException"}
NETWORK_ERRORS = {"EndpointConnectionError", "ConnectTimeoutError", "ReadTimeoutError", "ConnectionClosedError"}
STATUS_TTL_OK = 600  # seconds; the UI asks for health every 20 s, so cache the answer
STATUS_TTL_FAILED = 20  # re-check soon, so the pill turns green once the account is fixed

_lock = threading.RLock()
_sessions: dict[str, Any] = {}
_status: dict[tuple[str, str], tuple[float, dict[str, Any]]] = {}


def model_label(model_id: str) -> str:
    """'us.anthropic.claude-haiku-5-5' -> 'Claude Haiku 5.5'. Any other id comes back without its region prefix."""
    base = PROFILE_PREFIX.sub("", model_id)
    match = CLAUDE_ID.match(base)
    return f"Claude {match[1].title()} {match[2]}.{match[3]}" if match else base


def session(region: str) -> Any:
    """One boto3 session per region, so credentials load once rather than on every model call."""
    import boto3

    with _lock:
        if region not in _sessions:
            _sessions[region] = boto3.Session(region_name=region)
        return _sessions[region]


def build(settings: Settings, max_tokens: int) -> Any:
    from strands.models.bedrock import BedrockModel

    with _lock:  # a boto3 session is not thread-safe while it creates clients
        return BedrockModel(boto_session=session(settings.aws_region), model_id=settings.bedrock_model_id,
                            max_tokens=max_tokens)


def check(settings: Settings, client: Any = None) -> dict[str, Any]:
    """Ask the model for one word. About 20 tokens, a ten-thousandth of a cent, and the only test that
    proves this account can use the model: Bedrock enables a third-party model on its first call."""
    from botocore.exceptions import ClientError

    try:
        if client is None:
            with _lock:
                client = session(settings.aws_region).client("bedrock-runtime")
        client.converse(
            modelId=settings.bedrock_model_id,
            messages=[{"role": "user", "content": [{"text": "Reply with the single word OK."}]}],
            inferenceConfig={"maxTokens": 16},
        )
    except Exception as exc:  # noqa: BLE001 - every failure becomes a fix-it message
        return {"reachable": isinstance(exc, ClientError), "model_ready": False, "detail": explain(exc, settings)}
    return {"reachable": True, "model_ready": True, "detail": "ok"}


def status(settings: Settings, *, fresh: bool = False) -> dict[str, Any]:
    """check(), cached: a working model is re-checked every 10 minutes, a failing one every 20 seconds."""
    key = (settings.aws_region, settings.bedrock_model_id)
    now = time.monotonic()
    with _lock:
        hit = _status.get(key)
    if hit and not fresh and now < hit[0]:
        return dict(hit[1])
    result = check(settings)
    with _lock:
        _status[key] = (now + (STATUS_TTL_OK if result["model_ready"] else STATUS_TTL_FAILED), result)
    return dict(result)


def _code(exc: BaseException) -> str:
    """The AWS error code, also when Strands wrapped the ClientError (for example ModelThrottledException)."""
    for err in (exc, exc.__cause__):
        response = getattr(err, "response", None)
        if isinstance(response, dict):
            return str(response.get("Error", {}).get("Code", ""))
    return ""


def explain(exc: BaseException, settings: Settings) -> str:
    """Say what went wrong in words a workshop attendee can act on. Message checks come first:
    Bedrock reports a missing use-case form as ResourceNotFoundException and a missing payment
    method as AccessDeniedException, and each needs a different fix."""
    label = model_label(settings.bedrock_model_id)
    name, code, low = exc.__class__.__name__, _code(exc), str(exc).lower()
    if name in CREDENTIAL_ERRORS or code in CREDENTIAL_CODES or "security token" in low:
        return "Amazon Bedrock needs working AWS credentials. Run 'aws login', then restart the backend."
    if "use case" in low:
        return (f"Anthropic asks for a one-time use-case form before an AWS account can use {label}. In the "
                f"Amazon Bedrock console, open Model catalog, choose {label} and submit the form. Access "
                "usually starts within a few minutes.")
    if "payment" in low:
        return ("Claude models are sold through AWS Marketplace, so your AWS account needs a payment method. "
                "Add one in the Billing console under Payment preferences, then try again in a few minutes.")
    if "marketplace" in low:
        return (f"The first use of {label} in an AWS account needs AWS Marketplace permissions "
                "(aws-marketplace:Subscribe). Try once as an administrator.")
    if "channel program" in low:
        return (f"AWS accounts set up through an AWS partner (the channel program) can't use {label}. Use an AWS "
                "account you created yourself, or the free local model: COACH_PROVIDER=ollama.")
    if "operation not allowed" in low or "verification is in progress" in low:
        return ("Amazon Bedrock is still verifying this new AWS account. That can take a few days and only AWS "
                "can finish it, so open an AWS Support case if it lasts. Meanwhile, use the free local model: "
                "COACH_PROVIDER=ollama.")
    if "inference profile" in low:
        return (f"{settings.bedrock_model_id} has to be called through an inference profile. Use the id with "
                f"its region prefix, for example COACH_BEDROCK_MODEL={DEFAULT_BEDROCK_MODEL}.")
    if "model identifier is invalid" in low or code == "ResourceNotFoundException":
        return (f"Bedrock in {settings.aws_region} has no model called {settings.bedrock_model_id}. The default "
                f"({DEFAULT_BEDROCK_MODEL}) runs from US regions: set AWS_REGION=us-east-1 in backend/.env.")
    if code == "AccessDeniedException":
        return (f"This AWS account or user can't use {label} yet. Check that your user may call Amazon Bedrock "
                "(bedrock:InvokeModel), that the account is on the paid plan (the free plan blocks paid AWS "
                f"Marketplace products such as Claude), and that {label} shows as available in the Bedrock "
                "console's Model catalog. A use-case form you just sent can also still be pending: AWS emails you "
                "when it's done. To carry on without AWS, use the free local model: COACH_PROVIDER=ollama.")
    if code in BUSY_CODES or name == "ModelThrottledException":
        return "Amazon Bedrock is busy right now (throttled). Wait a few seconds and try again."
    if name in NETWORK_ERRORS or isinstance(exc, ConnectionError):
        return "Can't reach Amazon Bedrock. Check your internet connection, then try again."
    if name == "MaxTokensReachedException":
        return "The model ran out of room for its answer. Try again."
    if code in FLAKY_CODES:
        return "Amazon Bedrock had a temporary problem. Try again in a moment."
    return f"Amazon Bedrock request failed ({code or name}): {str(exc)[:200]}"
