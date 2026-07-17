import streamlit as st
import trimesh
import plotly.graph_objects as go
import tempfile
import os
import pandas as pd
from weasyprint import HTML
from datetime import datetime
from sqlalchemy import text
import uuid
from werkzeug.security import generate_password_hash, check_password_hash

# --- CONFIGURATION & BRANDING ---
# Makenica Brand Colors: Black, White, and Eagle Gold
st.set_page_config(page_title="Makenica Workspace", page_icon="⚙️", layout="wide")

st.markdown("""
    <style>
    .main .block-container { padding-top: 2rem; }
    h1, h2, h3 { color: #111111; }
    .stButton>button { background-color: #f39c12; color: white; border: none; }
    .stButton>button:hover { background-color: #e67e22; color: white; }
    </style>
""", unsafe_allow_html=True)

RAL_CODES = [
    "RAL 9003 (Signal White)", "RAL 9005 (Jet Black)", "RAL 9011 (Graphite black)", "Custom / Other"
]

TECH_CATALOG = {
    "SLA": ["ABS-like", "PC-like"],
    "SLS": ["PA12", "PA12 + GF 30%"],
    "FDM": ["PLA", "PETG", "TPU"],
    "DLP": ["Standard Resin"]
}

# --- DATABASE CONNECTION & INIT ---
conn = st.connection("postgresql", type="sql")

