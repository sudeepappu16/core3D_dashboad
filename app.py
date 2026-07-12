import streamlit as st
import trimesh
import plotly.graph_objects as go
import tempfile
import os
import pandas as pd
from weasyprint import HTML
from datetime import datetime, timedelta
from sqlalchemy import text

# --- CONFIGURATION & CONSTANTS ---
st.set_page_config(page_title="Core3D CRM & Quotes", page_icon="🧊", layout="wide")

RAL_CODES = [
    "RAL 9003 (Signal White)", "RAL 9005 (Jet Black)", "RAL 7016 (Anthracite Grey)",
    "RAL 3020 (Traffic Red)", "RAL 5002 (Ultramarine Blue)", "RAL 6018 (Yellow Green)", "Custom / Other"
]

TECH_CATALOG = {
    "SLA": ["ABS-like", "PC-like"],
    "SLS": ["PA12", "PA12 + GF 30%"],
    "MJF": ["PA12"],
    "FDM": ["PLA", "PETG", "TPU", "Translucent"],
    "DLP": ["Standard Resin", "Tough Resin"]
}

# --- DATABASE CONNECTION (PostgreSQL via Streamlit) ---
conn = st.connection("postgresql", type="sql")

def init_db():
    with conn.session as s:
        s.execute(text('''
            CREATE TABLE IF NOT EXISTS customers (
                id SERIAL PRIMARY KEY,
                customer_type TEXT, name TEXT, email TEXT, phone TEXT,
                gst_number TEXT, billing_address TEXT, shipping_address TEXT,
                account_manager TEXT, ac_email TEXT, ac_phone TEXT
            )
        '''))
        s.commit()

def add_customer(c_type, name, email, phone, gst, billing, shipping, am_name, am_email, am_phone):
    with conn.session as s:
        s.execute(text('''
            INSERT INTO customers (customer_type, name, email, phone, gst_number, billing_address, shipping_address, account_manager, ac_email, ac_phone)
            VALUES (:c_type, :name, :email, :phone, :gst, :billing, :shipping, :am_name, :am_email, :am_phone)
        '''), {
            "c_type": c_type, "name": name, "email": email, "phone": phone, 
            "gst": gst, "billing": billing, "shipping": shipping, 
            "am_name": am_name, "am_email": am_email, "am_phone": am_phone
        })
        s.commit()

def get_all_customers():
    # Uses Streamlit's built-in query caching
    df = conn.query("SELECT * FROM customers", ttl="10m")
    return df

