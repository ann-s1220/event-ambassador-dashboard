import streamlit as st

import db
from style import get_css
from tabs import ambassadors, attendance, data_management, feedback

st.set_page_config(page_title="Event & Ambassador Dashboard", layout="wide")

if "dark_mode" not in st.session_state:
    st.session_state["dark_mode"] = True

with st.sidebar:
    st.toggle("Dark mode", key="dark_mode")

st.markdown(get_css(st.session_state["dark_mode"]), unsafe_allow_html=True)

db.init_db()
conn = db.get_connection()

st.title("Event & Ambassador Dashboard")

tab1, tab2, tab3, tab4 = st.tabs(
    ["Member attendance", "Ambassador performance", "Member feedback", "Data management (GDPR)"]
)

with tab1:
    attendance.render(conn)

with tab2:
    ambassadors.render(conn)

with tab3:
    feedback.render(conn)

with tab4:
    data_management.render(conn)
