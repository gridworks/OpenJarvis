"""Tests for extended API routes."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from openjarvis.server.api_routes import include_all_routes  # noqa: E402


def _make_app():
    app = FastAPI()
    include_all_routes(app)
    return app


class TestAgentRoutes:
    def test_list_agents(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert "registered" in data
        assert "running" in data

    def test_create_agent(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/agents", json={"agent_type": "simple"})
        # May succeed or fail depending on agent_tools availability
        assert resp.status_code in (200, 501)

    def test_kill_nonexistent(self):
        client = TestClient(_make_app())
        resp = client.delete("/v1/agents/nonexistent")
        assert resp.status_code in (404, 501)


class TestMemoryRoutes:
    def test_search(self):
        client = TestClient(_make_app())
        resp = client.post("/v1/memory/search", json={"query": "test"})
        # May fail if SQLite not set up, that's ok
        assert resp.status_code in (200, 500)

    def test_stats(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/memory/stats")
        assert resp.status_code in (200, 500)


class TestBudgetRoutes:
    def test_get_budget(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/budget")
        assert resp.status_code == 200
        data = resp.json()
        assert "limits" in data
        assert "usage" in data

    def test_set_limits(self):
        client = TestClient(_make_app())
        resp = client.put("/v1/budget/limits", json={"max_tokens_per_day": 100000})
        assert resp.status_code == 200
        assert resp.json()["limits"]["max_tokens_per_day"] == 100000


class TestMetricsRoute:
    def test_metrics_endpoint(self):
        client = TestClient(_make_app())
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "openjarvis" in resp.text or "No metrics" in resp.text


class TestSkillRoutes:
    def test_list_skills(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/skills")
        assert resp.status_code == 200
        assert "skills" in resp.json()


class TestSessionRoutes:
    def test_list_sessions(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/sessions")
        assert resp.status_code == 200


class TestTraceRoutes:
    def test_list_traces_no_store(self):
        """Returns empty list when no trace_store is on app state."""
        client = TestClient(_make_app())
        resp = client.get("/v1/traces")
        assert resp.status_code == 200
        assert resp.json() == {"traces": []}

    def test_list_traces_with_store(self):
        """Traces are serialised with frontend-expected field names."""
        import time
        from unittest.mock import MagicMock

        from openjarvis.core.types import StepType, Trace, TraceStep
        from openjarvis.server.api_routes import _serialise_trace

        step = TraceStep(
            step_type=StepType.GENERATE,
            timestamp=time.time(),
            duration_seconds=1.5,
            input={"prompt": "hello"},
            output={"tokens": 42},
        )
        trace = Trace(
            trace_id="test-id-123",
            query="what is 2+2?",
            started_at=1_700_000_000.0,
            steps=[step],
        )

        result = _serialise_trace(trace)

        assert result["id"] == "test-id-123"
        assert result["query"] == "what is 2+2?"
        assert "created_at" in result
        assert result["created_at"] != ""
        assert len(result["steps"]) == 1
        s = result["steps"][0]
        assert s["step_type"] == "generate"
        assert s["duration_ms"] == pytest.approx(1500.0)
        assert "data" in s
        assert s["data"]["tokens"] == 42
        assert s["data"]["prompt"] == "hello"

    def test_get_trace_not_found(self):
        client = TestClient(_make_app())
        resp = client.get("/v1/traces/nonexistent-id")
        assert resp.status_code == 404


class TestTraceStoreBusWiring:
    def test_trace_store_subscribed_to_bus(self, tmp_path):
        """TraceStore must be subscribed to the event bus on startup."""
        from unittest.mock import MagicMock, patch

        from openjarvis.core.events import EventBus, EventType
        from openjarvis.server.app import create_app

        bus = EventBus()
        db_path = str(tmp_path / "traces.db")

        # Patch at the source module so the local import in create_app picks it up
        with patch("openjarvis.traces.store.TraceStore") as MockStore:
            mock_store = MockStore.return_value
            cfg = MagicMock()
            cfg.traces.enabled = True
            cfg.traces.db_path = db_path

            app = create_app(engine=None, model="", bus=bus, config=cfg)

        MockStore.assert_called_once_with(db_path=db_path)
        mock_store.subscribe_to_bus.assert_called_once_with(bus)
