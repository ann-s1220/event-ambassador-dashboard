"""Warm, human visual theme inspired by KCL Womxn in STEM's brand: a soft
violet-to-coral accent palette, serif display headings, rounded card-like
surfaces, and a light/dark mode toggle. `get_css(dark_mode)` renders the
full theme for the requested mode; it's re-injected on every rerun, so
flipping the toggle restyles the page immediately with no reload."""

# Accent colors stay identical across both modes for brand consistency.
CORAL = "#D98F6E"
PINK = "#E8B4B8"

LIGHT = {
    # This is the #834D88 palette from a prior iteration, reassigned to
    # the "light mode" slot (toggle off) at the user's request -- every
    # value here was tuned against #834D88 specifically (see the contrast
    # notes that used to live on DARK, before the swap): bg_secondary
    # went darker than bg for separation against a background this
    # bright/saturated, and text_muted/border/accent_strong were all
    # lightened from what they'd need against a much darker backdrop.
    "bg": "#834D88",
    "bg_secondary": "#5B3560",
    "text": "#F5F1EB",
    "text_muted": "#E3D9EF",
    "border": "#CDB0D1",
    "accent_strong": "#D4BEE5",
}

DARK = {
    # Restored original dark palette (toggle on).
    "bg": "#2A2140",
    "bg_secondary": "#3D3159",
    "text": "#F5F1EB",
    "text_muted": "#B8AECC",
    "border": "#55486E",
    "accent_strong": "#C9AEDB",
}

# Neither palette is a plain white/near-black background anymore, so both
# need their own explicit alert-color overrides (Streamlit's native alert
# colors assume a white page).
LIGHT_STATUS = {
    "success_bg": "rgba(74,222,128,0.22)", "success_text": "#9CF4BC",
    "warning_bg": "rgba(252,211,77,0.24)", "warning_text": "#FDDB7A",
    "error_bg": "rgba(252,165,165,0.24)", "error_text": "#FECBCB",
    "info_bg": "rgba(147,197,253,0.20)", "info_text": "#A8D2FE",
}
DARK_STATUS = {
    "success_bg": "rgba(74,222,128,0.16)", "success_text": "#86EFAC",
    "warning_bg": "rgba(252,211,77,0.18)", "warning_text": "#FCD34D",
    "error_bg": "rgba(252,165,165,0.18)", "error_text": "#FCA5A5",
    "info_bg": "rgba(147,197,253,0.16)", "info_text": "#93C5FD",
}


def get_css(dark_mode: bool) -> str:
    p = dict(DARK if dark_mode else LIGHT)
    p["coral"] = CORAL
    p["pink"] = PINK

    s = DARK_STATUS if dark_mode else LIGHT_STATUS
    status_css = f"""
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {{
            background-color: {s['success_bg']} !important;
        }}
        [data-testid="stAlertContentSuccess"], [data-testid="stAlertContentSuccess"] * {{
            color: {s['success_text']} !important;
        }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
            background-color: {s['warning_bg']} !important;
        }}
        [data-testid="stAlertContentWarning"], [data-testid="stAlertContentWarning"] * {{
            color: {s['warning_text']} !important;
        }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {{
            background-color: {s['error_bg']} !important;
        }}
        [data-testid="stAlertContentError"], [data-testid="stAlertContentError"] * {{
            color: {s['error_text']} !important;
        }}
        [data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
            background-color: {s['info_bg']} !important;
        }}
        [data-testid="stAlertContentInfo"], [data-testid="stAlertContentInfo"] * {{
            color: {s['info_text']} !important;
        }}
        """

    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=Inter:wght@400;500;600&display=swap');

:root {{
    --bg: {p['bg']};
    --bg-secondary: {p['bg_secondary']};
    --text: {p['text']};
    --text-muted: {p['text_muted']};
    --border: {p['border']};
    --accent-strong: {p['accent_strong']};
    --coral: {p['coral']};
    --pink: {p['pink']};
    --gradient: linear-gradient(135deg, var(--accent-strong), var(--coral));
}}

