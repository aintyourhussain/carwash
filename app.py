import streamlit as st
import sqlite3
from datetime import datetime
import hashlib
import os

# =========================
# CONFIG
# =========================
APP_TITLE = "Car Wash Booking & Live Status"
DB_PATH = os.getenv("CARWASH_DB_PATH", "carwash.db")  # SQLite default

# If you want MySQL later, set env vars and adapt connector section (see notes at bottom).

# =========================
# DB HELPERS (SQLite)
# =========================
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def hash_password(pw: str) -> str:
    # Simple SHA256 hashing (good enough for DB project demo)
    return hashlib.sha256(pw.encode("utf-8")).hexdigest()

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # USERS: customer/staff/admin in one table to keep app simple
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        phone TEXT NOT NULL UNIQUE,
        email TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('Customer','Staff','Admin')),
        created_at TEXT NOT NULL
    );
    """)

    # VEHICLES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS vehicles (
        vehicle_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        plate_no TEXT NOT NULL UNIQUE,
        make TEXT,
        model TEXT,
        color TEXT,
        vehicle_type TEXT,
        FOREIGN KEY(customer_id) REFERENCES users(user_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
    );
    """)

    # PACKAGES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS packages (
        package_id INTEGER PRIMARY KEY AUTOINCREMENT,
        package_name TEXT NOT NULL UNIQUE,
        price REAL NOT NULL CHECK(price >= 0),
        duration_minutes INTEGER NOT NULL CHECK(duration_minutes > 0),
        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
    );
    """)

    # SERVICE STAGES
    cur.execute("""
    CREATE TABLE IF NOT EXISTS service_stages (
        stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
        stage_name TEXT NOT NULL UNIQUE,
        stage_order INTEGER NOT NULL UNIQUE CHECK(stage_order > 0)
    );
    """)

    # BOOKINGS
    cur.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        vehicle_id INTEGER NOT NULL,
        package_id INTEGER NOT NULL,
        booking_datetime TEXT NOT NULL,
        scheduled_datetime TEXT,
        status TEXT NOT NULL CHECK(status IN ('Booked','InProgress','Completed','Cancelled')),
        current_stage_id INTEGER,
        notes TEXT,

        FOREIGN KEY(customer_id) REFERENCES users(user_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(vehicle_id) REFERENCES vehicles(vehicle_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(package_id) REFERENCES packages(package_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(current_stage_id) REFERENCES service_stages(stage_id)
            ON UPDATE CASCADE ON DELETE SET NULL
    );
    """)

    # STAGE HISTORY
    cur.execute("""
    CREATE TABLE IF NOT EXISTS booking_stage_history (
        history_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        stage_id INTEGER NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT,
        updated_by_staff_id INTEGER NOT NULL,

        FOREIGN KEY(booking_id) REFERENCES bookings(booking_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(stage_id) REFERENCES service_stages(stage_id)
            ON UPDATE CASCADE ON DELETE RESTRICT,
        FOREIGN KEY(updated_by_staff_id) REFERENCES users(user_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
    );
    """)

    # STAFF ASSIGNMENT (M:N)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS booking_staff_assignment (
        booking_id INTEGER NOT NULL,
        staff_id INTEGER NOT NULL,
        assigned_at TEXT NOT NULL,
        PRIMARY KEY(booking_id, staff_id),
        FOREIGN KEY(booking_id) REFERENCES bookings(booking_id)
            ON UPDATE CASCADE ON DELETE CASCADE,
        FOREIGN KEY(staff_id) REFERENCES users(user_id)
            ON UPDATE CASCADE ON DELETE RESTRICT
    );
    """)

    # PAYMENT (1:1 with booking)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        payment_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL UNIQUE,
        amount REAL NOT NULL CHECK(amount >= 0),
        method TEXT NOT NULL CHECK(method IN ('Cash','Card','Online')),
        payment_status TEXT NOT NULL CHECK(payment_status IN ('Unpaid','Paid','Partial','Refunded')),
        paid_at TEXT,

        FOREIGN KEY(booking_id) REFERENCES bookings(booking_id)
            ON UPDATE CASCADE ON DELETE CASCADE
    );
    """)

    # Seed default stages
    cur.execute("SELECT COUNT(*) FROM service_stages;")
    if cur.fetchone()[0] == 0:
        stages = [("Washing", 1), ("Drying", 2), ("Polishing", 3), ("Completed", 4)]
        cur.executemany("INSERT INTO service_stages(stage_name, stage_order) VALUES(?, ?);", stages)

    # Seed some packages (optional)
    cur.execute("SELECT COUNT(*) FROM packages;")
    if cur.fetchone()[0] == 0:
        pkgs = [
            ("Basic Wash", 500, 20, 1),
            ("Standard Wash", 800, 35, 1),
            ("Premium Wash", 1200, 50, 1),
        ]
        cur.executemany(
            "INSERT INTO packages(package_name, price, duration_minutes, is_active) VALUES(?,?,?,?);",
            pkgs
        )

    # Seed an admin if none exists
    cur.execute("SELECT COUNT(*) FROM users WHERE role='Admin';")
    if cur.fetchone()[0] == 0:
        cur.execute("""
        INSERT INTO users(full_name, phone, email, password_hash, role, created_at)
        VALUES(?,?,?,?,?,?);
        """, ("Admin", "0300-0000000", "admin@carwash.local", hash_password("admin123"), "Admin", now_str()))

    conn.commit()
    conn.close()