# --- 3D PROCESSING FUNCTIONS ---
def analyze_stl(file_bytes, filename):
    suffix = os.path.splitext(filename)[1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name

    try:
        mesh = trimesh.load(tmp_path, file_type='stl')
        volume_mm3 = mesh.volume if mesh.is_watertight else mesh.convex_hull.volume
        volume_cc = volume_mm3 / 1000.0
        extents = mesh.extents
        
        return {
            "success": True,
            "volume_cc": round(volume_cc, 3),
            "dimensions": (round(extents[0], 2), round(extents[1], 2), round(extents[2], 2)),
            "is_watertight": mesh.is_watertight,
            "mesh": mesh
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

def generate_3d_snapshot(mesh):
    vertices, faces = mesh.vertices, mesh.faces
    fig = go.Figure(data=[go.Mesh3d(
        x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
        i=faces[:, 0], j=faces[:, 1], k=faces[:, 2],
        color='lightgray', opacity=0.8, flatshading=True,
        lighting=dict(ambient=0.5, diffuse=0.8, roughness=0.5, specular=0.2)
    )])
    fig.update_layout(
        scene=dict(xaxis=dict(visible=False), yaxis=dict(visible=False), zaxis=dict(visible=False)),
        margin=dict(l=0, r=0, b=0, t=0), height=300
    )
    return fig

# --- PDF GENERATION ---
def generate_pdf_quote(customer_dict, quote_summary, total_price):
    date_today = datetime.now().strftime("%B %d, %Y")
    valid_until = (datetime.now() + timedelta(days=15)).strftime("%B %d, %Y")
    cgst, sgst = total_price * 0.09, total_price * 0.09
    grand_total = total_price + cgst + sgst

    items_html = ""
    for item in quote_summary:
        items_html += f"""
        <tr>
            <td><strong>{item['file_name']}</strong></td>
            <td>{item['tech']}<br/><span style="color:#7f8c8d; font-size:9pt;">{item['material']}</span></td>
            <td>{item['finish']}</td>
            <td>{item['volume_cc']} cc<br/><span style="color:#7f8c8d; font-size:9pt;">{item['dimensions']}</span></td>
            <td>{item['fasteners']}</td>
            <td style="text-align: right;">{item['total_cost']:.2f}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 20mm 15mm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; margin: 0; color: #2c3e50; font-size: 10pt; }}
        .header-table {{ width: 100%; border-bottom: 3px solid #2980b9; padding-bottom: 15px; margin-bottom: 20px; }}
        .company-name {{ font-size: 24pt; font-weight: bold; color: #2980b9; }}
        .section-title {{ font-weight: bold; margin-bottom: 10px; color: #2980b9; border-bottom: 1px solid #bdc3c7; padding-bottom: 4px; text-transform: uppercase; }}
        .info-table {{ width: 100%; margin-bottom: 20px; }}
        .quote-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
        .quote-table th {{ background-color: #34495e; color: #ffffff; padding: 8px; text-align: left; }}
        .quote-table td {{ padding: 8px; border-bottom: 1px solid #bdc3c7; }}
        .totals-table {{ width: 300px; float: right; border-collapse: collapse; font-size: 11pt; }}
        .totals-table td {{ padding: 6px 10px; }}
        .total-row {{ font-weight: bold; font-size: 13pt; border-top: 2px solid #2c3e50; background-color: #ecf0f1; }}
        .footer {{ clear: both; margin-top: 40px; font-size: 8pt; color: #7f8c8d; border-top: 1px solid #bdc3c7; padding-top: 10px; }}
    </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td style="width: 55%;">
                    <div class="company-name">Core3D Printing</div>
                    <div>123 Tech Park, Bengaluru, Karnataka 560001</div>
                    <div>Email: sales@core3d.in | Phone: +91-9876543210</div>
                    <div>GSTIN: 29XXXXXXXXXXXXX</div>
                    <div style="margin-top: 12px; padding-top: 10px; border-top: 1px dashed #bdc3c7;">
                        <strong>Your Account Manager:</strong> {customer_dict.get('account_manager', 'Not Assigned')}<br/>
                        Email: {customer_dict.get('ac_email', 'N/A')} | Phone: {customer_dict.get('ac_phone', 'N/A')}
                    </div>
                </td>
                <td style="width: 45%; text-align: right;">
                    <h2 style="margin:0 0 5px 0; color: #34495e;">QUOTATION</h2>
                    <div><strong>Date:</strong> {date_today}</div>
                    <div><strong>Valid Until:</strong> {valid_until}</div>
                </td>
            </tr>
        </table>
        <div class="section-title">Customer Details</div>
        <table class="info-table">
            <tr><td style="width: 15%; font-weight: bold;">Name/Co:</td><td style="width: 35%;">{customer_dict.get('name', '')}</td>
                <td style="width: 15%; font-weight: bold;">GSTIN:</td><td style="width: 35%;">{customer_dict.get('gst_number', '')}</td></tr>
            <tr><td style="font-weight: bold;">Email:</td><td>{customer_dict.get('email', '')}</td>
                <td style="font-weight: bold;">Phone:</td><td>{customer_dict.get('phone', '')}</td></tr>
            <tr><td style="font-weight: bold;">Billing:</td><td colspan="3">{customer_dict.get('billing_address', '')}</td></tr>
        </table>
        <div class="section-title">Order Specifications</div>
        <table class="quote-table">
            <thead><tr><th>Part Name</th><th>Tech/Material</th><th>Finish</th><th>Vol/Dims</th><th>Inserts</th><th style="text-align: right;">Total (₹)</th></tr></thead>
            <tbody>{items_html}</tbody>
        </table>
        <table class="totals-table">
            <tr><td>Subtotal:</td><td style="text-align: right;">₹ {total_price:.2f}</td></tr>
            <tr><td>CGST (9%):</td><td style="text-align: right;">₹ {cgst:.2f}</td></tr>
            <tr><td>SGST (9%):</td><td style="text-align: right;">₹ {sgst:.2f}</td></tr>
            <tr class="total-row"><td>Grand Total:</td><td style="text-align: right;">₹ {grand_total:.2f}</td></tr>
        </table>
        <div class="footer">
            <strong>Terms & Conditions:</strong><br/>
            1. Validity: 15 days from issue.<br/>
            2. Payment Terms: 100% advance along with Purchase Order.<br/>
            3. Lead Time: 3-5 working days upon payment confirmation.<br/>
            4. Tolerances: General 3D printing tolerances apply.
        </div>
    </body>
    </html>
    """
    return HTML(string=html_content).write_pdf()

# --- APP INITIALIZATION ---
try:
    init_db()
except Exception as e:
    st.error(f"Database Initialization Error: {e}")

st.title("🧊 Core3D CRM & Quotation Generator")
tab_quote, tab_crm = st.tabs(["📄 Generate Quote", "👥 Customer Management"])

# --- TAB 1: QUOTE GENERATOR ---
with tab_quote:
    st.subheader("1. Select Customer")
    try:
        customers_df = get_all_customers()
    except Exception:
        customers_df = pd.DataFrame()
        
    selected_customer_name = "-- Select Customer --"
    
    if not customers_df.empty:
        selected_customer_name = st.selectbox("Assign Quote To:", ["-- Select Customer --"] + customers_df['name'].tolist())
        if selected_customer_name != "-- Select Customer --":
            customer_data = customers_df[customers_df['name'] == selected_customer_name].iloc[0]
            st.info(f"**Email:** {customer_data['email']} | **Phone:** {customer_data['phone']} | **AM:** {customer_data.get('account_manager', 'None')}")
            
            uploaded_files = st.file_uploader("Upload STL Files", type=["stl"], accept_multiple_files=True)
            if uploaded_files:
                quote_summary = []
                for idx, file in enumerate(uploaded_files):
                    with st.expander(f"📦 Model #{idx+1}: {file.name}", expanded=True):
                        analysis = analyze_stl(file.getvalue(), file.name)
                        if not analysis["success"]:
                            st.error(f"Error: {analysis['error']}")
                            continue
                        
                        vol_cc = analysis["volume_cc"]
                        dim_x, dim_y, dim_z = analysis["dimensions"]

                        left_col, right_col = st.columns([2, 1])
                        with left_col:
                            c1, c2 = st.columns(2)
                            c1.metric("Calculated Volume", f"{vol_cc} cc")
                            c2.metric("Bounding Box", f"{dim_x} × {dim_y} × {dim_z} mm")
                            if not analysis["is_watertight"]: st.warning("⚠️ Non-watertight mesh.")
                        with right_col:
                            st.plotly_chart(generate_3d_snapshot(analysis["mesh"]), use_container_width=True)

                        cfg1, cfg2, cfg3 = st.columns(3)
                        with cfg1:
                            tech = st.selectbox("Technology", list(TECH_CATALOG.keys()), key=f"tech_{idx}")
                            mat = st.selectbox("Material", TECH_CATALOG[tech], key=f"mat_{idx}")
                        with cfg2:
                            fin_ops = ["Raw"] if (tech == "FDM" and mat in ["TPU", "Translucent"]) else ["Transparent", "Translucent", "Tinted"] if mat == "PC-like" else ["Raw", "Painted - Matte", "Painted - Glossy", "Custom"]
                            finish = st.selectbox("Finish", fin_ops, key=f"fin_{idx}")
                        with cfg3:
                            price_cc = st.number_input("Price/CC (₹)", min_value=0.0, value=45.0, key=f"rate_{idx}")
                            inserts = st.number_input("Threaded Inserts", min_value=0, value=0, key=f"ins_{idx}")
                            if inserts > 0: st.file_uploader("Insert Marking PDF", type=["pdf"], key=f"pdf_{idx}")
                        
                        total_item = (vol_cc * price_cc) + (inserts * 35.0)
                        st.write(f"**Item Estimate:** ₹{total_item:.2f}")
                        
                        quote_summary.append({
                            "file_name": file.name, "volume_cc": vol_cc,
                            "dimensions": f"{dim_x}x{dim_y}x{dim_z} mm", "tech": tech,
                            "material": mat, "finish": finish, "fasteners": inserts, "total_cost": total_item
                        })

                if quote_summary:
                    st.divider()
                    total_quote_price = sum(i["total_cost"] for i in quote_summary)
                    st.subheader("📋 Quotation Summary")
                    st.dataframe(quote_summary, use_container_width=True)
                    st.metric("Subtotal (Excl. Tax)", f"₹{total_quote_price:,.2f}")
                    
                    pdf_data = generate_pdf_quote(customer_data.to_dict(), quote_summary, total_quote_price)
                    st.download_button("📄 Download Official PDF Quotation", data=pdf_data, file_name=f"Quote_{customer_data['name']}.pdf", mime="application/pdf", type="primary")

# --- TAB 2: CRM MANAGEMENT ---
with tab_crm:
    st.subheader("Add New Customer")
    with st.form("new_customer_form", clear_on_submit=True):
        st.markdown("#### Client Details")
        c1, c2 = st.columns(2)
        with c1:
            c_type = st.radio("Type", ["B2B (Business)", "B2C (Consumer)"])
            c_name = st.text_input("Name / Company*")
            c_email = st.text_input("Email*")
            c_phone = st.text_input("Phone*")
        with c2:
            c_gst = st.text_input("GSTIN")
            c_billing = st.text_area("Billing Address*")
            c_shipping = st.text_area("Shipping Address")
            
        st.markdown("#### Account Manager")
        am1, am2, am3 = st.columns(3)
        with am1: am_name = st.text_input("AM Name")
        with am2: am_email = st.text_input("AM Email")
        with am3: am_phone = st.text_input("AM Phone")

        if st.form_submit_button("Save Customer"):
            if c_name and c_email and c_billing:
                add_customer(c_type, c_name, c_email, c_phone, c_gst if "B2B" in c_type else "N/A", c_billing, c_shipping or c_billing, am_name, am_email, am_phone)
                st.success("Customer added!")
                st.cache_data.clear() # Clears cache so new customer appears instantly
                st.rerun()
            else:
                st.error("Missing required fields.")
                
    st.divider()
    st.subheader("Customer Database")
    try:
        df = get_all_customers()
        if not df.empty: st.dataframe(df, hide_index=True)
    except Exception:
        st.info("Database empty or not connected.")