html, body {{
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}
[data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stBottomBlockContainer"] {{
    background-color: var(--bg) !important;
}}
[data-testid="stSidebar"] {{
    background-color: var(--bg-secondary) !important;
    border-right: 1px solid var(--border);
}}
[data-testid="stSidebar"] * {{
    color: var(--text) !important;
}}
/* The collapse/expand arrow lives outside [data-testid="stSidebar"] (it
   has to stay visible even when the sidebar is fully collapsed), so the
   blanket rule above never reaches it -- it was stuck at Streamlit's
   baked-in light-theme icon color regardless of mode. Targeted directly
   here for both the collapse (sidebar open) and expand (sidebar closed)
   states. */
[data-testid="stSidebarCollapseButton"] [data-testid="stIconMaterial"],
[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{
    color: var(--text) !important;
}}

/* Widget labels and plain text: Streamlit bakes an explicit color onto
   these elements (not just inherited), so ancestor overrides alone don't
   reach them -- they need direct rules. */
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] *,
[data-testid="stMarkdownContainer"], [data-testid="stMarkdownContainer"] *,
[data-testid="stFileUploaderDropzoneInstructions"], [data-testid="stFileUploaderDropzoneInstructions"] * {{
    color: var(--text) !important;
}}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {{
    color: var(--text-muted) !important;
}}
[data-testid="stElementToolbar"] svg {{
    fill: var(--text-muted) !important;
}}

/* Headings */
h1, h2, h3, h4, h5,
[data-testid="stMarkdownContainer"] h1,
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {{
    font-family: 'Playfair Display', Georgia, serif !important;
    color: var(--text) !important;
    font-weight: 700 !important;
}}
[data-testid="stAppViewContainer"] h1 {{
    border-bottom: 3px solid transparent;
    border-image: var(--gradient) 1;
    padding-bottom: 0.5rem;
    display: inline-block;
}}

/* Tabs */
[data-baseweb="tab-list"] {{ gap: 0.5rem; }}
[data-baseweb="tab-border"] {{ background-color: var(--border) !important; }}
[data-baseweb="tab"] {{
    font-family: 'Inter', sans-serif;
    font-weight: 600;
    color: var(--text-muted) !important;
}}
[data-baseweb="tab"][aria-selected="true"] {{ color: var(--accent-strong) !important; }}
[data-baseweb="tab-highlight"] {{
    background: var(--gradient) !important;
    height: 3px;
    border-radius: 3px;
}}

/* Buttons */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
    background-color: var(--bg-secondary) !important;
    color: var(--text) !important;
    border-radius: 12px !important;
    border: 1px solid var(--accent-strong) !important;
    transition: filter 0.15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {{
    background-color: var(--pink) !important;
    border-color: var(--coral) !important;
    color: #332A3D !important;
}}
.stButton > button:disabled, .stFormSubmitButton > button:disabled {{
    opacity: 0.5 !important;
}}
button[kind="primary"], button[kind="primaryFormSubmit"] {{
    background: var(--gradient) !important;
    border: none !important;
    color: #fff !important;
}}
button[kind="primary"]:hover, button[kind="primaryFormSubmit"]:hover {{
    filter: brightness(1.08);
    color: #fff !important;
}}
/* Sidebar nav "active" state: applied by injected JS (see app.py), not a
   Streamlit button `type`, since which section is showing is tracked by
   native st.tabs() -- this just needs to look identical to a primary
   button. */
[data-testid="stSidebar"] .stButton > button.nav-active {{
    background: var(--gradient) !important;
    border: none !important;
    color: #fff !important;
}}

