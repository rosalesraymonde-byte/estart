from flask import Flask, render_template, request, redirect, url_for, session, send_file
from datetime import datetime
import json
import csv
import io
import requests

app = Flask(__name__)
app.secret_key = "replace_with_a_random_secret"

TRUSTED_PUBLIC_IPS = ["27.49.13.224"]

# ------------------- Helpers -------------------
def load_users():
    try:
        with open("users.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_users(users):
    with open("users.json", "w") as f:
        json.dump(users, f, indent=4)

def load_attendance():
    try:
        with open("attendance.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

def save_attendance(attendance_log):
    with open("attendance.json", "w") as f:
        json.dump(attendance_log, f, indent=4)

def get_client_public_ip():
    try:
        response = requests.get('https://api.ipify.org?format=json', timeout=5)
        return response.json().get("ip")
    except Exception:
        return None

# ------------------- Routes -------------------
@app.route("/")
def index():
    return redirect(url_for("login"))

# ------------------- Login -------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    client_ip = get_client_public_ip()
    is_trusted_ip = client_ip in TRUSTED_PUBLIC_IPS

    message = ""  # Initialize message variable

    if request.method == "POST":
        emp_id = request.form.get("emp_id")
        password = request.form.get("password")
        users = load_users()

        if emp_id in users and users[emp_id]["password"] == password:
            session["user"] = emp_id
            session["role"] = users[emp_id]["role"]
            if users[emp_id]["role"].lower() == "admin":
                return redirect(url_for("admin_dashboard"))
            else:
                return redirect(url_for("user_dashboard"))
        else:
            message = "Invalid credentials. Please try again."  # Set error message

    # Render appropriate login template with message
    if is_trusted_ip:
        return render_template("login.html", message=message)
    else:
        return render_template("wfh_login.html", message=message)

# ------------------- User Dashboard -------------------
@app.route("/user_dashboard", methods=["GET", "POST"])
def user_dashboard():
    if "user" not in session or session.get("role").lower() != "user":
        return redirect(url_for("login"))

    emp_id = session["user"]
    users = load_users()
    attendance_log = load_attendance()

    # Ensure this user's log always exists (append safe)
    if emp_id not in attendance_log:
        attendance_log[emp_id] = []

    # Device/IP tracker
    device_tracker = {}
    for u, logs in attendance_log.items():
        for entry in logs:
            key = f"{entry['ip']}|{entry['device']}"
            if entry['action'] == "Time In":
                device_tracker[key] = u
            elif entry['action'] == "Time Out" and key in device_tracker:
                del device_tracker[key]

    message = ""
    client_ip = request.remote_addr
    device = request.headers.get('User-Agent', 'Unknown')
    key = f"{client_ip}|{device}"

    if request.method == "POST":
        action = request.form.get("action")
        timestamp = datetime.now().strftime("%Y-%m-%d %I:%M:%S %p")

        # Check last action for this user
        last_action = attendance_log[emp_id][-1]["action"] if attendance_log[emp_id] else None

        if action == "Time In":
            if last_action == "Time In":
                message = "You are already timed in."
            elif key in device_tracker and device_tracker[key] != emp_id:
                message = f"Cannot Time In: This device/IP is already in use by {device_tracker[key]}"
            else:
                attendance_log[emp_id].append({
                    "action": "Time In",
                    "time": timestamp,
                    "ip": client_ip,
                    "device": device
                })
                device_tracker[key] = emp_id
                save_attendance(attendance_log)
                message = f"Time In recorded at {timestamp}"

        elif action == "Time Out":
            if last_action != "Time In":
                message = "You cannot time out without timing in first."
            elif key not in device_tracker:
                message = "Cannot Time Out: No active Time In on this device/IP"
            elif device_tracker[key] != emp_id:
                alert_msg = f"ALERT: {emp_id} tried to Time Out using device/IP of {device_tracker[key]}"
                print(alert_msg)
                message = "Time Out blocked! Admin has been notified."
            else:
                attendance_log[emp_id].append({
                    "action": "Time Out",
                    "time": timestamp,
                    "ip": client_ip,
                    "device": device
                })
                del device_tracker[key]
                save_attendance(attendance_log)
                message = f"Time Out recorded at {timestamp}"

    # Button states based only on valid last action
    last_action = attendance_log[emp_id][-1]["action"] if attendance_log[emp_id] else None
    time_in_disabled = last_action == "Time In"
    time_out_disabled = last_action != "Time In" or device_tracker.get(key) != emp_id

    return render_template(
        "user_dashboard.html",
        emp_id=emp_id,
        user=users[emp_id],
        message=message,
        log=attendance_log[emp_id][::-1],  # Newest first
        time_in_disabled=time_in_disabled,
        time_out_disabled=time_out_disabled
    )

# ------------------- Admin Dashboard -------------------
@app.route("/admin_dashboard")
def admin_dashboard():
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    return render_template("admin_dashboard.html", users=users)

# ------------------- Manage Users (Add/Edit) -------------------
@app.route("/add_users", methods=["GET", "POST"])
@app.route("/add_users/<emp_id>", methods=["GET", "POST"])
def add_users(emp_id=None):
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    message = ""
    user_data = {}

    # Prefill if editing
    if emp_id:
        user_data = users.get(emp_id)
        if not user_data:
            return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        form_emp_id = request.form.get("emp_id") or emp_id
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email")
        password = request.form.get("password")
        role = request.form.get("role")

        if emp_id:  # Edit user
            user = users[emp_id]
            user['first_name'] = first_name
            user['last_name'] = last_name
            user['email'] = email
            if password:
                user['password'] = password
            user['role'] = role
            save_users(users)
            message = f"User {first_name} {last_name} updated."
        else:  # Add user
            if form_emp_id in users:
                message = "Employee ID already exists."
            else:
                users[form_emp_id] = {
                    "first_name": first_name,
                    "last_name": last_name,
                    "email": email,
                    "password": password,
                    "role": role
                }
                save_users(users)
                message = f"User {first_name} {last_name} added."

        return redirect(url_for("admin_dashboard"))

    return render_template(
        "add_users.html",
        user=user_data,
        emp_id=emp_id,
        message=message
    )

# ------------------- View/Delete/Export Users -------------------
@app.route("/view_user/<emp_id>")
def view_user(emp_id):
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    attendance_log = load_attendance()
    log = attendance_log.get(emp_id, [])

    return render_template("view_user_attendance.html", user=users.get(emp_id, {}), log=log)

@app.route("/delete_user/<emp_id>")
def delete_user(emp_id):
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    if emp_id in users:
        del users[emp_id]
        save_users(users)
    return redirect(url_for("admin_dashboard"))

@app.route("/export_user/<emp_id>")
def export_user(emp_id):
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    user = users.get(emp_id)
    if not user:
        return redirect(url_for("admin_dashboard"))

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "First Name", "Last Name", "Email", "Role"])
    writer.writerow([emp_id, user["first_name"], user["last_name"], user["email"], user["role"]])
    output.seek(0)

    return send_file(io.BytesIO(output.getvalue().encode()),
                     mimetype="text/csv",
                     as_attachment=True,
                     download_name=f"{emp_id}.csv")