def q(conn, sql, params=()):
    cur = conn.cursor()
    cur.execute(sql, params)
    return cur

# =========================
# AUTH
# =========================
def login(phone, password):
    conn = get_conn()
    cur = q(conn, "SELECT user_id, full_name, role FROM users WHERE phone=? AND password_hash=?",
            (phone, hash_password(password)))
    row = cur.fetchone()
    conn.close()
    return row  # (id, name, role) or None

def register_customer(full_name, phone, email, password):
    conn = get_conn()
    try:
        q(conn, """
        INSERT INTO users(full_name, phone, email, password_hash, role, created_at)
        VALUES(?,?,?,?, 'Customer', ?)
        """, (full_name, phone, email if email else None, hash_password(password), now_str()))
        conn.commit()
        return True, "Registered successfully. Please login."
    except sqlite3.IntegrityError as e:
        return False, f"Registration failed: {e}"
    finally:
        conn.close()

# =========================
# UI HELPERS
# =========================
def require_login():
    if "user" not in st.session_state:
        st.warning("Please login first.")
        st.stop()

def is_staff_or_admin():
    return st.session_state["user"]["role"] in ("Staff", "Admin")

def get_stage_list(conn):
    cur = q(conn, "SELECT stage_id, stage_name FROM service_stages ORDER BY stage_order")
    return cur.fetchall()

def get_active_packages(conn):
    cur = q(conn, "SELECT package_id, package_name, price, duration_minutes FROM packages WHERE is_active=1 ORDER BY price")
    return cur.fetchall()

