"""API unit/integration tests for the Personal Monitor backend.

Each test runs against a fresh in-memory SQLite database, so they are fast and
isolated and never touch the real (Neon) database.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import auth
import database
import main


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,  # one shared connection for the whole test
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    database.Base.metadata.create_all(bind=engine)
    return TestingSessionLocal


@pytest.fixture
def client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    main.app.dependency_overrides[database.get_db] = override_get_db
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()


# ---------- helpers ----------
def seed_user(session_factory, username, password, is_admin=False):
    db = session_factory()
    user = database.User(
        username=username,
        hashed_password=auth.get_password_hash(password),
        is_admin=is_admin,
    )
    db.add(user)
    db.commit()
    db.close()


def token_for(client, username, password):
    res = client.post("/token", data={"username": username, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def auth_header(client, username, password):
    return {"Authorization": f"Bearer {token_for(client, username, password)}"}


# ---------- basic ----------
def test_root_ok(client):
    res = client.get("/")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"


# ---------- auth ----------
def test_register_login_and_me(client):
    assert client.post("/register", json={"username": "alice", "password": "pw"}).status_code == 200
    headers = auth_header(client, "alice", "pw")
    me = client.get("/api/me", headers=headers)
    assert me.status_code == 200
    assert me.json() == {"username": "alice", "is_admin": False}


def test_register_duplicate_username(client):
    client.post("/register", json={"username": "bob", "password": "pw"})
    res = client.post("/register", json={"username": "bob", "password": "pw"})
    assert res.status_code == 400


def test_login_wrong_password(client):
    client.post("/register", json={"username": "carol", "password": "right"})
    res = client.post("/token", data={"username": "carol", "password": "wrong"})
    assert res.status_code == 401


def test_protected_route_requires_token(client):
    assert client.get("/api/health").status_code == 401


# ---------- health + BMI ----------
def test_health_create_computes_bmi(client):
    client.post("/register", json={"username": "h", "password": "pw"})
    headers = auth_header(client, "h", "pw")
    res = client.post(
        "/api/health",
        headers=headers,
        json={"date": "2026-06-20", "height": 175, "weight": 82, "bp_systolic": 120, "bp_diastolic": 80},
    )
    assert res.status_code == 200
    body = res.json()
    assert body["bmi"] == 26.78
    assert body["category"] == "Overweight"
    assert body["weight_diff_to_normal"] == 5.74


def test_health_normal_category(client):
    client.post("/register", json={"username": "h2", "password": "pw"})
    headers = auth_header(client, "h2", "pw")
    res = client.post("/api/health", headers=headers, json={"height": 175, "weight": 68})
    body = res.json()
    assert body["category"] == "Normal weight"
    assert body["weight_diff_to_normal"] == 0


def test_health_update_and_delete(client):
    client.post("/register", json={"username": "h3", "password": "pw"})
    headers = auth_header(client, "h3", "pw")
    rec = client.post("/api/health", headers=headers, json={"height": 170, "weight": 70}).json()

    upd = client.put(f"/api/health/{rec['id']}", headers=headers, json={"height": 170, "weight": 90})
    assert upd.status_code == 200
    assert upd.json()["weight"] == 90

    assert client.delete(f"/api/health/{rec['id']}", headers=headers).status_code == 200
    assert client.get("/api/health", headers=headers).json() == []


# ---------- finance ----------
def test_transaction_updates_and_reverses_balance(client):
    client.post("/register", json={"username": "f", "password": "pw"})
    headers = auth_header(client, "f", "pw")

    source = client.post("/api/sources", headers=headers, json={"name": "Cash", "balance": 1000}).json()
    assert source["balance"] == 1000

    tx = client.post(
        "/api/transactions",
        headers=headers,
        json={"source_id": source["id"], "amount": 150, "type": "expense", "category": "Lunch"},
    ).json()
    assert tx["source_name"] == "Cash"

    balance = client.get("/api/sources", headers=headers).json()[0]["balance"]
    assert balance == 850

    # Deleting the transaction reverses the balance change.
    assert client.delete(f"/api/transactions/{tx['id']}", headers=headers).status_code == 200
    assert client.get("/api/sources", headers=headers).json()[0]["balance"] == 1000


def test_income_increases_balance(client):
    client.post("/register", json={"username": "f2", "password": "pw"})
    headers = auth_header(client, "f2", "pw")
    source = client.post("/api/sources", headers=headers, json={"name": "Bank", "balance": 500}).json()
    client.post(
        "/api/transactions",
        headers=headers,
        json={"source_id": source["id"], "amount": 200, "type": "income", "category": "Salary"},
    )
    assert client.get("/api/sources", headers=headers).json()[0]["balance"] == 700


# ---------- admin / roles ----------
def test_admin_can_manage_users(client, session_factory):
    seed_user(session_factory, "root", "rootpw", is_admin=True)
    headers = auth_header(client, "root", "rootpw")

    # /api/me reflects admin
    assert client.get("/api/me", headers=headers).json()["is_admin"] is True

    # create
    created = client.post(
        "/api/users",
        headers=headers,
        json={"username": "newbie", "password": "pw", "is_admin": False},
    )
    assert created.status_code == 201
    new_id = created.json()["id"]

    # list
    usernames = [u["username"] for u in client.get("/api/users", headers=headers).json()]
    assert "root" in usernames and "newbie" in usernames

    # update username + password + promote
    upd = client.put(
        f"/api/users/{new_id}",
        headers=headers,
        json={"username": "promoted", "password": "newpw", "is_admin": True},
    )
    assert upd.status_code == 200
    assert upd.json()["username"] == "promoted"
    assert upd.json()["is_admin"] is True
    # new password works
    assert client.post("/token", data={"username": "promoted", "password": "newpw"}).status_code == 200

    # delete
    assert client.delete(f"/api/users/{new_id}", headers=headers).status_code == 200


def test_non_admin_forbidden(client):
    client.post("/register", json={"username": "plain", "password": "pw"})
    headers = auth_header(client, "plain", "pw")
    assert client.get("/api/users", headers=headers).status_code == 403
    assert client.post(
        "/api/users", headers=headers, json={"username": "x", "password": "y", "is_admin": False}
    ).status_code == 403


def test_admin_cannot_delete_self(client, session_factory):
    seed_user(session_factory, "root2", "pw", is_admin=True)
    headers = auth_header(client, "root2", "pw")
    me_id = [u for u in client.get("/api/users", headers=headers).json() if u["username"] == "root2"][0]["id"]
    res = client.delete(f"/api/users/{me_id}", headers=headers)
    assert res.status_code == 400


def test_admin_cannot_revoke_own_admin(client, session_factory):
    seed_user(session_factory, "root3", "pw", is_admin=True)
    headers = auth_header(client, "root3", "pw")
    me_id = [u for u in client.get("/api/users", headers=headers).json() if u["username"] == "root3"][0]["id"]
    res = client.put(f"/api/users/{me_id}", headers=headers, json={"is_admin": False})
    assert res.status_code == 400


def test_duplicate_username_on_create(client, session_factory):
    seed_user(session_factory, "root4", "pw", is_admin=True)
    headers = auth_header(client, "root4", "pw")
    client.post("/api/users", headers=headers, json={"username": "dup", "password": "pw", "is_admin": False})
    res = client.post("/api/users", headers=headers, json={"username": "dup", "password": "pw", "is_admin": False})
    assert res.status_code == 400
