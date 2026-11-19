import io
from datetime import date

import pytest
from sqlalchemy import select

from app import create_app, db
from app.expenses import shift_month
from app.models import Expense
from app.money import format_cents, parse_amount


@pytest.fixture
def app():
    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test",
    })
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def register(client, username="alice", password="password123"):
    return client.post("/register", data={"username": username, "password": password},
                       follow_redirects=True)


def add(client, amount="12.50", category="Food", spent_on="2026-11-03", description="Lunch"):
    return client.post("/expenses/new", data={
        "amount": amount, "category": category, "spent_on": spent_on, "description": description,
    }, follow_redirects=True)


def all_expenses(app):
    with app.app_context():
        return db.session.scalars(select(Expense)).all()


# ------------------------------------------------------------ unit tests ---

@pytest.mark.parametrize("text, cents", [
    ("12.50", 1250), ("$1,234.56", 123456), ("0.01", 1), (" 7 ", 700), ("2.005", 201),
])
def test_parse_amount_valid(text, cents):
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "0", "-5", "NaN", "Infinity", "1000000.01"])
def test_parse_amount_invalid(text):
    with pytest.raises(ValueError):
        parse_amount(text)


def test_format_cents():
    assert format_cents(123456) == "$1,234.56"
    assert format_cents(5) == "$0.05"


def test_shift_month_wraps_years():
    assert shift_month(2026, 12, 1) == (2027, 1)
    assert shift_month(2026, 1, -1) == (2025, 12)
    assert shift_month(2026, 3, -14) == (2025, 1)


# ----------------------------------------------------------- auth tests ---

def test_dashboard_requires_login(client):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_register_and_login(client):
    assert b"Welcome, alice" in register(client).data
    client.post("/logout")
    bad = client.post("/login", data={"username": "alice", "password": "wrong-password"})
    assert b"Incorrect username or password" in bad.data
    good = client.post("/login", data={"username": "alice", "password": "password123"},
                       follow_redirects=True)
    assert b"Total spent" in good.data


def test_duplicate_username_rejected(client):
    register(client)
    client.post("/logout")
    assert b"already taken" in register(client).data


def test_short_password_rejected(client):
    assert b"at least 8 characters" in register(client, password="short").data


def test_login_ignores_offsite_next(client):
    register(client)
    client.post("/logout")
    response = client.post("/login?next=//evil.example.com",
                           data={"username": "alice", "password": "password123"})
    assert response.headers["Location"] == "/"


# -------------------------------------------------------- expense tests ---

def test_add_expense_and_monthly_total(client, app):
    register(client)
    add(client, amount="12.50", spent_on="2026-11-03")
    add(client, amount="$7.25", category="Transport", spent_on="2026-11-20")
    add(client, amount="100", spent_on="2026-10-15")  # different month

    page = client.get("/?month=2026-11").data
    assert b"$19.75" in page
    assert b"$100.00" not in page
    assert [e.amount_cents for e in all_expenses(app)] == [1250, 725, 10000]


def test_invalid_expense_shows_error_and_saves_nothing(client, app):
    register(client)
    assert b"Amount must be a number" in add(client, amount="lots").data
    assert b"Category must be one of" in add(client, category="Yachts").data
    assert b"YYYY-MM-DD" in add(client, spent_on="yesterday").data
    assert all_expenses(app) == []


def test_edit_and_delete_expense(client, app):
    register(client)
    add(client)
    expense_id = all_expenses(app)[0].id

    client.post(f"/expenses/{expense_id}/edit", data={
        "amount": "20", "category": "Groceries", "spent_on": "2026-11-05", "description": "Trader Joe's",
    })
    edited = all_expenses(app)[0]
    assert (edited.amount_cents, edited.category) == (2000, "Groceries")

    client.post(f"/expenses/{expense_id}/delete")
    assert all_expenses(app) == []


def test_users_cannot_touch_each_others_expenses(client, app):
    register(client, "alice")
    add(client, description="Alice's secret purchase")
    expense_id = all_expenses(app)[0].id
    client.post("/logout")

    register(client, "mallory")
    assert client.get(f"/expenses/{expense_id}/edit").status_code == 404
    assert client.post(f"/expenses/{expense_id}/delete").status_code == 404
    assert b"secret purchase" not in client.get("/?month=2026-11").data
    assert b"secret purchase" not in client.get("/export.csv").data
    assert len(all_expenses(app)) == 1


# ------------------------------------------------------------ CSV tests ---

def upload(client, text):
    return client.post("/import", data={"file": (io.BytesIO(text.encode()), "data.csv")},
                       content_type="multipart/form-data", follow_redirects=True)


def test_csv_round_trip(client, app):
    register(client)
    add(client, amount="12.50", description="=SUM(A1)")  # formula-looking text
    exported = client.get("/export.csv").data.decode()
    assert exported.splitlines()[0] == "date,amount,category,description"
    assert "'=SUM(A1)" in exported  # neutralized for spreadsheet apps

    response = upload(client, exported)
    assert b"Imported 1 expenses" in response.data
    assert len(all_expenses(app)) == 2


def test_csv_import_is_all_or_nothing(client, app):
    register(client)
    csv_text = (
        "date,amount,category,description\n"
        "2026-11-01,10.00,Food,Good row\n"
        "2026-11-02,oops,Food,Bad amount\n"
    )
    response = upload(client, csv_text)
    assert b"Nothing was imported" in response.data
    assert b"Line 3" in response.data
    assert all_expenses(app) == []


def test_csv_import_rejects_wrong_header(client):
    register(client)
    assert b"first row must be the header" in upload(client, "foo,bar\n1,2\n").data


def test_dashboard_empty_month(client):
    register(client)
    today = date.today()
    page = client.get(f"/?month={today:%Y-%m}").data
    assert b"No expenses in" in page
