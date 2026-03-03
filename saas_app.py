import streamlit as st
import pandas as pd
import mammoth
import re
from bs4 import BeautifulSoup
import io
import requests
import base64
import time
import json
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import cloudscraper

# --- Page Configuration & Theming ---
st.set_page_config(page_title="Link Up Pro", page_icon="🔗", layout="wide")

# Custom CSS for a cleaner, branded look
st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    h1 { color: #2C3E50; font-weight: 700 !important; }
    h2, h3 { color: #1a1a1a; font-weight: 600 !important; }
    .streamlit-expanderHeader { background-color: #f0f4f8; border-radius: 8px; font-weight: 600; }
    [data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #e9ecef; }
    .stSuccess { border-left: 5px solid #28a745; }
    </style>
""", unsafe_allow_html=True)

# --- App Header ---
st.markdown("<h1>🔗 Link Up Pro <span style='color: #888; font-size: 0.5em; vertical-align: middle;'>v5.0</span></h1>", unsafe_allow_html=True)
st.markdown("Automate your internal linking strategy, and generate SEO-friendly alt text for your images.")
st.divider()

# --- Authentication Gate ---
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.info("### 🔒 Restricted Access\nPlease enter your passcode to use this tool.")
        entered_password = st.text_input("Passcode", type="password", label_visibility="collapsed", placeholder="Enter passcode...")
        
        if st.button("Login", type="primary", use_container_width=True):
            # We use st.secrets so your password isn't exposed in your public GitHub repo!
            # If no secret is set yet, it defaults to 'demo123' for testing.
            expected_password = st.secrets.get("app_password", "demo123") 
            
            if entered_password == expected_password:
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("❌ Incorrect passcode. Please try again.")
    
    # st.stop() halts the script here, hiding the entire tool from unauthenticated users
    st.stop() 

# --- Sidebar: Tool Selector ---
st.sidebar.markdown("### 🛠️ Select Tool")
app_mode = st.sidebar.radio("App Mode", ["🔗 Link Up Optimizer", "🖼️ AI Alt Text Generator"], label_visibility="collapsed")
st.sidebar.divider()
st.sidebar.info("💡 **Tip:** Use the menu above to switch between the Link Optimizer and the Alt Text Generator.")

# --- Advanced Stealth Scraper ---
@st.cache_resource
def get_scraper():
    # Bypasses Cloudflare 503s and Anti-Bot walls by solving JS challenges automatically
    return cloudscraper.create_scraper(
        browser={
            'browser': 'chrome',
            'platform': 'windows',
            'desktop': True
        }
    )

# --- NEW: Sitemap Auto-Discovery Engine ---
def discover_sitemap(input_url):
    scraper = get_scraper()
    parsed = urlparse(input_url)
    scheme = parsed.scheme if parsed.scheme else "https"
    base_url = f"{scheme}://{parsed.netloc}"
    if not parsed.netloc:
        base_url = f"https://{parsed.path.split('/')[0]}"
    
    # 1. Check robots.txt (The Gold Standard)
    try:
        r = scraper.get(f"{base_url}/robots.txt", timeout=10)
        if r.status_code == 200:
            for line in r.text.split('\n'):
                if line.lower().startswith('sitemap:'):
                    return line.split(':', 1)[1].strip()
    except:
        pass
        
    # 2. Try common default paths
    common_paths = ['/sitemap.xml', '/sitemap_index.xml']
    for path in common_paths:
        test_url = f"{base_url}{path}"
        try:
            r = scraper.get(test_url, timeout=10)
            if r.status_code == 200 and 'xml' in r.headers.get('Content-Type', '').lower():
                return test_url
        except:
            pass
    
    return input_url

# Helper function to parse sitemaps recursively
def fetch_sitemap_urls(sitemap_url, max_urls=5000):
    scraper = get_scraper()
    urls = []
    try:
        # Bumped timeout to 30s for massive enterprise sitemaps
        r = scraper.get(sitemap_url, timeout=30)
        r.raise_for_status()
        
        root = ET.fromstring(r.content)
        
        for elem in root.iter():
            if 'loc' in elem.tag and elem.text:
                loc = elem.text.strip()
                if loc.endswith('.xml'):
                    if len(urls) < max_urls:
                        # Graceful degradation on sub-sitemaps
                        try:
                            urls.extend(fetch_sitemap_urls(loc, max_urls - len(urls)))
                        except Exception as sub_e:
                            st.toast(f"Skipped a sub-sitemap due to timeout: {loc}")
                else:
                    urls.append(loc)
            if len(urls) >= max_urls:
                break
    except requests.exceptions.Timeout:
        st.error(f"⚠️ **Timeout Error:** The website took too long to respond ({sitemap_url}). It may be actively blocking bots or the sitemap is too large.")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 503:
            st.error(f"🛡️ **Firewall Blocked (503):** {sitemap_url} is protected by an enterprise firewall (like Cloudflare) that actively blocks automated scraping.")
        elif e.response.status_code == 403:
            st.error(f"🛑 **Forbidden (403):** This site explicitly denies access to automated tools.")
        else:
            st.error(f"⚠️ **HTTP Error ({e.response.status_code}):** {e}")
    except Exception as e:
        st.error(f"⚠️ **Error reading sitemap:** Could not parse {sitemap_url}. ({e})")
    
    return urls

if app_mode == "🔗 Link Up Optimizer":
    # ==========================================
    # TOOL 1: LINK UP OPTIMIZER
    # ==========================================
    st.markdown("### 📚 Step 1: Select Link Database")
    st.markdown("Choose how you want to build your internal link dictionary.")
    base_domain = st.text_input("Target Base Domain", placeholder="https://www.example.com", help="Used to resolve relative URLs in your crawl or sitemap (Optional).")
    
    tab_csv, tab_sitemap = st.tabs(["📁 Upload CSV (High Accuracy)", "🌐 Scan Live Sitemap (Fast)"])
    
    master_link_map = {}
    sorted_keywords = []
    database_ready = False
    
    with tab_csv:
        st.markdown("**Upload SEO Crawls:**")
        csv_files = st.file_uploader(
            "Upload CSV Crawls", 
            type=["csv"], 
            accept_multiple_files=True,
            label_visibility="collapsed"
        )
        
        if csv_files:
            with st.spinner("Processing CSV databases..."):
                for file in csv_files:
                    try:
                        df = pd.read_csv(file)
                        cols = df.columns.tolist()
                        lower_cols = [str(c).lower() for c in cols]
                        
                        kw_col, url_col = cols[0], cols[1]

                        # Smart Column Detection
                        if 'h1-1' in lower_cols: kw_col = cols[lower_cols.index('h1-1')]
                        elif 'title 1' in lower_cols: kw_col = cols[lower_cols.index('title 1')]
                        elif 'keyword' in lower_cols: kw_col = cols[lower_cols.index('keyword')]

                        if 'address' in lower_cols: url_col = cols[lower_cols.index('address')]
                        elif 'url' in lower_cols: url_col = cols[lower_cols.index('url')]
                        elif 'permalink' in lower_cols: url_col = cols[lower_cols.index('permalink')]

                        # Strict SEO Filtering
                        mask = pd.Series(True, index=df.index)
                        if 'status code' in lower_cols:
                            mask &= df[cols[lower_cols.index('status code')]].astype(str).str.strip().isin(['200', '200.0'])
                        if 'indexability' in lower_cols:
                            mask &= (df[cols[lower_cols.index('indexability')]].astype(str).str.strip().str.lower() == 'indexable')
                            
                        df_filtered = df[mask].copy()
                        df_links = df_filtered[[kw_col, url_col]].dropna().copy()
                        df_links[kw_col] = df_links[kw_col].astype(str).str.strip()
                        df_links[url_col] = df_links[url_col].astype(str).str.strip()
                        
                        # Clean URLs & Assets
                        valid_urls = df_links[url_col].str.startswith(('http://', 'https://', '/'), na=False)
                        no_assets = ~df_links[url_col].str.contains(r'\.(pdf|jpg|jpeg|png|gif|docx|doc)$', case=False, regex=True, na=False)
                        df_links = df_links[valid_urls & no_assets]

                        # Filter short words
                        df_links = df_links[df_links[kw_col].str.len() > 3]

                        # Build Map
                        for index, row in df_links.drop_duplicates(subset=[kw_col], keep='first').iterrows():
                            kw = row[kw_col].lower()
                            url = row[url_col]
                            if url.startswith('/'): 
                                url = f"{base_domain.rstrip('/')}{url}" if base_domain else url
                            master_link_map[kw] = url
                            
                    except Exception as e:
                        st.error(f"Error reading {file.name}: {e}")

                if master_link_map:
                    database_ready = True
                    sorted_keywords = sorted(master_link_map.keys(), key=len, reverse=True)

    with tab_sitemap:
        st.markdown("**Extract URLs directly from a website:**")
        st.markdown("*Note: Paste a homepage (e.g., `theatlantic.com`) and we will auto-discover the sitemap!*")
        
        col_sm1, col_sm2 = st.columns([3, 1])
        with col_sm1:
            sitemap_input = st.text_input("Website or Sitemap URL", placeholder="https://www.example.com", label_visibility="collapsed")
        with col_sm2:
            scan_btn = st.button("Scan Site", type="primary", use_container_width=True)
            
        if scan_btn and sitemap_input:
            with st.spinner("Locating and parsing sitemap... this may take a moment for large sites."):
                # Run Auto-Discovery First
                actual_sitemap_url = discover_sitemap(sitemap_input)
                
                if actual_sitemap_url != sitemap_input:
                    st.info(f"🔍 **Auto-discovered sitemap:** `{actual_sitemap_url}`")
                    
                raw_urls = fetch_sitemap_urls(actual_sitemap_url)
                
                if not raw_urls:
                    st.error("❌ Scan Failed. The website may be blocking automated scrapers, or the sitemap could not be parsed.")
                else:
                    for url in set(raw_urls):
                        # Skip junk assets
                        if re.search(r'\.(pdf|jpg|jpeg|png|gif|docx|doc)$', url, re.IGNORECASE): continue
                        
                        # Reverse-engineer keyword from the URL slug
                        parsed = urlparse(url)
                        path_parts = [p for p in parsed.path.split('/') if p]
                        
                        if not path_parts: continue # Skip homepage
                        
                        # Grab the last part of the URL, remove hyphens, title case it
                        raw_slug = path_parts[-1]
                        keyword = raw_slug.replace('-', ' ').replace('_', ' ').strip().title()
                        
                        # Basic filtering
                        if len(keyword) > 3 and not keyword.isdigit():
                            kw_lower = keyword.lower()
                            master_link_map[kw_lower] = url
                    
                    if master_link_map:
                        database_ready = True
                        sorted_keywords = sorted(master_link_map.keys(), key=len, reverse=True)

    if not database_ready:
        st.info("👆 **Upload a database or scan a sitemap above to proceed to the next step!**")
    else:
        st.success(f"✅ **Database Ready:** {len(master_link_map):,} keywords loaded successfully.")

        # --- Main Area: Provide Article (Progressively Disclosed) ---
        st.divider()
        st.markdown("### 📝 Step 2: Provide Article")
        
        with st.expander("⚙️ Advanced SEO Settings & Filters", expanded=False):
            st.markdown("Use these settings to fine-tune how the tool processes your text.")
            col1, col2 = st.columns(2)
            with col1:
                target_url = st.text_input("Final URL (Prevents Self-Linking)", help="Paste the URL where this article lives so it doesn't link to itself.")
                strip_above_p = st.checkbox("Strip junk above first paragraph", value=True, help="Removes site navigation menus and ESI headers.")
                silo_filter = st.text_input("URL Silo Filter", help="Force links to stay within a specific subfolder (e.g., '/blog/').")
            with col2:
                ignore_kws_input = st.text_area(
                    "Generic Keywords to Ignore", 
                    value="contact us, read more, click here, learn more, about us, home, services, products",
                    height=130
                )

        def clean_url_str(u):
            if not isinstance(u, str): return ""
            return re.sub(r'^https?://(www\.)?', '', u).rstrip('/').lower()
            
        target_url_clean = clean_url_str(target_url) if target_url else None

        tab_file, tab_paste, tab_url = st.tabs(["📄 Upload File", "✍️ Paste Text", "🌐 Scrape Live URL"])
        raw_html = ""
        
        with tab_file:
            doc_file = st.file_uploader("Upload Article Draft (.docx, .html)", type=["docx", "html", "htm"], label_visibility="collapsed")
            if doc_file:
                if doc_file.name.lower().endswith(('.html', '.htm')):
                    raw_html_content = doc_file.getvalue().decode("utf-8", errors="ignore")
                    soup_upload = BeautifulSoup(raw_html_content, 'html.parser')
                    main_content = soup_upload.find('main') or soup_upload.find('article') or soup_upload.find('div', class_=re.compile(r'content|main|region-content', re.I))
                    raw_html = str(main_content) if main_content else (str(soup_upload.body) if soup_upload.body else raw_html_content)
                else:
                    style_map = "p[style-name='Heading 1'] => h1:fresh\np[style-name='Heading 2'] => h2:fresh\np[style-name='Heading 3'] => h3:fresh"
                    result = mammoth.convert_to_html(doc_file, style_map=style_map)
                    raw_html = result.value

        with tab_paste:
            paste_text = st.text_area("Paste your draft text or HTML here:", height=250, label_visibility="collapsed")
            if paste_text and st.button("Process Pasted Text", type="primary"):
                raw_html = paste_text

        with tab_url:
            fetch_url = st.text_input("Paste the live URL to scrape:", label_visibility="collapsed", placeholder="https://www.example.com/blog/article-name")
            if fetch_url and st.button("Fetch & Process URL", type="primary"):
                with st.spinner("Fetching content..."):
                    try:
                        scraper = get_scraper()
                        res = scraper.get(fetch_url)
                        res.raise_for_status()
                        soup_fetch = BeautifulSoup(res.text, 'html.parser')
                        main_content = soup_fetch.find('main') or soup_fetch.find('article') or soup_fetch.find('div', class_=re.compile(r'content|main|region-content', re.I))
                        
                        if main_content:
                            raw_html = str(main_content)
                            st.success("Successfully extracted the main content area.")
                        else:
                            raw_html = str(soup_fetch.body) if soup_fetch.body else res.text
                            st.warning("Could not isolate main content; processed the entire page body.")
                    except requests.exceptions.HTTPError as e:
                        if e.response.status_code in [503, 403]:
                            st.error(f"🛡️ **Firewall Blocked ({e.response.status_code}):** This site is protected by a firewall that blocks scraping. Try pasting the text instead.")
                        else:
                            st.error(f"Error fetching URL: {e}")
                    except Exception as e:
                        st.error(f"Error fetching URL: {e}")

        # --- Run Link Up Logic ---
        if raw_html:
            with st.spinner("✨ Optimizing your article..."):
                ignore_kws_list = [k.strip().lower() for k in ignore_kws_input.split(',')] if ignore_kws_input else []
                silo_filter_clean = silo_filter.strip().lower() if silo_filter else None

                if strip_above_p:
                    match = re.search(r'<p\b[^>]*>', raw_html, re.IGNORECASE)
                    if match: raw_html = raw_html[match.start():]
                
                soup = BeautifulSoup(raw_html, 'html.parser')
                
                for kw_lower in sorted_keywords:
                    if kw_lower in ignore_kws_list: continue

                    url = master_link_map[kw_lower]
                    
                    if silo_filter_clean:
                        url_lower = url.lower()
                        if silo_filter_clean not in url_lower: continue

                    if target_url_clean and clean_url_str(url) == target_url_clean: continue
                    
                    already_linked = False
                    for a_tag in soup.find_all('a'):
                        tag_text = a_tag.get_text()
                        if tag_text and re.search(r'\b' + re.escape(kw_lower) + r'\b', tag_text, re.IGNORECASE):
                            already_linked = True
                            break

                    state = {"first_found": already_linked}
                    pattern = re.compile(r'\b(' + re.escape(kw_lower) + r')\b', re.IGNORECASE)
                    
                    for text_node in list(soup.find_all(string=True)):
                        parent = text_node.parent
                        if parent is None: continue
                        if parent.name in ['a', 'script', 'style', 'h1', 'h2', 'h3', 'head', 'title', 'meta', 'link', 'noscript']: continue
                            
                        classes = parent.get('class', [])
                        if parent.name == 'span' and classes and 'link-mask' in classes: continue
                        if not text_node.strip(): continue

                        if pattern.search(str(text_node)):
                            def replace(match):
                                if not state["first_found"]:
                                    state["first_found"] = True
                                    return f'<a href="{url}">{match.group(1)}</a>'
                                else:
                                    return f'<span class="link-mask">{match.group(1)}</span>'
                            new_text = pattern.sub(replace, str(text_node))
                            if new_text != str(text_node):
                                text_node.replace_with(BeautifulSoup(new_text, 'html.parser'))

                for mask in soup.find_all('span', class_='link-mask'): mask.unwrap()
                    
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href'].strip()
                    if "file:///" in href:
                        href = href.replace('file:///', '/')
                    if href.startswith('/') and not href.startswith('//'):
                        # Apply dynamic base domain here
                        a_tag['href'] = f"{base_domain.rstrip('/')}{href}" if base_domain else href

                final_html = str(soup)

            st.success("🎉 **Transformation Complete!** Your article is ready for the CMS.")
            
            # Results Output
            st.divider()
            st.markdown("### 📋 Step 3: Review & Copy Code")
            res_col1, res_col2 = st.columns([2, 1])
            
            with res_col1:
                st.text_area("Copy this HTML into your CMS source code editor:", value=final_html, height=300, label_visibility="collapsed")
            
            with res_col2:
                st.markdown("<br>", unsafe_allow_html=True) # Spacer
                st.download_button(
                    label="📥 Download HTML File", 
                    data=final_html, 
                    file_name="link_up_pro_output.html", 
                    mime="text/html",
                    use_container_width=True,
                    type="primary"
                )
                st.info("💡 **Pro Tip:** Switch your CMS editor to 'Source' or 'HTML' mode before pasting!")
                
            st.markdown("#### 👁️ Visual Preview")
            st.components.v1.html(final_html, height=400, scrolling=True)
            
            # --- AI SEO Metadata Generator ---
            st.divider()
            st.markdown("### 🧠 Step 4: AI SEO Recommendations")
            st.markdown("Generate search-optimized metadata for your CMS based on the final linked content.")
            
            if st.button("Generate SEO Metadata ✨", type="primary", key="generate_seo"):
                with st.spinner("Analyzing article content..."):
                    plain_text = BeautifulSoup(final_html, 'html.parser').get_text(separator=" ", strip=True)[:50000]
                    api_key = "AIzaSyBEcth2QVmYrQ4EgFbXG14_TIVFqWEUqS8"
                    
                    payload = {
                        "contents": [{
                            "role": "user",
                            "parts": [{
                                "text": f"You are an expert SEO specialist. Read the following article and provide an optimized H1, Meta Title (max 60 chars), and Meta Description (max 160 chars, compelling and click-worthy).\n\nArticle Text:\n{plain_text}"
                            }]
                        }],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": {
                                "type": "OBJECT",
                                "properties": {
                                    "h1": {"type": "STRING"},
                                    "meta_title": {"type": "STRING"},
                                    "meta_description": {"type": "STRING"}
                                },
                                "required": ["h1", "meta_title", "meta_description"]
                            }
                        }
                    }
                    
                    models_to_try = ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-8b"]
                    success = False
                    error_msg = ""
                    final_status = 0
                    seo_data = {}
                    
                    for model in models_to_try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                        try:
                            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
                            final_status = response.status_code
                            if final_status == 200:
                                resp_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                                seo_data = json.loads(resp_text)
                                success = True
                                st.success(f"✅ **SEO Metadata Generated!** *(Used {model})*")
                                break
                            else:
                                error_msg = response.text
                                if final_status in [429, 404]: continue
                                if final_status in [400, 403]: break
                        except Exception as e:
                            error_msg = str(e)
                            final_status = 500
                            break
                            
                    if success:
                        st.text_input("🎯 Optimized H1:", value=seo_data.get('h1', ''))
                        st.text_input("🔍 Meta Title (Under 60 chars):", value=seo_data.get('meta_title', ''))
                        st.text_area("📝 Meta Description (Under 160 chars):", value=seo_data.get('meta_description', ''))
                    else:
                        if final_status == 429:
                            st.error("❌ **Account Quota Locked**\n\nGoogle is actively blocking this API key from the free tier across all models.")
                        else:
                            st.error(f"❌ **API Error ({final_status})**\n\n{error_msg}")

elif app_mode == "🖼️ AI Alt Text Generator":
    # ==========================================
    # TOOL 2: ALT TEXT GENERATOR
    # ==========================================
    st.markdown("### 🖼️ AI Alt Text Generator")
    st.markdown("Upload an image to automatically generate accessibility-friendly alt text. The AI is pre-configured to keep it concise and highly descriptive.")
    
    api_key = "AIzaSyBEcth2QVmYrQ4EgFbXG14_TIVFqWEUqS8"
    img_file = st.file_uploader("Upload Image", type=["png", "jpg", "jpeg", "webp"])
    
    if img_file:
        col1, col2 = st.columns([1, 2])
        with col1:
            st.image(img_file, use_container_width=True)
        with col2:
            st.markdown("#### Actions")
            if st.button("Generate Alt Text ✨", type="primary"):
                with st.spinner("Analyzing image structure and context..."):
                    base64_img = base64.b64encode(img_file.getvalue()).decode('utf-8')
                    payload = {
                        "contents": [{
                            "role": "user",
                            "parts": [
                                { "text": "You are an expert web accessibility specialist. Write a concise, descriptive alt text for this image. Do not include phrases like 'Image of' or 'Picture of'. Focus purely on the subject matter and keep it under 125 characters." },
                                { "inlineData": { "mimeType": img_file.type, "data": base64_img } }
                            ]
                        }]
                    }
                    
                    models_to_try = ["gemini-1.5-flash", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash-8b"]
                    success = False
                    error_msg = ""
                    final_status = 0
                    
                    for model in models_to_try:
                        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
                        try:
                            response = requests.post(url, json=payload, headers={'Content-Type': 'application/json'})
                            final_status = response.status_code
                            if final_status == 200:
                                alt_text = response.json()['candidates'][0]['content']['parts'][0]['text']
                                st.success(f"✅ **Generation Complete!** *(Used {model})*")
                                st.text_input("Copy your Alt Text here:", value=alt_text.strip())
                                success = True
                                break
                            else:
                                error_msg = response.text
                                if final_status in [429, 404]: continue
                                if final_status in [400, 403]: break
                        except Exception as e:
                            error_msg = str(e)
                            final_status = 500
                            break
                            
                    if not success:
                        if final_status == 429:
                            st.error("❌ **Account Quota Locked**\n\nGoogle is actively blocking this API key from the free tier across all models.")
                        else:
                            st.error(f"❌ **API Error ({final_status})**\n\n{error_msg}")
