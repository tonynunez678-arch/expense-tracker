"""Dashboard, add/edit/delete expenses, and CSV import/export."""

import csv
import io
from collections import defaultdict
from datetime import date, datetime

from flask import (
    Blueprint,
    Response,
    abort,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func, select

from . import db
from .models import CATEGORIES, Expense
from .money import format_cents, parse_amount

bp = Blueprint("expenses", __name__)

CSV_HEADER = ["date", "amount", "category", "description"]
MAX_IMPORT_ROWS = 5000


# ---------------------------------------------------------------- helpers ---


def shift_month(year, month, delta):
    """Move (year, month) forward or back by `delta` months."""
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def month_bounds(year, month):
    """Return (first day of month, first day of the next month)."""
    next_year, next_month = shift_month(year, month, 1)
    return date(year, month, 1), date(next_year, next_month, 1)


def parse_month(text):
    """Parse "2026-11" into (2026, 11); fall back to the current month."""
    try:
        parsed = datetime.strptime(text or "", "%Y-%m")
        return parsed.year, parsed.month
    except ValueError:
        today = date.today()
        return today.year, today.month


def get_own_expense(expense_id):
    """Fetch an expense, returning 404 if it doesn't exist OR isn't yours.

    Using 404 (not 403) avoids revealing that another user's expense exists.
    """
    expense = db.session.get(Expense, expense_id)
    if expense is None or expense.user_id != current_user.id:
        abort(404)
    return expense


def validate_expense(date_text, amount_text, category, description):
    """Validate raw form/CSV values. Returns (clean_values, error_message)."""
    try:
        spent_on = date.fromisoformat((date_text or "").strip())
    except ValueError:
        return None, "Date must be in YYYY-MM-DD format."
    try:
        amount_cents = parse_amount(amount_text)
    except ValueError as exc:
        return None, str(exc)
    category = (category or "").strip()
    if category not in CATEGORIES:
        return None, f"Category must be one of: {', '.join(CATEGORIES)}."
    description = (description or "").strip()
    if len(description) > 200:
        return None, "Description must be 200 characters or fewer."
    return {
        "spent_on": spent_on,
        "amount_cents": amount_cents,
        "category": category,
        "description": description,
    }, None


# ----------------------------------------------------------------- routes ---


@bp.route("/")
@login_required
def dashboard():
    year, month = parse_month(request.args.get("month"))
    start, end = month_bounds(year, month)
    in_month = (
        Expense.user_id == current_user.id,
        Expense.spent_on >= start,
        Expense.spent_on < end,
    )

    expenses = db.session.scalars(
        select(Expense)
        .where(*in_month)
        .order_by(Expense.spent_on.desc(), Expense.id.desc())
    ).all()

    # Let the database do the grouping and summing.
    by_category = db.session.execute(
        select(Expense.category, func.sum(Expense.amount_cents))
        .where(*in_month)
        .group_by(Expense.category)
        .order_by(func.sum(Expense.amount_cents).desc())
    ).all()
    month_total = sum(total for _, total in by_category)

    # Spending trend for the 6 months ending with the selected month.
    first_year, first_month = shift_month(year, month, -5)
    trend_start, _ = month_bounds(first_year, first_month)
    trend_rows = db.session.execute(
        select(Expense.spent_on, Expense.amount_cents).where(
            Expense.user_id == current_user.id,
            Expense.spent_on >= trend_start,
            Expense.spent_on < end,
        )
    ).all()
    totals = defaultdict(int)
    for spent_on, cents in trend_rows:
        totals[(spent_on.year, spent_on.month)] += cents
    trend = []
    for offset in range(6):
        y, m = shift_month(first_year, first_month, offset)
        trend.append({"label": date(y, m, 1).strftime("%b %Y"), "cents": totals[(y, m)]})

    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)

    return render_template(
        "dashboard.html",
        expenses=expenses,
        by_category=by_category,
        month_total=month_total,
        month_label=start.strftime("%B %Y"),
        month_value=f"{year:04d}-{month:02d}",
        prev_month=f"{prev_year:04d}-{prev_month:02d}",
        next_month=f"{next_year:04d}-{next_month:02d}",
        trend=trend,
        top_category=by_category[0][0] if by_category else None,
    )


@bp.route("/expenses/new", methods=["GET", "POST"])
@login_required
def add_expense():
    form = request.form
    if request.method == "POST":
        values, error = validate_expense(
            form.get("spent_on"), form.get("amount"),
            form.get("category"), form.get("description"),
        )
        if error:
            flash(error, "error")
        else:
            db.session.add(Expense(user_id=current_user.id, **values))
            db.session.commit()
            flash("Expense added.", "success")
            return redirect(url_for(
                "expenses.dashboard", month=values["spent_on"].strftime("%Y-%m")
            ))

    return render_template(
        "expense_form.html",
        title="Add expense",
        categories=CATEGORIES,
        form={
            "spent_on": form.get("spent_on", date.today().isoformat()),
            "amount": form.get("amount", ""),
            "category": form.get("category", "Food"),
            "description": form.get("description", ""),
        },
    )


