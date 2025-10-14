import os
import string
import random
from datetime import datetime

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
    user = current_user()
    if not user:
        return redirect(url_for("index"))
    group = Group.query.get_or_404(group_id)
    # check membership
    if not Membership.query.filter_by(user_id=user.id, group_id=group.id).first():
        flash("You are not a member of this group")
        return redirect(url_for("home"))
    expenses = Expense.query.filter_by(group_id=group.id).order_by(Expense.timestamp.desc()).all()
    # set current group in session so header can show it
    session["current_group_name"] = group.name
    session["current_group_id"] = group.id
    # build a map of user ids to usernames for display
    user_ids = {e.created_by for e in expenses if e.created_by}
    users = User.query.filter(User.id.in_(list(user_ids))).all() if user_ids else []
    user_map = {u.id: u.username for u in users}
    return render_template(
        "group.html", group=group, expenses=expenses, user=user, user_map=user_map
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
    flash("Expense added")
    return redirect(url_for("group_view", group_id=group.id))


if __name__ == "__main__":
    app.run(debug=True)
