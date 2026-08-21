"""Regression checks for the persistent actuator audit trail."""

from __future__ import annotations

import gc
import tempfile
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dashboard.storage import Store
from dashboard import server


def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / "audit.db")
        store.initialize()
        store.add_event({
            "command_id": "request:7",
            "actuator": "supply",
            "requested_state": "on",
            "duration_seconds": 30,
            "source": "proposal:manual_dashboard",
            "result": "requested",
            "note": "양액 순환 확인",
        })
        store.add_event({
            "command_id": "request:7",
            "actuator": "supply",
            "requested_state": "on",
            "duration_seconds": 30,
            "source": "decision:telegram:123",
            "result": "approved",
            "note": "Telegram inline approval",
        })
        events = store.events()
        assert [event["result"] for event in events] == ["approved", "requested"]
        report_events = store.day_events(store.now()[:10])
        assert len(report_events) == 2
        assert report_events[0]["actuator"] == "supply"

        original_store, original_control = server.store, server.CONTROL_ENABLED
        server.store, server.CONTROL_ENABLED = store, False
        try:
            recommendation_id = server.add_actuator_recommendation({
                "source": "deterministic_rule",
                "severity": "warning",
                "title": "양액 공급 검토",
                "rationale": "현장 확인용 시험",
                "actuator": "supply",
                "requested_state": "on",
                "duration_seconds": 10,
                "evidence": {},
                "model": None,
            })
            result = server.decide_recommendation(recommendation_id, "approve", "telegram:123")
            assert result["status"] == "simulated"
            results = [event["result"] for event in store.events(20)]
            for expected in ("requested", "approved", "simulated"):
                assert expected in results
        finally:
            server.store, server.CONTROL_ENABLED = original_store, original_control
        del store
        gc.collect()
    print("Actuator audit tests passed")


if __name__ == "__main__":
    main()