# =========================
# CUSTOMER PAGES
# =========================
def page_customer_dashboard():
    st.subheader("Customer Dashboard")
    user_id = st.session_state["user"]["user_id"]

    conn = get_conn()

    st.markdown("### My Vehicles")
    cur = q(conn, "SELECT vehicle_id, plate_no, make, model, color, vehicle_type FROM vehicles WHERE customer_id=? ORDER BY vehicle_id DESC", (user_id,))
    vehicles = cur.fetchall()

    with st.expander("Add Vehicle", expanded=False):
        c1, c2 = st.columns(2)
        plate_no = c1.text_input("Plate No", key="v_plate")
        make = c2.text_input("Make", key="v_make")
        model = c1.text_input("Model", key="v_model")
        color = c2.text_input("Color", key="v_color")
        vtype = c1.text_input("Vehicle Type (Car/SUV)", key="v_type")
        if st.button("Save Vehicle"):
            try:
                q(conn, """
                INSERT INTO vehicles(customer_id, plate_no, make, model, color, vehicle_type)
                VALUES(?,?,?,?,?,?)
                """, (user_id, plate_no.strip(), make.strip() or None, model.strip() or None,
                      color.strip() or None, vtype.strip() or None))
                conn.commit()
                st.success("Vehicle added.")
                st.rerun()
            except sqlite3.IntegrityError as e:
                st.error(f"Could not add vehicle: {e}")

    if vehicles:
        for v in vehicles:
            st.write(f"• **{v[1]}** | {v[2] or '-'} {v[3] or ''} | {v[4] or '-'} | {v[5] or '-'}")
    else:
        st.info("No vehicles yet. Add one.")

    st.markdown("---")
    st.markdown("### Create Booking")
    pkgs = get_active_packages(conn)
    if not vehicles:
        st.warning("Add a vehicle first to create a booking.")
        conn.close()
        return
    if not pkgs:
        st.warning("No packages available.")
        conn.close()
        return

    vehicle_map = {f"{v[1]} (ID {v[0]})": v[0] for v in vehicles}
    pkg_map = {f"{p[1]} - Rs {p[2]} ({p[3]} min)": p[0] for p in pkgs}

    colA, colB = st.columns(2)
    vehicle_choice = colA.selectbox("Select Vehicle", list(vehicle_map.keys()))
    pkg_choice = colB.selectbox("Select Package", list(pkg_map.keys()))
    scheduled = st.text_input("Scheduled DateTime (optional, e.g. 2025-12-27 15:30)", "")
    notes = st.text_area("Notes (optional)", "")

    if st.button("Create Booking"):
        vehicle_id = vehicle_map[vehicle_choice]
        package_id = pkg_map[pkg_choice]

        # initial stage: first stage in order
        cur = q(conn, "SELECT stage_id FROM service_stages ORDER BY stage_order LIMIT 1")
        first_stage_id = cur.fetchone()[0]

        q(conn, """
        INSERT INTO bookings(customer_id, vehicle_id, package_id, booking_datetime, scheduled_datetime, status, current_stage_id, notes)
        VALUES(?,?,?,?,?,?,?,?)
        """, (user_id, vehicle_id, package_id, now_str(), scheduled.strip() or None, "Booked", first_stage_id, notes.strip() or None))
        booking_id = q(conn, "SELECT last_insert_rowid()").fetchone()[0]

        # create unpaid payment record (optional but matches requirement)
        pkg_price = q(conn, "SELECT price FROM packages WHERE package_id=?", (package_id,)).fetchone()[0]
        q(conn, """
        INSERT INTO payments(booking_id, amount, method, payment_status, paid_at)
        VALUES(?,?,?,?,?)
        """, (booking_id, float(pkg_price), "Cash", "Unpaid", None))

        conn.commit()
        st.success(f"Booking created (ID {booking_id}).")
        st.rerun()

    st.markdown("---")
    st.markdown("### My Bookings (Live Status + History)")

    cur = q(conn, """
    SELECT b.booking_id, b.booking_datetime, b.status,
           v.plate_no, p.package_name, p.price,
           s.stage_name
    FROM bookings b
    JOIN vehicles v ON v.vehicle_id=b.vehicle_id
    JOIN packages p ON p.package_id=b.package_id
    LEFT JOIN service_stages s ON s.stage_id=b.current_stage_id
    WHERE b.customer_id=?
    ORDER BY b.booking_id DESC
    """, (user_id,))
    bookings = cur.fetchall()

    if not bookings:
        st.info("No bookings yet.")
        conn.close()
        return

    for b in bookings:
        bid, bdt, status, plate, pkg, price, stage = b
        with st.expander(f"Booking #{bid} | {plate} | {pkg} | Status: {status} | Stage: {stage}"):
            st.write(f"**Booking Time:** {bdt}")
            st.write(f"**Package:** {pkg} (Rs {price})")
            st.write(f"**Current Stage:** {stage}")

            pay = q(conn, "SELECT amount, method, payment_status, paid_at FROM payments WHERE booking_id=?", (bid,)).fetchone()
            if pay:
                st.write(f"**Payment:** Rs {pay[0]} | Method: {pay[1]} | Status: {pay[2]} | Paid At: {pay[3] or '-'}")

            st.markdown("**Stage History:**")
            hist = q(conn, """
            SELECT ss.stage_name, h.start_time, h.end_time, u.full_name
            FROM booking_stage_history h
            JOIN service_stages ss ON ss.stage_id=h.stage_id
            JOIN users u ON u.user_id=h.updated_by_staff_id
            WHERE h.booking_id=?
            ORDER BY h.history_id DESC
            """, (bid,)).fetchall()

            if hist:
                for row in hist:
                    st.write(f"- {row[0]} | start: {row[1]} | end: {row[2] or '-'} | by: {row[3]}")
            else:
                st.info("No history yet (staff will update stages).")

    conn.close()


