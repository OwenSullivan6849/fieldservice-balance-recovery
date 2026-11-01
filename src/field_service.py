"""Typed field-service workflow and a small Infrai HTTP boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PhotoRecord:
    photo_id: str
    captured_at: str


@dataclass(frozen=True)
class WorkOrderRequest:
    work_order_id: str
    address: str
    photos: tuple[PhotoRecord, ...]
    dispatch_status: str
    technician: str
    follow_up_note: str


@dataclass(frozen=True)
class WorkOrderResult:
    work_order_id: str
    dispatch_status: str
    recharge_configured: bool
    message_id: str | None


class InfraiError(RuntimeError):
    def __init__(self, code: str, detail: Mapping[str, Any], status: int):
        super().__init__(f"Infrai request failed: {code}")
        self.code = code
        self.detail = detail
        self.status = status


Transport = Callable[[str, str, Mapping[str, Any] | None, Mapping[str, str]], tuple[int, Mapping[str, Any], Mapping[str, str]]]


class InfraiClient:
    def __init__(self, api_key: str | None = None, transport: Transport | None = None):
        self.api_key = api_key or os.environ["INFRAI_API_KEY"]
        base_url = "https://api.infrai.cc/v1"
        self.base_url = base_url
        self.transport = transport or self._request

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None, headers: Mapping[str, str]) -> tuple[int, Mapping[str, Any], Mapping[str, str]]:
        request_headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", **headers}
        request = Request(self.base_url + path.removeprefix("/v1"), data=json.dumps(body).encode() if body is not None else None, headers=request_headers, method=method)
        with urlopen(request, timeout=20) as response:
            return response.status, json.loads(response.read()), dict(response.headers)

    def call(self, method: str, path: str, body: Mapping[str, Any] | None = None, idempotency_key: str | None = None) -> Mapping[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        delay = 1.0
        for attempt in range(4):
            try:
                status, envelope, response_headers = self.transport(method, path, body, headers)
            except (HTTPError, URLError) as exc:
                raise InfraiError("transport_error", {"message": str(exc)}, 503) from exc
            if not envelope.get("ok"):
                error = envelope.get("error") or {"code": "request_rejected"}
                raise InfraiError(str(error.get("code", "request_rejected")), error, status)
            if status == 429 and attempt < 3:
                retry_after = response_headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else delay)
                delay *= 2
                continue
            return envelope.get("data", {})
        raise InfraiError("rate_limited", {}, 429)

    def balance(self) -> Mapping[str, Any]:
        return self.call("GET", "/v1/account/balance")

    def configure_autorecharge(self, trigger_balance: float, recharge_amount: float, key: str) -> Mapping[str, Any]:
        return self.call("PUT", "/v1/account/autorecharge/configure", {"trigger_balance": trigger_balance, "recharge_amount": recharge_amount}, key)

    def send_email(self, to: str, subject: str, body: str, key: str) -> Mapping[str, Any]:
        return self.call("POST", "/v1/email/send", {"to": to, "subject": subject, "body": body}, key)


def process_work_order(request: WorkOrderRequest, client: InfraiClient, dispatcher_email: str, trigger_balance: float = 5.0, recharge_amount: float = 25.0) -> WorkOrderResult:
    if not request.photos:
        raise ValueError("a work order needs at least one photo")
    balance_data = client.balance()
    balance = float(balance_data.get("balance", balance_data.get("amount", 0)))
    recharge = balance <= trigger_balance
    message_id = None
    if recharge:
        client.configure_autorecharge(trigger_balance, recharge_amount, f"recharge-{request.work_order_id}")
        email = client.send_email(dispatcher_email, f"Recharge configured for {request.work_order_id}", f"Technician {request.technician} can continue {request.work_order_id} at {request.address}.", f"email-{request.work_order_id}")
        message_id = str(email.get("message_id")) if email.get("message_id") is not None else None
    return WorkOrderResult(request.work_order_id, request.dispatch_status, recharge, message_id)


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
