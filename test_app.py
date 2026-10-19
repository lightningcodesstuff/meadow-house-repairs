"""Automated versions of the ten published judging tests."""

import pytest

from app import create_app


@pytest.fixture
def make_client(tmp_path):
    data_file = tmp_path / "jobs.json"

    def _make():
        app = create_app(data_file)
        app.config["TESTING"] = True
        return app, app.test_client()

    return _make


@pytest.fixture
def client_store(make_client):
    app, client = make_client()
    return client, app.config["STORE"]


def report(client, description, reporter, priority):
    return client.post("/jobs", data={
        "description": description, "reporter": reporter, "priority": priority,
    })


def test_1_valid_repair_report(client_store):
    client, store = client_store
    res = report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    assert res.status_code == 302
    [job] = store.all_jobs()
    assert job["id"] == "MH-0001"
    assert job["status"] == "New"
    assert job["house"] == "Meadow House"
    page = client.get("/jobs/MH-0001").get_data(as_text=True)
    for text in ("MH-0001", "Meadow House", "Garden fence damaged",
                 "Alex Morgan", "Urgent priority", "Status: New", job["created_at"][:4]):
        assert text in page
    res = report(client, "Kitchen light flickering", "Jo Patel", "Normal")
    home = client.get(res.headers["Location"]).get_data(as_text=True)
    assert "Repair job MH-0002 created" in home


@pytest.mark.parametrize("description", ["", "     "])
def test_2_description_required(client_store, description):
    client, store = client_store
    res = report(client, description, "Alex Morgan", "Normal")
    assert res.status_code == 400
    page = res.get_data(as_text=True)
    assert "Enter a description of the repair" in page
    assert 'value="Alex Morgan"' in page  # valid input preserved
    assert store.all_jobs() == []


@pytest.mark.parametrize("reporter", ["", "   "])
def test_3_reporter_required(client_store, reporter):
    client, store = client_store
    res = report(client, "Garden fence damaged", reporter, "Normal")
    assert res.status_code == 400
    page = res.get_data(as_text=True)
    assert "Enter the name of the person reporting" in page
    assert "Garden fence damaged</textarea>" in page
    assert store.all_jobs() == []


def test_4_priority_retained(client_store):
    client, store = client_store
    report(client, "Dripping tap", "Sam Lee", "Normal")
    report(client, "Boiler not working", "Sam Lee", "Urgent")
    jobs = store.all_jobs()
    assert [j["priority"] for j in jobs] == ["Normal", "Urgent"]
    assert "Normal priority" in client.get("/jobs/MH-0001").get_data(as_text=True)
    assert "Urgent priority" in client.get("/jobs/MH-0002").get_data(as_text=True)


def test_5_independent_jobs(client_store):
    client, store = client_store
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    report(client, "Kitchen light flickering", "Jo Patel", "Normal")
    before = store.get("MH-0002")
    client.post("/jobs/MH-0001/start")
    client.post("/jobs/MH-0001/progress", data={"note": "Temporary barrier fitted"})
    client.post("/jobs/MH-0001/complete", data={"completion_note": "Fence repaired and checked"})
    assert store.get("MH-0001")["status"] == "Completed"
    assert store.get("MH-0002") == before


def test_6_progress_and_history(client_store):
    client, store = client_store
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    client.post("/jobs/MH-0001/start")
    res = client.post("/jobs/MH-0001/progress", data={"note": "Temporary barrier fitted"},
                      follow_redirects=True)
    page = res.get_data(as_text=True)
    assert "Status: In Progress" in page
    assert "Temporary barrier fitted" in page
    assert "Progress note saved" in page
    history = store.get("MH-0001")["history"]
    assert [h["status"] for h in history] == ["New", "In Progress", "In Progress"]
    assert all(h["at"] for h in history)


@pytest.mark.parametrize("note", ["", "    "])
def test_7_completion_note_required(client_store, note):
    client, store = client_store
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    client.post("/jobs/MH-0001/start")
    client.post("/jobs/MH-0001/progress", data={"note": "Temporary barrier fitted"})
    before = store.get("MH-0001")
    res = client.post("/jobs/MH-0001/complete", data={"completion_note": note})
    assert res.status_code == 400
    assert "Enter a completion note" in res.get_data(as_text=True)
    assert store.get("MH-0001") == before


def test_8_complete_a_repair(client_store):
    client, store = client_store
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    client.post("/jobs/MH-0001/start")
    client.post("/jobs/MH-0001/progress", data={"note": "Temporary barrier fitted"})
    res = client.post("/jobs/MH-0001/complete",
                      data={"completion_note": "Fence repaired and checked"},
                      follow_redirects=True)
    page = res.get_data(as_text=True)
    assert "Status: Completed" in page
    assert "Fence repaired and checked" in page
    assert "Temporary barrier fitted" in page
    statuses = [h["status"] for h in store.get("MH-0001")["history"]]
    assert statuses[0] == "New" and "In Progress" in statuses and statuses[-1] == "Completed"


def test_9_refresh_persistence(make_client):
    _, client = make_client()
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    report(client, "Kitchen light flickering", "Jo Patel", "Normal")
    client.post("/jobs/MH-0001/progress", data={"note": "Temporary barrier fitted"})
    client.post("/jobs/MH-0001/complete", data={"completion_note": "Fence repaired and checked"})
    before = client.application.config["STORE"].all_jobs()

    # A brand-new app instance (like a server restart) reads the same saved data.
    app2, client2 = make_client()
    assert app2.config["STORE"].all_jobs() == before
    page = client2.get("/jobs/MH-0001").get_data(as_text=True)
    assert "Fence repaired and checked" in page and "Temporary barrier fitted" in page
    page2 = client2.get("/jobs/MH-0002").get_data(as_text=True)
    assert "Kitchen light flickering" in page2 and "Status: New" in page2


def test_10_typed_text_stays_plain(client_store):
    client, _ = client_store
    report(client, "<b>check gate</b>", "<b>Alex</b>", "Normal")
    client.post("/jobs/MH-0001/progress", data={"note": "<b>check gate</b>"})
    for url in ("/", "/jobs/MH-0001"):
        page = client.get(url).get_data(as_text=True)
        assert "<b>check gate</b>" not in page
        assert "&lt;b&gt;check gate&lt;/b&gt;" in page


def test_delete_asks_then_removes_only_that_job(client_store):
    client, store = client_store
    report(client, "Garden fence damaged", "Alex Morgan", "Urgent")
    report(client, "Kitchen light flickering", "Jo Patel", "Normal")
    kitchen = store.get("MH-0002")

    confirm = client.get("/jobs/MH-0001/delete").get_data(as_text=True)
    assert "Yes, delete job MH-0001" in confirm
    assert store.get("MH-0001") is not None  # viewing the confirm page deletes nothing

    res = client.post("/jobs/MH-0001/delete", follow_redirects=True)
    assert "Job MH-0001 deleted" in res.get_data(as_text=True)
    assert store.get("MH-0001") is None
    assert store.get("MH-0002") == kitchen
    assert client.get("/jobs/MH-0001").status_code == 404

    # IDs are never reused after a delete.
    report(client, "Dripping tap", "Sam Lee", "Normal")
    assert store.get("MH-0003") is not None


def test_delete_unknown_job_is_404(client_store):
    client, _ = client_store
    assert client.post("/jobs/MH-9999/delete").status_code == 404