/* Inputs */
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input,
[data-baseweb="select"] > div, [data-testid="stFileUploaderDropzone"],
[data-testid="stSelectbox"] .react-aria-ComboBox,
[data-testid="stMultiSelect"] .react-aria-ComboBox {{
    background-color: var(--bg-secondary) !important;
    color: var(--text) !important;
    border-radius: 12px !important;
    border-color: var(--border) !important;
}}
[data-testid="stSelectbox"] .react-aria-ComboBox div,
[data-testid="stMultiSelect"] .react-aria-ComboBox div {{
    background-color: var(--bg-secondary) !important;
}}
[data-testid="stSelectbox"] .react-aria-ComboBox *,
[data-testid="stMultiSelect"] .react-aria-ComboBox * {{
    color: var(--text) !important;
}}
[data-testid="stSelectbox"] .react-aria-ComboBox svg,
[data-testid="stMultiSelect"] .react-aria-ComboBox svg {{
    fill: var(--text-muted) !important;
}}
[data-testid="stSelectboxVirtualDropdown"] {{
    background-color: var(--bg-secondary) !important;
}}
[data-testid="stSelectboxVirtualDropdown"] [role="option"] {{
    color: var(--text) !important;
}}
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] {{
    background-color: var(--border) !important;
}}

/* Tables / dataframes -- one shared block for every st.dataframe in the
   app (members list, attendance, ambassador roster, full leaderboard,
   referred attendees, feedback, GDPR search results, deletion log, ...),
   so any future table matches automatically without extra work.
   Important caveat: st.dataframe paints its grid to an HTML5 canvas
   (glide-data-grid) -- header/cell backgrounds, text, and gridlines are
   pixel-rendered from Streamlit's static server-side theme
   (.streamlit/config.toml) once per session and are not reachable by CSS
   or by this toggle (verified: neither injected CSS variables nor
   Streamlit's own embed_options=dark_theme mechanism change canvas pixel
   color -- only a server restart with different config.toml values
   would). Cell text stays dark-on-white regardless of mode, which is
   always high-contrast/readable on its own terms, just not chromatically
   matched to the page. Everything below is what CSS *can* reach: the
   container chrome, border, radius, and hover accent. */
[data-testid="stDataFrame"] {{
    border-radius: 12px !important;
    border: 1px solid var(--border) !important;
    background-color: var(--bg-secondary);
    overflow: hidden;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}
[data-testid="stDataFrame"]:hover {{
    border-color: var(--coral) !important;
    box-shadow: 0 0 0 3px rgba(217, 143, 110, 0.15);
}}

/* Other card-like surfaces */
[data-testid="stExpander"], [data-testid="stAlert"],
[data-testid="stFileUploaderDropzone"] {{
    border-radius: 12px !important;
    border: 1px solid var(--border) !important;
    overflow: hidden;
}}
[data-testid="stExpander"] {{ background-color: var(--bg-secondary) !important; }}
[data-testid="stExpander"] summary {{
    background-color: transparent !important;
    color: var(--text) !important;
    font-weight: 600;
}}
[data-testid="stExpander"] summary:hover {{ background-color: rgba(232,180,184,0.18) !important; }}
[data-testid="stExpanderDetails"] {{ background-color: var(--bg-secondary) !important; }}

[data-testid="stMetric"] {{
    background: linear-gradient(135deg, rgba(122,92,142,0.10), rgba(217,143,110,0.08));
    border: 1px solid var(--border);
    border-radius: 12px !important;
    padding: 0.9rem 1.1rem;
}}
[data-testid="stMetricValue"], [data-testid="stMetricLabel"] {{ color: var(--text) !important; }}

/* Dialog (st.dialog) */
[data-testid="stDialog"] {{ background-color: rgba(0,0,0,0.5) !important; }}
[data-testid="stDialog"] > div {{
    background-color: var(--bg-secondary) !important;
    color: var(--text) !important;
    border-radius: 16px !important;
    border: 1px solid var(--border);
}}

/* Charts */
[data-testid="stVegaLiteChart"] svg {{ background-color: transparent !important; }}
[data-testid="stVegaLiteChart"] svg text {{ fill: var(--text-muted) !important; }}
[data-testid="stVegaLiteChart"] svg line {{ stroke: var(--border) !important; }}
[data-testid="stVegaLiteChart"] svg .domain {{ stroke: var(--border) !important; }}

/* Dividers */
hr {{
    border: none;
    height: 2px;
    background: var(--gradient);
    opacity: 0.5;
    border-radius: 2px;
}}
{status_css}
</style>
"""
