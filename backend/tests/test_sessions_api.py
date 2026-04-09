"""Tests for /api/sessions CRUD endpoints."""

import pytest


def _create_session(client, name="Test Session", target_url="https://www.saucedemo.com"):
    resp = client.post("/api/sessions/", json={
        "name": name,
        "description": "desc",
        "target_url": target_url,
    })
    assert resp.status_code == 201, resp.text
    return resp.json()


class TestCreateSession:
    def test_returns_201_with_id(self, client):
        data = _create_session(client)
        assert "id" in data
        assert data["name"] == "Test Session"

    def test_defaults_target_url(self, client):
        resp = client.post("/api/sessions/", json={"name": "Minimal"})
        assert resp.status_code == 201
        assert "saucedemo" in resp.json()["target_url"]

    def test_initial_status_is_created(self, client):
        data = _create_session(client)
        assert data["status"] == "created"

    def test_initial_stage_is_intake(self, client):
        data = _create_session(client)
        assert data["current_stage"] == "intake"

    def test_missing_name_returns_422(self, client):
        resp = client.post("/api/sessions/", json={"description": "no name"})
        assert resp.status_code == 422


class TestListSessions:
    def test_empty_list(self, client):
        resp = client.get("/api/sessions/")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_created_session_appears_in_list(self, client):
        _create_session(client, name="ListMe")
        resp = client.get("/api/sessions/")
        names = [s["name"] for s in resp.json()]
        assert "ListMe" in names


class TestGetSession:
    def test_get_existing(self, client):
        created = _create_session(client, name="GetMe")
        resp = client.get(f"/api/sessions/{created['id']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == created["id"]

    def test_get_missing_returns_404(self, client):
        resp = client.get("/api/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404


class TestDeleteSession:
    def test_delete_existing(self, client):
        created = _create_session(client, name="DeleteMe")
        resp = client.delete(f"/api/sessions/{created['id']}")
        assert resp.status_code == 204

    def test_deleted_session_not_found(self, client):
        created = _create_session(client, name="GoneSession")
        client.delete(f"/api/sessions/{created['id']}")
        resp = client.get(f"/api/sessions/{created['id']}")
        assert resp.status_code == 404

    def test_delete_missing_returns_404(self, client):
        resp = client.delete("/api/sessions/00000000-0000-0000-0000-000000000000")
        assert resp.status_code == 404