@bp.route("/expenses/<int:expense_id>/edit", methods=["GET", "POST"])
@login_required
def edit_expense(expense_id):
    expense = get_own_expense(expense_id)
    form = request.form
    if request.method == "POST":
        values, error = validate_expense(
            form.get("spent_on"), form.get("amount"),
            form.get("category"), form.get("description"),
        )
        if error:
            flash(error, "error")
        else:
            for key, value in values.items():
                setattr(expense, key, value)
            db.session.commit()
            flash("Expense updated.", "success")
            return redirect(url_for(
                "expenses.dashboard", month=expense.spent_on.strftime("%Y-%m")
            ))

    return render_template(
        "expense_form.html",
        title="Edit expense",
        categories=CATEGORIES,
        expense=expense,
        form={
            "spent_on": form.get("spent_on", expense.spent_on.isoformat()),
            "amount": form.get("amount", f"{expense.amount_cents / 100:.2f}"),
            "category": form.get("category", expense.category),
            "description": form.get("description", expense.description),
        },
    )


@bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
def delete_expense(expense_id):
    expense = get_own_expense(expense_id)
    month = expense.spent_on.strftime("%Y-%m")
    db.session.delete(expense)
    db.session.commit()
    flash("Expense deleted.", "success")
    return redirect(url_for("expenses.dashboard", month=month))


@bp.route("/export.csv")
@login_required
def export_csv():
    expenses = db.session.scalars(
        select(Expense)
        .where(Expense.user_id == current_user.id)
        .order_by(Expense.spent_on, Expense.id)
    ).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(CSV_HEADER)
    for e in expenses:
        description = e.description
        # Prevent "CSV injection": spreadsheet apps run cells starting with
        # these characters as formulas.
        if description[:1] in ("=", "+", "-", "@"):
            description = "'" + description
        writer.writerow([
            e.spent_on.isoformat(), f"{e.amount_cents / 100:.2f}", e.category, description
        ])

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=expenses.csv"},
    )


@bp.route("/import", methods=["GET", "POST"])
@login_required
def import_csv():
    if request.method == "GET":
        return render_template("import.html", header=",".join(CSV_HEADER), categories=CATEGORIES)

    upload = request.files.get("file")
    if upload is None or upload.filename == "":
        flash("Choose a CSV file to upload.", "error")
        return redirect(url_for("expenses.import_csv"))

    try:
        text = upload.read().decode("utf-8-sig")  # utf-8-sig strips Excel's BOM
    except UnicodeDecodeError:
        flash("That file isn't a UTF-8 text CSV.", "error")
        return redirect(url_for("expenses.import_csv"))

    reader = csv.DictReader(io.StringIO(text))
    fields = [f.strip().lower() for f in (reader.fieldnames or [])]
    if fields[:4] != CSV_HEADER:
        flash(f"The first row must be the header: {','.join(CSV_HEADER)}", "error")
        return redirect(url_for("expenses.import_csv"))
    reader.fieldnames = fields

    # All-or-nothing: if any row is bad, import nothing, so the user can fix the
    # file and re-upload without creating duplicates.
    new_expenses, errors = [], []
    for line_number, row in enumerate(reader, start=2):
        if len(new_expenses) + len(errors) >= MAX_IMPORT_ROWS:
            errors.append(f"Files are limited to {MAX_IMPORT_ROWS} rows.")
            break
        values, error = validate_expense(
            row.get("date"), row.get("amount"), row.get("category"), row.get("description")
        )
        if error:
            errors.append(f"Line {line_number}: {error}")
        else:
            new_expenses.append(Expense(user_id=current_user.id, **values))

    if errors:
        shown = errors[:5]
        more = f" (and {len(errors) - 5} more)" if len(errors) > 5 else ""
        flash("Nothing was imported. " + " | ".join(shown) + more, "error")
        return redirect(url_for("expenses.import_csv"))
    if not new_expenses:
        flash("That file has no expenses in it.", "error")
        return redirect(url_for("expenses.import_csv"))

    db.session.add_all(new_expenses)
    db.session.commit()
    total = sum(e.amount_cents for e in new_expenses)
    flash(f"Imported {len(new_expenses)} expenses totalling {format_cents(total)}.", "success")
    return redirect(url_for("expenses.dashboard"))