# =========================
# STAFF/ADMIN PAGES
# =========================
def page_staff_dashboard():
    st.subheader("Admin/Staff Dashboard")
    conn = get_conn()

    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["Active Bookings", "Update Stages", "Assignments", "Packages & Staff"])

    # -------------------------
    # ACTIVE BOOKINGS
    # -------------------------
    with tab1:
        st.markdown("### Active / In Progress Bookings")
        rows = q(conn, """
        SELECT b.booking_id, b.booking_datetime, b.status,
               c.full_name, v.plate_no, p.package_name,
               ss.stage_name
        FROM bookings b
        JOIN users c ON c.user_id=b.customer_id
        JOIN vehicles v ON v.vehicle_id=b.vehicle_id
        JOIN packages p ON p.package_id=b.package_id
        LEFT JOIN service_stages ss ON ss.stage_id=b.current_stage_id
        WHERE b.status IN ('Booked','InProgress')
        ORDER BY b.booking_id ASC
        """).fetchall()

        if not rows:
            st.info("No active bookings.")
        else:
            for r in rows:
                st.write(f"• **#{r[0]}** | {r[3]} | {r[4]} | {r[5]} | Status: {r[2]} | Stage: {r[6]} | Time: {r[1]}")

    # -------------------------
    # UPDATE STAGES
    # -------------------------
    with tab2:
        st.markdown("### Update Booking Stage (creates history)")
        bookings = q(conn, """
        SELECT booking_id FROM bookings
        WHERE status IN ('Booked','InProgress')
        ORDER BY booking_id ASC
        """).fetchall()
        if not bookings:
            st.info("No bookings to update.")
        else:
            booking_ids = [b[0] for b in bookings]
            bid = st.selectbox("Select Booking", booking_ids)

            stages = get_stage_list(conn)
            stage_map = {name: sid for sid, name in stages}
            stage_names = list(stage_map.keys())

            current = q(conn, """
            SELECT current_stage_id, status FROM bookings WHERE booking_id=?
            """, (bid,)).fetchone()
            current_stage_id, current_status = current
            current_stage_name = q(conn, "SELECT stage_name FROM service_stages WHERE stage_id=?", (current_stage_id,)).fetchone()
            current_stage_name = current_stage_name[0] if current_stage_name else "None"

            st.write(f"Current: **{current_stage_name}** | Booking Status: **{current_status}**")

            new_stage_name = st.selectbox("New Stage", stage_names, index=stage_names.index(current_stage_name) if current_stage_name in stage_names else 0)
            end_prev = st.checkbox("End previous stage (if any)", value=True)

            if st.button("Update Stage"):
                staff_id = st.session_state["user"]["user_id"]

                # End previous history row if requested
                if end_prev and current_stage_id is not None:
                    q(conn, """
                    UPDATE booking_stage_history
                    SET end_time=?
                    WHERE booking_id=? AND stage_id=? AND end_time IS NULL
                    """, (now_str(), bid, current_stage_id))

                new_stage_id = stage_map[new_stage_name]

                # Set booking status automatically
                new_booking_status = "InProgress"
                # If completed stage selected
                stage_order = q(conn, "SELECT stage_order FROM service_stages WHERE stage_id=?", (new_stage_id,)).fetchone()[0]
                max_order = q(conn, "SELECT MAX(stage_order) FROM service_stages").fetchone()[0]
                if stage_order == max_order:
                    new_booking_status = "Completed"

                # Update booking
                q(conn, """
                UPDATE bookings
                SET current_stage_id=?, status=?
                WHERE booking_id=?
                """, (new_stage_id, new_booking_status, bid))

                # Add history row
                q(conn, """
                INSERT INTO booking_stage_history(booking_id, stage_id, start_time, end_time, updated_by_staff_id)
                VALUES(?,?,?,?,?)
                """, (bid, new_stage_id, now_str(), None, staff_id))

                # If completed, mark payment as Paid automatically? (optional)
                if new_booking_status == "Completed":
                    # Keep as-is; staff can update payment in Assignments tab if needed
                    pass

                conn.commit()
                st.success("Stage updated + history saved.")
                st.rerun()

    # -------------------------
    # ASSIGNMENTS + PAYMENTS
    # -------------------------
    with tab3:
        st.markdown("### Staff Assignments & Payments")

        # Assign staff to booking
        booking_ids = [r[0] for r in q(conn, "SELECT booking_id FROM bookings ORDER BY booking_id DESC").fetchall()]
        if booking_ids:
            bsel = st.selectbox("Booking ID", booking_ids, key="assign_booking")
        else:
            st.info("No bookings exist yet.")
            bsel = None

        staff_rows = q(conn, "SELECT user_id, full_name, role FROM users WHERE role IN ('Staff','Admin') ORDER BY full_name").fetchall()
        staff_map = {f"{s[1]} ({s[2]}) [ID {s[0]}]": s[0] for s in staff_rows}

        if bsel and staff_rows:
            chosen_staff = st.multiselect("Assign Staff", list(staff_map.keys()))
            if st.button("Save Assignment"):
                for label in chosen_staff:
                    sid = staff_map[label]
                    try:
                        q(conn, """
                        INSERT INTO booking_staff_assignment(booking_id, staff_id, assigned_at)
                        VALUES(?,?,?)
                        """, (bsel, sid, now_str()))
                    except sqlite3.IntegrityError:
                        pass
                conn.commit()
                st.success("Assignments updated.")
                st.rerun()

            st.markdown("**Current Assigned Staff:**")
            assigned = q(conn, """
            SELECT u.full_name, u.role, a.assigned_at
            FROM booking_staff_assignment a
            JOIN users u ON u.user_id=a.staff_id
            WHERE a.booking_id=?
            ORDER BY a.assigned_at DESC
            """, (bsel,)).fetchall()
            if assigned:
                for a in assigned:
                    st.write(f"- {a[0]} ({a[1]}) | assigned_at: {a[2]}")
            else:
                st.info("No staff assigned yet.")

            st.markdown("---")
            st.markdown("**Payment Update (for selected booking):**")
            pay = q(conn, "SELECT amount, method, payment_status, paid_at FROM payments WHERE booking_id=?", (bsel,)).fetchone()
            if pay:
                amount, method, pstatus, paid_at = pay
                c1, c2 = st.columns(2)
                new_method = c1.selectbox("Method", ["Cash", "Card", "Online"], index=["Cash","Card","Online"].index(method))
                new_status = c2.selectbox("Payment Status", ["Unpaid", "Paid", "Partial", "Refunded"], index=["Unpaid","Paid","Partial","Refunded"].index(pstatus))
                paid_time = now_str() if new_status == "Paid" else None
                if st.button("Update Payment"):
                    q(conn, """
                    UPDATE payments SET method=?, payment_status=?, paid_at=?
                    WHERE booking_id=?
                    """, (new_method, new_status, paid_time, bsel))
                    conn.commit()
                    st.success("Payment updated.")
                    st.rerun()
            else:
                st.warning("No payment row found for this booking.")

    # -------------------------
    # PACKAGES + STAFF MANAGEMENT
    # -------------------------
    with tab4:
        st.markdown("### Manage Packages")
        pkgs = q(conn, "SELECT package_id, package_name, price, duration_minutes, is_active FROM packages ORDER BY package_id DESC").fetchall()
        for p in pkgs:
            st.write(f"• **{p[1]}** | Rs {p[2]} | {p[3]} min | Active: {bool(p[4])} | ID: {p[0]}")

        with st.expander("Add New Package", expanded=False):
            n = st.text_input("Package Name", key="pkg_name")
            pr = st.number_input("Price", min_value=0.0, step=50.0, key="pkg_price")
            dm = st.number_input("Duration (minutes)", min_value=1, step=5, key="pkg_dur")
            active = st.checkbox("Active", value=True, key="pkg_active")
            if st.button("Create Package"):
                try:
                    q(conn, """
                    INSERT INTO packages(package_name, price, duration_minutes, is_active)
                    VALUES(?,?,?,?)
                    """, (n.strip(), float(pr), int(dm), 1 if active else 0))
                    conn.commit()
                    st.success("Package created.")
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    st.error(f"Could not create package: {e}")

        st.markdown("---")
        st.markdown("### Create Staff/Admin User")
        nm = st.text_input("Full Name", key="staff_nm")
        ph = st.text_input("Phone (unique)", key="staff_ph")
        em = st.text_input("Email (optional)", key="staff_em")
        rl = st.selectbox("Role", ["Staff", "Admin"], key="staff_rl")
        pw = st.text_input("Password", type="password", key="staff_pw")
        if st.button("Create User"):
            if not (nm.strip() and ph.strip() and pw.strip()):
                st.error("Name, phone and password required.")
            else:
                try:
                    q(conn, """
                    INSERT INTO users(full_name, phone, email, password_hash, role, created_at)
                    VALUES(?,?,?,?,?,?)
                    """, (nm.strip(), ph.strip(), em.strip() or None, hash_password(pw.strip()), rl, now_str()))
                    conn.commit()
                    st.success("Staff/Admin user created.")
                    st.rerun()
                except sqlite3.IntegrityError as e:
                    st.error(f"Could not create user: {e}")

    conn.close()


