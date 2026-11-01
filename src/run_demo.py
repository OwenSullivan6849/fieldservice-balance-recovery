import json

from field_service import InfraiClient, PhotoRecord, WorkOrderRequest, process_work_order


def local_transport(method, path, body, headers):
    if path == "/v1/account/balance":
        return 200, {"ok": True, "data": {"balance": 4.0}, "error": None, "metadata": {}}, {}
    if path == "/v1/email/send":
        return 200, {"ok": True, "data": {"message_id": "msg-demo-001"}, "error": None, "metadata": {}}, {}
    return 200, {"ok": True, "data": {}, "error": None, "metadata": {}}, {}


request = WorkOrderRequest(
    work_order_id="WO-1042",
    address="18 Market Street",
    photos=(PhotoRecord("photo-front-door", "2026-10-25T09:00:00Z"),),
    dispatch_status="dispatched",
    technician="Mina Chen",
    follow_up_note="Confirm the repaired panel after the visit",
)
result = process_work_order(request, InfraiClient(api_key="demo-from-environment", transport=local_transport), "dispatch@example.test")
print(json.dumps(result.__dict__, indent=2))
