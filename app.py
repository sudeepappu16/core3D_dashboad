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

# --- CONFIGURATION & CONSTANTS ---
st.set_page_config(page_title="Makenica CRM & Quotes", page_icon="⚙️", layout="wide")

RAL_CODES = [
    "RAL 9003 (Signal White)", "RAL 9005 (Jet Black)", "RAL 7016 (Anthracite Grey)",
    "RAL 3020 (Traffic Red)", "RAL 5002 (Ultramarine Blue)", "RAL 6018 (Yellow Green)", 
    "RAL 9011 (Graphite black)", "Custom / Other"
]

TECH_CATALOG = {
    "SLA": ["ABS-like", "PC-like"],
    "SLS": ["PA12", "PA12 + GF 30%"],
    "MJF": ["PA12"],
    "FDM": ["PLA", "PETG", "TPU", "Translucent"],
    "DLP": ["Standard Resin", "Tough Resin"]
}

# --- DATABASE CONNECTION ---
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
def generate_pdf_quote(customer_dict, quote_summary, total_price, shipping_charge=0.0):
    date_time_now = datetime.now().strftime("%B %d, %Y, %I:%M %p")
    quote_number = f"Q-{str(uuid.uuid4())[:6].upper()}"
    
    gst_amount = total_price * 0.18
    grand_total = total_price + gst_amount + shipping_charge

    # Format the current directory for the logo
    current_dir = f"file://{os.path.abspath(os.path.dirname(__file__))}"
    logo_path = f"{current_dir}/Makenica Company Logo Black.png"

    items_html = ""
    for idx, item in enumerate(quote_summary):
        items_html += f"""
        <tr>
            <td style="padding-top: 15px;">
                <strong>{item['tech']} 3D Printing</strong><br/>
                Part: {item['file_name']}<br/>
                Dimensions: {item['dimensions']}<br/>
                Material: {item['material']}<br/>
                Finish: {item['finish']}<br/>
                {f"Paint Color: {item['paint_details'].get('ral', '')}<br/>" if 'ral' in item['paint_details'] else ""}
                {f"Paint Finish: {item['paint_details'].get('gloss_level', 'Matt')}<br/>" if 'Painted' in item['finish'] else ""}
                {f"<br/><em>Includes {item['fasteners']} threaded inserts</em>" if item['fasteners'] > 0 else ""}
            </td>
            <td style="padding-top: 15px;">HSN:39260000</td>
            <td style="padding-top: 15px; text-align: center;">{item['qty']}</td>
            <td style="padding-top: 15px; text-align: right;">{item['unit_price']:,.2f}</td>
            <td style="padding-top: 15px; text-align: right;">{item['total_cost']:,.2f}</td>
        </tr>
        """

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
    <style>
        @page {{ size: A4; margin: 15mm 15mm; }}
        body {{ font-family: Helvetica, Arial, sans-serif; margin: 0; color: #111; font-size: 9pt; }}
        .header-table {{ width: 100%; border-bottom: 2px solid #333; padding-bottom: 15px; margin-bottom: 15px; }}
        .header-left {{ width: 60%; vertical-align: top; line-height: 1.4; }}
        .header-right {{ width: 40%; text-align: right; vertical-align: top; line-height: 1.4; }}
        .logo {{ width: 180px; margin-bottom: 10px; }}
        .info-table {{ width: 100%; margin-bottom: 25px; line-height: 1.4; }}
        .info-table td {{ vertical-align: top; width: 50%; }}
        .quote-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; font-size: 9pt; }}
        .quote-table th {{ border-bottom: 1px solid #333; padding: 8px 4px; text-align: left; font-weight: bold; }}
        .quote-table td {{ padding: 4px; border-bottom: 1px solid #eee; vertical-align: top; line-height: 1.5; }}
        .totals-table {{ width: 300px; float: right; border-collapse: collapse; font-size: 10pt; }}
        .totals-table td {{ padding: 6px 10px; }}
        .total-row {{ font-weight: bold; font-size: 11pt; border-top: 1px solid #333; }}
        .clearfix {{ clear: both; }}
        .footer-section {{ margin-top: 30px; font-size: 8.5pt; line-height: 1.5; }}
        .footer-bottom {{ text-align: center; border-top: 1px solid #ccc; padding-top: 10px; margin-top: 20px; font-weight: bold; }}
    </style>
    </head>
    <body>
        <table class="header-table">
            <tr>
                <td class="header-left">
                    <img src="{logo_path}" class="logo" alt="Makenica Logo"/><br/>
                    <strong>MAKENICA PRIVATE LIMITED</strong><br/>
                    #46, 7th Main Road, J.C. Industrial Estate,<br/>
                    Bengaluru, Karnataka 560062<br/>
                    <strong>GSTIN:</strong> 29AAQCM7969K1Z9<br/>
                    <strong>Phone:</strong> +91 96067 70777<br/>
                    <strong>Email:</strong> support@makenica.com
                </td>
                <td class="header-right">
                    <strong>Generated at:</strong><br/>
                    {date_time_now}<br/><br/>
                    <strong style="font-size: 14pt;">Quote #{quote_number}</strong><br/>
                </td>
            </tr>
        </table>
        
        <table class="info-table">
            <tr>
                <td>
                    <strong>Bill To:</strong><br/>
                    {customer_dict.get('name', '')}<br/>
                    {customer_dict.get('billing_address', '').replace(chr(10), '<br/>')}<br/>
                    <strong>Phone:</strong> {customer_dict.get('phone', '')}<br/>
                    <strong>GSTIN:</strong> {customer_dict.get('gst_number', 'N/A')}<br/><br/>
                    <strong>Account Manager:</strong> {customer_dict.get('account_manager', 'Not Assigned')}<br/>
                    Email: {customer_dict.get('ac_email', 'N/A')} | Ph: {customer_dict.get('ac_phone', 'N/A')}
                </td>
                <td>
                    <strong>Ship To:</strong><br/>
                    {customer_dict.get('shipping_address', '').replace(chr(10), '<br/>')}<br/><br/>
                    <strong>Method:</strong> Pickup / Standard Shipping
                </td>
            </tr>
        </table>

        <table class="quote-table">
            <thead>
                <tr>
                    <th style="width: 45%;">Item & Description</th>
                    <th>HSN/SAC</th>
                    <th style="text-align: center;">Qty</th>
                    <th style="text-align: right;">Rate</th>
                    <th style="text-align: right;">Amount</th>
                </tr>
            </thead>
            <tbody>
                {items_html}
            </tbody>
        </table>

        <table class="totals-table">
            <tr><td>Sub Total</td><td style="text-align: right;">₹{total_price:,.2f}</td></tr>
            <tr><td>GST (18.0%)</td><td style="text-align: right;">₹{gst_amount:,.2f}</td></tr>
            <tr><td>Shipping Charge</td><td style="text-align: right;">₹{shipping_charge:,.2f}</td></tr>
            <tr class="total-row"><td>Total Amount</td><td style="text-align: right;">₹{grand_total:,.2f}</td></tr>
        </table>
        <div class="clearfix"></div>

        <div class="footer-section">
            <strong>Default manufacturing accuracy until stated otherwise</strong><br/>
            FDM 3D Printing: 300-400 µm or ±0.2 mm / 100 mm<br/>
            SLA 3D Printing: 100-200 µm or ±0.2 mm / 100 mm<br/>
            SLS 3D Printing: 150-250 µm or ±0.2 mm / 100 mm<br/>
            Vacuum Casting: 200-500 µm or ±0.2 mm / 100 mm<br/>
            VMC Machining: 50-100 µm<br/>
            Injection Molding: 50-100 µm<br/><br/>

            <strong>Terms & Conditions</strong><br/>
            Payment Terms: 100% Advance<br/>
            You can make payment to the below details:<br/>
            A/c Name: Makenica Private Limited.<br/>
            A/c No: 50200081911171<br/>
            IFSC: HDFC0000133<br/>
            Bank Name: HDFC BANK LTD<br/>
            Branch Name: BANGALORE - JP NAGAR<br/>
            Once payment is done, please share the payment receipt.<br/>
            *Shipping Charges will be added during checkout or after order confirmation, if currently Not Available.<br/>
            Order once confirmed cannot be Cancelled or Modified.<br/>
            Please contact support team +91 9606770777 for more information.
        </div>

        <div class="footer-bottom">
            support@makenica.com | www.makenica.com
        </div>
    </body>
    </html>
    """
    return HTML(string=html_content, base_url=current_dir).write_pdf()

# --- APP INITIALIZATION ---
try:
    init_db()
except Exception as e:
    st.error(f"Database Initialization Error: {e}")

st.title("⚙️ Makenica CRM & Quotation Generator")
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
                        dims = analysis["dimensions"]

                        left_col, right_col = st.columns([2, 1])
                        with left_col:
                            c1, c2 = st.columns(2)
                            c1.metric("Calculated Volume", f"{vol_cc} cc")
                            c2.metric("Dimensions", dims)
                            if not analysis["is_watertight"]: st.warning("⚠️ Non-watertight mesh.")
                        with right_col:
                            st.plotly_chart(generate_3d_snapshot(analysis["mesh"]), use_container_width=True)

                        cfg1, cfg2, cfg3, cfg4 = st.columns(4)
                        paint_details = {}
                        
                        with cfg1:
                            tech = st.selectbox("Technology", list(TECH_CATALOG.keys()), key=f"tech_{idx}")
                            mat = st.selectbox("Material", TECH_CATALOG[tech], key=f"mat_{idx}")
                            qty = st.number_input("Quantity", min_value=1, value=1, step=1, key=f"qty_{idx}")
                            
                        with cfg2:
                            fin_ops = ["Raw"] if (tech == "FDM" and mat in ["TPU", "Translucent"]) else ["Transparent", "Translucent", "Tinted"] if mat == "PC-like" else ["Raw", "Painted"]
                            finish = st.selectbox("Finish", fin_ops, key=f"fin_{idx}")
                            
                            if finish == "Painted":
                                ral = st.selectbox("RAL Color", RAL_CODES, key=f"ral_{idx}")
                                gloss = st.selectbox("Paint Finish", ["Matt", "Glossy"], key=f"gloss_{idx}")
                                paint_details = {"ral": ral, "gloss_level": gloss}
                                
                        with cfg3:
                            price_cc = st.number_input("Price/CC (₹)", min_value=0.0, value=45.0, key=f"rate_{idx}")
                            inserts = st.number_input("Threaded Inserts", min_value=0, value=0, key=f"ins_{idx}")
                            
                        with cfg4:
                            unit_price = (vol_cc * price_cc) + (inserts * 35.0)
                            total_item_cost = unit_price * qty
                            st.metric("Total Line Amount", f"₹{total_item_cost:,.2f}")
                        
                        quote_summary.append({
                            "file_name": file.name, "volume_cc": vol_cc,
                            "dimensions": dims, "tech": tech,
                            "material": mat, "finish": finish, 
                            "paint_details": paint_details, "fasteners": inserts, 
                            "qty": qty, "unit_price": unit_price, "total_cost": total_item_cost
                        })

                if quote_summary:
                    st.divider()
                    st.subheader("📋 Quotation Summary")
                    total_quote_price = sum(i["total_cost"] for i in quote_summary)
                    
                    # Shipping Input
                    shipping_charge = st.number_input("Shipping Charge (₹)", min_value=0.0, value=0.0, step=50.0)
                    
                    st.dataframe(quote_summary, use_container_width=True)
                    st.metric("Subtotal (Excl. Tax)", f"₹{total_quote_price:,.2f}")
                    
                    pdf_data = generate_pdf_quote(customer_data.to_dict(), quote_summary, total_quote_price, shipping_charge)
                    st.download_button("📄 Download Makenica PDF Quotation", data=pdf_data, file_name=f"Makenica_Quote_{customer_data['name'].replace(' ', '_')}.pdf", mime="application/pdf", type="primary")

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
                st.cache_data.clear() 
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
