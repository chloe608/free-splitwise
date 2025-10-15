import os
import string
import random
from datetime import datetime
from decimal import Decimal, getcontext

from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
)
from flask_sqlalchemy import SQLAlchemy

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SECRET_KEY"] = os.environ.get("FS_SECRET", "dev-secret")

db = SQLAlchemy(app)


def generate_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(random.choices(alphabet, k=length))


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    first_name = db.Column(db.String(80))
    last_name = db.Column(db.String(80))


class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    code = db.Column(db.String(12), unique=True, nullable=False)


class Membership(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)


class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey("group.id"), nullable=False)
    description = db.Column(db.String(200), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class ExpenseShare(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey("expense.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    amount = db.Column(db.Float, nullable=False)



def ensure_db():
    # create database tables within the app context
    with app.app_context():
        db.create_all()

# Ensure DB is created when the module is imported / app starts
ensure_db()


def current_user():
    uname = session.get("username")
    if not uname:
        return None
    return User.query.filter_by(username=uname).first()


@app.route("/", methods=["GET", "POST"])
def index():
    # onboarding / login (username only)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        first = request.form.get("first_name", "").strip()
        last = request.form.get("last_name", "").strip()
        if not username:
            flash("Please provide a username.")
            return redirect(url_for("index"))
        user = User.query.filter_by(username=username).first()
        if not user:
            # create suggested first/last if not given
            if not first and " " in username:
                parts = username.split()
                first = parts[0]
                last = parts[-1] if len(parts) > 1 else ""
            user = User(username=username, first_name=first, last_name=last)
            db.session.add(user)
            db.session.commit()
        session["username"] = user.username
        flash(f"Logged in as {user.username}")
        return redirect(url_for("home"))

    # show onboarding / login form
    suggested_first = ""
    suggested_last = ""
    return render_template(
        "index.html", suggested_first=suggested_first, suggested_last=suggested_last
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out")
    return redirect(url_for("index"))


@app.route("/home")
def home():
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    # clear current group when on home
    session.pop("current_group_name", None)
    session.pop("current_group_id", None)
    # list groups the user is a member of
    memberships = (
        db.session.query(Group)
        .join(Membership, Membership.group_id == Group.id)
        .filter(Membership.user_id == user.id)
        .all()
    )
    return render_template("home.html", user=user, groups=memberships)


@app.route("/create_group", methods=["POST"])
def create_group():
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    name = request.form.get("group_name", "").strip()
    if not name:
        flash("Group name required")
        return redirect(url_for("home"))
    code = generate_code(6)
    while Group.query.filter_by(code=code).first():
        code = generate_code(6)
    group = Group(name=name, code=code)
    db.session.add(group)
    db.session.commit()
    # add membership
    m = Membership(user_id=user.id, group_id=group.id)
    db.session.add(m)
    db.session.commit()
    flash(f"Group '{name}' created. Share code: {code}")
    return redirect(url_for("group_view", group_id=group.id))


@app.route("/join_group", methods=["POST"])
def join_group():
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    code = request.form.get("group_code", "").strip().upper()
    if not code:
        flash("Group code required")
        return redirect(url_for("home"))
    group = Group.query.filter_by(code=code).first()
    if not group:
        flash("Group not found")
        return redirect(url_for("home"))
    exists = Membership.query.filter_by(user_id=user.id, group_id=group.id).first()
    if not exists:
        m = Membership(user_id=user.id, group_id=group.id)
        db.session.add(m)
        db.session.commit()
    flash(f"Joined group {group.name}")
    return redirect(url_for("group_view", group_id=group.id))


@app.route("/group/<int:group_id>")
def group_view(group_id):
    # ...existing code...
    # Calculate net balances, receivers, and givers (after member_ids is defined)
    # These will be filled after total_paid and total_owed are computed
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    group = Group.query.get_or_404(group_id)
    # check membership
    if not Membership.query.filter_by(user_id=user.id, group_id=group.id).first():
        flash("You are not a member of this group")
        return redirect(url_for("home"))
    expenses = Expense.query.filter_by(group_id=group.id).order_by(Expense.timestamp.desc()).all()
    # load members of the group
    members = (
        db.session.query(User)
        .join(Membership, Membership.user_id == User.id)
        .filter(Membership.group_id == group.id)
        .all()
    )
    member_ids = [m.id for m in members]
    # compute shares map for expenses
    shares = {}
    for e in expenses:
        e_shares = ExpenseShare.query.filter_by(expense_id=e.id).all()
        if e_shares:
            shares[e.id] = {s.user_id: s.amount for s in e_shares}
        else:
            # default: equal split among members
            per = round((e.amount / max(len(member_ids), 1)), 2) if member_ids else e.amount
            shares[e.id] = {uid: per for uid in member_ids}

    # compute per-member net balances (positive => others owe them)
    balances = {uid: 0.0 for uid in member_ids}
    total_paid = {uid: 0.0 for uid in member_ids}
    total_owed = {uid: 0.0 for uid in member_ids}
    for e in expenses:
        s_map = shares.get(e.id, {})
        payer = e.created_by
        total_paid[payer] += e.amount
        for uid, share_amt in s_map.items():
            total_owed[uid] += share_amt
            if uid == payer:
                # payer: others owe them part of amount
                # payer's net increases by (amount - their share)
                balances[payer] += (e.amount - share_amt)
            else:
                # non-payer: they owe share_amt
                balances[uid] -= share_amt

    # Now calculate net balances, receivers, and givers
    net_balances = {uid: round(total_paid[uid] - total_owed[uid], 2) for uid in member_ids}
    receivers = {uid: net_balances[uid] for uid in member_ids if net_balances[uid] > 0}
    givers = {uid: net_balances[uid] for uid in member_ids if net_balances[uid] < 0}

    # current user's net in this group
    current_net = balances.get(user.id, 0.0)

    # compute pairwise settlements (greedy): list of {from, to, amount}
    def compute_settlements(bal_map):
        # Use Decimal for precise rounding and to avoid tiny residuals.
        getcontext().prec = 12
        dec_bal = {uid: Decimal(str(bal_map.get(uid, 0.0))).quantize(Decimal('0.01')) for uid in bal_map}
        # creditors positive, debtors negative
        creditors = [(uid, amt) for uid, amt in dec_bal.items() if amt > Decimal('0.00')]
        debtors = [(uid, amt) for uid, amt in dec_bal.items() if amt < Decimal('0.00')]
        creditors.sort(key=lambda x: x[1], reverse=True)
        debtors.sort(key=lambda x: x[1])  # most negative first
        i = 0
        j = 0
        settlements = []
        while i < len(debtors) and j < len(creditors):
            debtor_id, debt_amt = debtors[i]
            cred_id, cred_amt = creditors[j]
            # transfer is min(creditor amount, -debtor amount)
            transfer = min(cred_amt, -debt_amt)
            transfer = transfer.quantize(Decimal('0.01'))
            if transfer <= Decimal('0.00'):
                break
            settlements.append({"from": debtor_id, "to": cred_id, "amount": float(transfer)})
            debt_amt = (debt_amt + transfer).quantize(Decimal('0.01'))
            cred_amt = (cred_amt - transfer).quantize(Decimal('0.01'))
            debtors[i] = (debtor_id, debt_amt)
            creditors[j] = (cred_id, cred_amt)
            # advance pointers when settled (within a small epsilon)
            if abs(debt_amt) <= Decimal('0.00'):
                i += 1
            if cred_amt <= Decimal('0.00'):
                j += 1
        return settlements

    settlements = compute_settlements(balances)

    # prepare user map for expense display
    user_ids = {e.created_by for e in expenses if e.created_by}
    users = User.query.filter(User.id.in_(list(user_ids))).all() if user_ids else []
    user_map = {u.id: u.username for u in users}
    # set current group in session so header can show it
    session["current_group_name"] = group.name
    session["current_group_id"] = group.id
    member_map = {m.id: m.username for m in members}
    return render_template(
        "group.html",
        group=group,
        expenses=expenses,
        user=user,
        user_map=user_map,
        members=members,
        shares=shares,
        balances=balances,
        current_net=current_net,
        settlements=settlements,
        member_map=member_map,
        total_paid=total_paid,
        total_owed=total_owed,
        net_balances=net_balances,
        receivers=receivers,
        givers=givers,
    )


@app.route("/group/<int:group_id>/add_expense", methods=["POST"])
def add_expense(group_id):
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    group = Group.query.get_or_404(group_id)
    if not Membership.query.filter_by(user_id=user.id, group_id=group.id).first():
        flash("Not a member")
        return redirect(url_for("home"))
    desc = request.form.get("description", "").strip()
    amount = request.form.get("amount", "").strip()
    try:
        amt = float(amount)
    except Exception:
        flash("Invalid amount")
        return redirect(url_for("group_view", group_id=group.id))
    if not desc:
        desc = "Expense"
    e = Expense(group_id=group.id, description=desc, amount=amt, created_by=user.id)
    db.session.add(e)
    db.session.commit()

    # Handle splits: supported modes: all, selected_even, selected_custom
    split_mode = request.form.get('split_mode', 'all')
    # members selected via checkboxes -> may be multiple
    selected = request.form.getlist('members')
    # ensure members list (as ints)
    if split_mode == 'all' or not selected:
        # split evenly among all group members
        group_members = (
            db.session.query(User)
            .join(Membership, Membership.user_id == User.id)
            .filter(Membership.group_id == group.id)
            .all()
        )
        n = len(group_members) if group_members else 1
        per = round(amt / n, 2)
        for m in group_members:
            sh = ExpenseShare(expense_id=e.id, user_id=m.id, amount=per)
            db.session.add(sh)
    elif split_mode == 'selected_even':
        # split evenly among selected members
        sel_ids = [int(x) for x in selected]
        n = len(sel_ids) if sel_ids else 1
        per = round(amt / n, 2)
        for uid in sel_ids:
            sh = ExpenseShare(expense_id=e.id, user_id=uid, amount=per)
            db.session.add(sh)
    elif split_mode == 'selected_custom':
        # custom amounts provided per user as amount_<id>
        sel_ids = [int(x) for x in selected]
        total_custom = 0.0
        custom_rows = []
        for uid in sel_ids:
            key = f'amount_{uid}'
            v = request.form.get(key, '').strip()
            try:
                vv = float(v)
            except Exception:
                vv = 0.0
            total_custom += vv
            custom_rows.append((uid, vv))
        # allow a small epsilon for rounding errors
        if round(total_custom, 2) != round(amt, 2):
            # rollback created expense and show error
            db.session.delete(e)
            db.session.commit()
            flash(f"Custom split amounts (${total_custom:.2f}) do not equal total expense (${amt:.2f}).")
            return redirect(url_for("group_view", group_id=group.id))
        for uid, vv in custom_rows:
            sh = ExpenseShare(expense_id=e.id, user_id=uid, amount=vv)
            db.session.add(sh)
    db.session.commit()
    flash("Expense added")
    return redirect(url_for("group_view", group_id=group.id))


if __name__ == "__main__":
    app.run(debug=True)