def init_db():
    with conn.session as s:
        # Customers Table
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                customer_type TEXT, name TEXT, email TEXT, phone TEXT,
                gst_number TEXT, billing_address TEXT, shipping_address TEXT,
                account_manager TEXT, ac_email TEXT, ac_phone TEXT
            )
        '''))
        # Users Table (Authentication)
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE,
                password_hash TEXT,
                role TEXT
            )
        '''))
        # Quotes Table (Saved Quotes)
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS quotes (
                id SERIAL PRIMARY KEY,
                quote_number TEXT UNIQUE,
                customer_name TEXT,
                total_amount NUMERIC,
                created_by TEXT,
                created_at TIMESTAMP
            )
        '''))
        
        # Inject default admin if users table is empty
        result = s.execute(text("SELECT COUNT(*) FROM users")).scalar()
        if result == 0:
            default_hash = generate_password_hash("admin123")
            s.execute(text("INSERT INTO users (username, password_hash, role) VALUES ('admin', :hash, 'Admin')"), {"hash": default_hash})
            
        s.commit()

# --- DATABASE HELPER FUNCTIONS ---
def authenticate_user(username, password):
    with conn.session as s:
        result = s.execute(text("SELECT password_hash, role FROM users WHERE username = :u"), {"u": username}).fetchone()
        if result and check_password_hash(result[0], password):
            return {"success": True, "role": result[1]}
    return {"success": False}

def delete_customer(customer_id):
    with conn.session as s:
        s.execute(text("DELETE FROM customers WHERE id = :id"), {"id": customer_id})
        s.commit()

def save_quote_record(quote_number, customer_name, total, created_by):
    with conn.session as s:
        s.execute(text('''
            INSERT INTO quotes (quote_number, customer_name, total_amount, created_by, created_at)
            VALUES (:q_num, :c_name, :total, :usr, :dt)
        '''), {"q_num": quote_number, "c_name": customer_name, "total": total, "usr": created_by, "dt": datetime.now()})
        s.commit()

# --- 3D PROCESSING (FIXED MESH RENDERING) ---
def analyze_cad(file_bytes, filename):
    suffix = os.path.splitext(filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        # Note: STEP support in trimesh requires backend CAD engines installed on the server.
        mesh = trimesh.load(tmp_path, force='mesh') 
        volume_mm3 = mesh.volume if mesh.is_watertight else mesh.convex_hull.volume
        extents = mesh.extents
        
        return {
            "success": True,
            "volume_cc": round(volume_mm3 / 1000.0, 3),
            "dimensions": f"{round(extents[0], 2)}mm x {round(extents[1], 2)}mm x {round(extents[2], 2)}mm",
            "is_watertight": mesh.is_watertight,
            "mesh": mesh
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def generate_3d_snapshot(mesh):
    # Force triangulation for Plotly compatibility
    if not hasattr(mesh, 'faces') or len(mesh.faces) == 0:
        return go.Figure()
        
    vertices, faces = mesh.vertices, mesh.faces
    
    fig = go.Figure(data=[go.Mesh3d(
        x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
        i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
        intensity=vertices[:, 2], # Colors based on Z-height
        colorscale='Viridis',
        opacity=0.9,
        flatshading=False,
        lighting=dict(ambient=0.4, diffuse=0.8, roughness=0.2, specular=0.4, fresnel=0.1)
    )])
    
    fig.update_layout(
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False)),
        margin=dict(l=0, r=0, b=0, t=0), height=350, paper_bgcolor="rgba(0,0,0,0)"
    )
    return fig

# --- PDF GENERATOR (COMPRESSED FOR BREVITY) ---
def generate_pdf_quote(customer_dict, quote_summary, total_price, q_number):
    date_now = datetime.now().strftime("%B %d, %Y, %I:%M %p")
    gst = total_price * 0.18
    grand = total_price + gst
    logo_path = f"file://{os.path.abspath(os.path.dirname(__file__))}/Makenica Company Logo Black.png"

    items_html = "".join([
        f"<tr><td style='padding:10px;'><strong>{i['tech']} 3D Printing</strong><br/>Part: {i['file_name']}<br/>Dims: {i['dimensions']}<br/>Mat: {i['material']}<br/>Finish: {i['finish']}</td><td style='padding:10px;text-align:right;'>₹{i['total_cost']:,.2f}</td></tr>" for i in quote_summary
    ])

    html_content = f"""
    <html><head><style>body{{font-family:Helvetica;font-size:10pt;color:#111;}} th{{text-align:left;}} td{{border-bottom:1px solid #eee;}} .totals{{float:right;width:300px;}}</style></head>
    <body>
        <div style="border-bottom:2px solid #111; padding-bottom:10px;">
            <img src="{logo_path}" width="150"/><br/>
            <strong>MAKENICA PRIVATE LIMITED</strong><br/>GSTIN: 29AAQCM7969K1Z9
            <div style="float:right;text-align:right;margin-top:-50px;"><strong>Quote #{q_number}</strong><br/>{date_now}</div>
        </div>
        <div style="margin-top:20px;"><strong>Bill To:</strong> {customer_dict.get('name', 'N/A')} | <strong>AM:</strong> {customer_dict.get('account_manager', 'N/A')}</div>
        <table style="width:100%;margin-top:20px;border-collapse:collapse;"><tr><th>Item Details</th><th style="text-align:right;">Amount</th></tr>{items_html}</table>
        <table class="totals">
            <tr><td>Subtotal</td><td style="text-align:right;">₹{total_price:,.2f}</td></tr>
            <tr><td>GST (18%)</td><td style="text-align:right;">₹{gst:,.2f}</td></tr>
            <tr><td><strong>Total</strong></td><td style="text-align:right;"><strong>₹{grand:,.2f}</strong></td></tr>
        </table>
    </body></html>
    """
    return HTML(string=html_content, base_url=f"file://{os.path.abspath(os.path.dirname(__file__))}").write_pdf()

# --- INITIALIZE SESSION STATE ---
try:
    init_db()
except Exception as e:
    st.error(f"Database Error: {e}")

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.username = None

# --- AUTHENTICATION PAGE ---
if not st.session_state.logged_in:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.image("Makenica Company Logo Black.png", width=250)
        st.subheader("Workspace Login")
        u_name = st.text_input("Username")
        pwd = st.text_input("Password", type="password")
        if st.button("Secure Login", use_container_width=True):
            auth = authenticate_user(u_name, pwd)
            if auth["success"]:
                st.session_state.logged_in = True
                st.session_state.role = auth["role"]
                st.session_state.username = u_name
                st.rerun()
            else:
                st.error("Invalid credentials.")
    st.stop()

# --- SIDEBAR NAVIGATION ---
with st.sidebar:
    st.image("Makenica Company Logo Black.png", width=180)
    st.markdown(f"👤 **User:** {st.session_state.username} | **Role:** {st.session_state.role}")
    st.divider()
    
    nav_options = ["📄 Create Quote", "👥 Customers", "🗄️ Saved Quotes"]
    if st.session_state.role == "Admin":
        nav_options.append("🛡️ Admin Panel")
        
    selection = st.radio("Navigation", nav_options)
    
    st.divider()
    if st.button("Log Out"):
        st.session_state.logged_in = False
        st.rerun()

# --- PAGE 1: CREATE QUOTE ---
if selection == "📄 Create Quote":
    st.title("📄 Generate Quotation")
    try:
        customers_df = conn.query("SELECT * FROM customers")
    except:
        customers_df = pd.DataFrame()

    if not customers_df.empty:
        c_names = ["-- Select Customer --"] + customers_df['name'].tolist()
        sel_c = st.selectbox("Assign To", c_names)
        
        if sel_c != "-- Select Customer --":
            c_data = customers_df[customers_df['name'] == sel_c].iloc[0]
            
            # Note the updated file types here
            uploaded_files = st.file_uploader("Upload Files (STL, STEP, STP)", type=["stl", "step", "stp"], accept_multiple_files=True)
            
            if uploaded_files:
                quote_summary = []
                for idx, f in enumerate(uploaded_files):
                    with st.expander(f"📦 Model: {f.name}", expanded=True):
                        analysis = analyze_cad(f.getvalue(), f.name)
                        if not analysis["success"]:
                            st.error(f"Failed to process {f.name}. Make sure it is a valid 3D file.")
                            continue
                        
                        l_col, r_col = st.columns([2,1])
                        with l_col:
                            st.metric("Volume", f"{analysis['volume_cc']} cc")
                            st.metric("Dimensions", analysis['dimensions'])
                        with r_col:
                            st.plotly_chart(generate_3d_snapshot(analysis["mesh"]), use_container_width=True)

                        cfg1, cfg2 = st.columns(2)
                        with cfg1:
                            tech = st.selectbox("Tech", list(TECH_CATALOG.keys()), key=f"t_{idx}")
                            mat = st.selectbox("Material", TECH_CATALOG[tech], key=f"m_{idx}")
                            qty = st.number_input("Qty", min_value=1, value=1, key=f"q_{idx}")
                        with cfg2:
                            fin = st.selectbox("Finish", ["Raw", "Painted"], key=f"f_{idx}")
                            price = st.number_input("Rate/cc", value=45.0, key=f"r_{idx}")
                            
                        item_total = analysis['volume_cc'] * price * qty
                        st.markdown(f"**Item Total: ₹{item_total:,.2f}**")
                        
                        quote_summary.append({
                            "file_name": f.name, "volume_cc": analysis['volume_cc'], "dimensions": analysis['dimensions'],
                            "tech": tech, "material": mat, "finish": fin, "qty": qty, "total_cost": item_total
                        })
                
                if quote_summary:
                    st.divider()
                    total_price = sum(i["total_cost"] for i in quote_summary)
                    q_num = f"Q-{str(uuid.uuid4())[:6].upper()}"
                    
                    st.subheader(f"Total: ₹{total_price:,.2f} (Excl. Tax)")
                    
                    pdf_data = generate_pdf_quote(c_data.to_dict(), quote_summary, total_price, q_num)
                    
                    col_dl, col_save = st.columns(2)
                    with col_dl:
                        st.download_button("⬇️ Download PDF", data=pdf_data, file_name=f"{q_num}.pdf", mime="application/pdf")
                    with col_save:
                        if st.button("💾 Save Quote to Database"):
                            save_quote_record(q_num, c_data['name'], total_price, st.session_state.username)
                            st.success(f"Quote {q_num} saved successfully!")
    else:
        st.warning("Please add a customer in the 'Customers' tab first.")

# --- PAGE 2: CUSTOMERS ---
elif selection == "👥 Customers":
    st.title("👥 Customer Database")
    
    with st.expander("➕ Add New Customer"):
        with st.form("add_c_form"):
            name = st.text_input("Name / Company*")
            email = st.text_input("Email*")
            phone = st.text_input("Phone")
            gst = st.text_input("GSTIN")
            address = st.text_area("Address")
            if st.form_submit_button("Save"):
                if name and email:
                    with conn.session as s:
                        s.execute(text("INSERT INTO customers (name, email, phone, gst_number, billing_address) VALUES (:n, :e, :p, :g, :b)"),
                                  {"n":name, "e":email, "p":phone, "g":gst, "b":address})
                        s.commit()
                    st.success("Added!")
                    st.rerun()

    st.subheader("Manage Existing")
    df = conn.query("SELECT id, name, email, phone, gst_number FROM customers")
    if not df.empty:
        st.dataframe(df, hide_index=True, use_container_width=True)
        
        st.markdown("### Delete Customer")
        del_c = st.selectbox("Select Customer to Delete", df['name'].tolist())
        if st.button("Delete Client", type="primary"):
            c_id = df[df['name'] == del_c].iloc[0]['id']
            delete_customer(int(c_id))
            st.success("Client deleted.")
            st.rerun()

# --- PAGE 3: SAVED QUOTES ---
elif selection == "🗄️ Saved Quotes":
    st.title("🗄️ Quote History")
    quotes_df = conn.query("SELECT quote_number, customer_name, total_amount, created_by, created_at FROM quotes ORDER BY created_at DESC")
    if not quotes_df.empty:
        st.dataframe(quotes_df, hide_index=True, use_container_width=True)
    else:
        st.info("No quotes have been saved to the database yet.")

# --- PAGE 4: ADMIN PANEL ---
elif selection == "🛡️ Admin Panel":
    st.title("🛡️ System Administration")
    
    st.subheader("Create New User")
    with st.form("new_user"):
        new_u = st.text_input("Username")
        new_p = st.text_input("Password", type="password")
        role = st.selectbox("Role", ["User", "Admin"])
        if st.form_submit_button("Create Account"):
            if new_u and new_p:
                h_pwd = generate_password_hash(new_p)
                try:
                    with conn.session as s:
                        s.execute(text("INSERT INTO users (username, password_hash, role) VALUES (:u, :p, :r)"),
                                  {"u": new_u, "p": h_pwd, "r": role})
                        s.commit()
                    st.success("User created!")
                except Exception as e:
                    st.error("Username may already exist.")
                    
    st.divider()
    st.subheader("Current Users")
    users_df = conn.query("SELECT id, username, role FROM users")
    st.dataframe(users_df, hide_index=True)
