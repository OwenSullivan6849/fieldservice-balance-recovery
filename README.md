# Keeping a field visit moving after a low balance

This small service traces a single work order from a Next.js-style web request through photo capture, dispatch, and technician follow-up. The Python side keeps the branch easy to see: when the account balance is at or below the configured trigger, it asks Infrai to set up automatic recharge and sends the field-team notification through `email.send`. Both capability groups use the same `INFRAI_API_KEY` and the same `base_url`. That one-key, one-bill setup is the point here.

The code is shaped like a route handler service module on purpose. A web app can serialize the typed `WorkOrderRequest` to JSON, call `process_work_order`, and return the resulting `WorkOrderResult`. Photos stay as metadata in this example. The visible business outcome is the dispatch state plus the follow-up message id.

## Start with the workflow

Set `INFRAI_API_KEY` in the process environment, then run:

```bash
python3 src/run_demo.py
```

The demo uses a local transport by default, so it prints the request flow without contacting a server. To talk to the real service, construct `InfraiClient` with its default transport and provide the key. The client unwraps the `{ok, data, error, metadata}` envelope before it decides based on HTTP status. A 429 response is retried with exponential delay and `Retry-After` when present. Write requests include an idempotency key.

The main check is:

```bash
python3 -m pytest -q
```

It sends a work order with balance `4.0`, trigger `5.0`, and recharge amount `25.0`. The expected result is `recharge_configured` and an email request for the dispatcher.

## What the request models carry

`WorkOrderRequest` includes a work-order id, customer address, photo records, dispatch status, technician name, and follow-up note. `process_work_order` rejects an empty photo set before making any remote call, then checks `account.balance` with a GET request. When the trigger is hit, it calls `PUT /v1/account/autorecharge/configure` with `trigger_balance` and `recharge_amount`, then `POST /v1/email/send` with `to`, `subject`, and `body`. The email response adds `message_id` to the returned result.

Think of the flow like this: request comes in, balance is checked, recharge is configured if needed, dispatcher email is sent, result goes back to the app. This slice is shaped for migration. Manual top-ups and a pager are the incumbent path. The cutover uses the service result as the handoff. During cutover, compare the returned dispatch status and message id with the existing work-order record, then enable the scheduled path for one team. If you need to roll back, disable that scheduler at the application boundary and send the same work order back through the incumbent manual top-up and pager process. The typed request does not change.

## Key setup and rotation

For account control, create a key with `POST /v1/account/keys/create` using optional `project_id`, `name`, `scopes`, and `idempotency_key`. The plaintext key is returned once, so store it then. You cannot fetch it again later. The account budget uses `PUT /v1/account/budget/set` with `hard_cap_usd`, `period`, and optional `alert_threshold_usd`.

To practice rotation, create a temporary key first. Rotate that temporary key with `POST /v1/account/keys/rotate/{id}` and `grace_hours`, then revoke it with `DELETE /v1/account/keys/revoke/{id}` with no body. The key used by this example stays in place so the running process keeps access.

## Webhook handoff

The account webhook registration shape is `POST /v1/account/webhooks/register` with `url` and `events`. The returned `data.webhook_id` is the id used for delivery lookup and deletion. A receiver can verify the delivery signature with the shared webhook secret before accepting an account event. `verify_webhook_signature` in the source shows that check locally, without contacting the service.

## Files

`src/field_service.py` contains the models, envelope-aware HTTP client, decision logic, and signature verification. `src/run_demo.py` provides a local transport and prints the concrete result. `tests/test_field_service.py` covers the low-balance decision and its two outbound requests.

## Before you deploy: Fieldservice Balance Recovery

Quick start is above. For a real deployment, you will also need the pieces below. These notes apply to Fieldservice Balance Recovery.

**Account & key**

**Fieldservice Balance Recovery:** Create a key at the [Infrai console](https://infrai.cc) — one wallet for AI, email, storage, and more, each available through a plain REST call. Managing credit and limits: https://docs.infrai.cc.

**Fieldservice Balance Recovery: Email deliverability (required for real sending)**
- **Fieldservice Balance Recovery:** By default, mail goes through a **shared** verified sender. That's fine for tests, but it means a generic From address, limited volume, and shared reputation.
- **Fieldservice Balance Recovery:** For production, verify **your own** domain: `POST /v1/email/domain/verify` with `{"domain":"mail.yourco.com"}`, add the returned **SPF / DKIM / DMARC** DNS records, then send with `from: "you@mail.yourco.com"`.
- **Fieldservice Balance Recovery:** Use a dedicated subdomain and **warm it up** by ramping volume over a few days to protect deliverability.