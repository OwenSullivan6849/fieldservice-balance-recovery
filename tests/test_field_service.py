from src.field_service import InfraiClient, PhotoRecord, WorkOrderRequest, process_work_order


def test_low_balance_configures_recharge_and_notifies_dispatcher():
    calls = []

    def transport(method, path, body, headers):
        calls.append((method, path, body, headers))
        if path == "/v1/account/balance":
            data = {"balance": 4.0}
        elif path == "/v1/email/send":
            data = {"message_id": "msg-42"}
        else:
            data = {}
        return 200, {"ok": True, "data": data, "error": None, "metadata": {}}, {}

    request = WorkOrderRequest("WO-1", "1 Main Road", (PhotoRecord("p-1", "now"),), "dispatched", "Lee", "call customer")
    result = process_work_order(request, InfraiClient(api_key="from-environment", transport=transport), "dispatch@example.test")

    assert result.recharge_configured is True
    assert result.message_id == "msg-42"
    assert [call[1] for call in calls] == ["/v1/account/balance", "/v1/account/autorecharge/configure", "/v1/email/send"]
    assert calls[1][2] == {"trigger_balance": 5.0, "recharge_amount": 25.0}