@app.route("/export_all_users")
def export_all_users():
    if "user" not in session or session.get("role").lower() != "admin":
        return redirect(url_for("login"))

    users = load_users()
    attendance_log = load_attendance()

    output = io.StringIO()
    writer = csv.writer(output)

    # Header row
    writer.writerow(["Employee ID", "First Name", "Last Name", "Time In", "Time Out"])

    for emp_id, user in users.items():
        logs = attendance_log.get(emp_id, [])
        # Organize by date
        date_dict = {}
        for entry in logs:
            date_only = entry["time"].split(" ")[0]  # YYYY-MM-DD
            if date_only not in date_dict:
                date_dict[date_only] = {"Time In": None, "Time Out": None}

            if entry["action"] == "Time In":
                date_dict[date_only]["Time In"] = entry["time"]
            elif entry["action"] == "Time Out":
                date_dict[date_only]["Time Out"] = entry["time"]

        # Write per date
        if not date_dict:  # No attendance
            writer.writerow([emp_id, user["first_name"], user["last_name"], user.get("email",""), "", "", ""])
        else:
            for date, times in date_dict.items():
                writer.writerow([
                    emp_id,
                    user["first_name"],
                    user["last_name"],
                    user.get("email",""),
                    date,
                    times["Time In"] or "",
                    times["Time Out"] or ""
                ])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="all_users_attendance.csv"
    )

# ------------------- Logout -------------------
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":

    app.run(host="0.0.0.0", port=5000, debug=True)