# =========================
# AUTH PAGES
# =========================
def page_login():
    st.subheader("Login")
    phone = st.text_input("Phone")
    password = st.text_input("Password", type="password")

    if st.button("Login"):
        row = login(phone.strip(), password.strip())
        if not row:
            st.error("Invalid phone or password.")
        else:
            st.session_state["user"] = {"user_id": row[0], "full_name": row[1], "role": row[2]}
            st.success(f"Welcome, {row[1]} ({row[2]})")
            st.rerun()

    st.info("Default Admin Login (auto-created):\n- Phone: 0300-0000000\n- Password: admin123")

def page_register():
    st.subheader("Register (Customer)")
    full_name = st.text_input("Full Name")
    phone = st.text_input("Phone (unique)")
    email = st.text_input("Email (optional)")
    password = st.text_input("Password", type="password")
    confirm = st.text_input("Confirm Password", type="password")

    if st.button("Create Account"):
        if password != confirm:
            st.error("Passwords do not match.")
            return
        ok, msg = register_customer(full_name.strip(), phone.strip(), email.strip(), password.strip())
        if ok:
            st.success(msg)
        else:
            st.error(msg)

# =========================
# APP SHELL
# =========================
def logout_button():
    if st.sidebar.button("Logout"):
        st.session_state.pop("user", None)
        st.rerun()

def main():
    st.set_page_config(page_title=APP_TITLE, layout="wide")
    init_db()

    st.title(APP_TITLE)
    st.caption("Based on your DB proposal requirements: booking + packages + live status stages + history + payment + staff assignment. " 
               ":contentReference[oaicite:1]{index=1}")

    with st.sidebar:
        st.header("Navigation")

        if "user" in st.session_state:
            st.write(f"Logged in as: **{st.session_state['user']['full_name']}**")
            st.write(f"Role: **{st.session_state['user']['role']}**")
            logout_button()

            if st.session_state["user"]["role"] == "Customer":
                choice = st.radio("Go to", ["Customer Dashboard"])
            else:
                choice = st.radio("Go to", ["Admin/Staff Dashboard"])
        else:
            choice = st.radio("Go to", ["Login", "Register"])

    if "user" not in st.session_state:
        if choice == "Login":
            page_login()
        else:
            page_register()
    else:
        if st.session_state["user"]["role"] == "Customer":
            page_customer_dashboard()
        else:
            page_staff_dashboard()


if __name__ == "__main__":
    main()
