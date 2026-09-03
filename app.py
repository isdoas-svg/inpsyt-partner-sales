import io
import os
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 0. 데이터 영구 저장 유틸리티 함수
# ==========================================
SALES_FILE_PATH = "sales_data.csv"

# Google Sheets 연결 객체 생성
conn = st.connection("gsheets", type=GSheetsConnection)

DEFAULT_ORGS = {}

def clean_dataframe_types(df):
    """년도, 월, 매출금액, 기관코드 등의 타입을 정수로 정형화합니다."""
    if df is None or df.empty:
        return pd.DataFrame(columns=["년도", "월", "기관코드", "기관", "매출금액"])
    
    df = df.copy()
    
    # 소수점문자열 또는 float 타입을 정수형으로 변환
    if "년도" in df.columns:
        df["년도"] = pd.to_numeric(df["년도"], errors="coerce").fillna(0).astype(int)
    if "월" in df.columns:
        df["월"] = pd.to_numeric(df["월"], errors="coerce").fillna(0).astype(int)
    if "매출금액" in df.columns:
        df["매출금액"] = pd.to_numeric(df["매출금액"], errors="coerce").fillna(0).astype(int)
    if "기관코드" in df.columns:
        df["기관코드"] = df["기관코드"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
        
    # 빈 값 또는 0년도 데이터 제거
    df = df[(df["년도"] > 0) & (df["월"] > 0)].reset_index(drop=True)
    return df

@st.cache_data(ttl=60)
def load_sales_data():
    """Google Sheets의 sales 워크시트에서 매출 데이터를 불러옵니다."""
    with st.spinner("Running..."):
        try:
            sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
            df_sales = conn.read(spreadsheet=sheet_url, worksheet="sales", ttl=60) if sheet_url else conn.read(worksheet="sales", ttl=60)
            return clean_dataframe_types(df_sales)
        except Exception as e:
            if os.path.exists(SALES_FILE_PATH):
                df_local = pd.read_csv(SALES_FILE_PATH)
                return clean_dataframe_types(df_local)
            return pd.DataFrame(columns=["년도", "월", "기관코드", "기관", "매출금액"])

@st.cache_data(ttl=60)
def load_persistent_db():
    """Google Sheets에서 계정, 기관 및 목표 매출 DB를 불러옵니다."""
    users = {}
    orgs = DEFAULT_ORGS.copy()
    targets = {}

    with st.spinner("Running..."):
        try:
            sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
            df_users = conn.read(spreadsheet=sheet_url, worksheet="users", ttl=60) if sheet_url else conn.read(worksheet="users", ttl=60)
            
            try:
                df_targets = conn.read(spreadsheet=sheet_url, worksheet="targets", ttl=60) if sheet_url else conn.read(worksheet="targets", ttl=60)
                if df_targets is not None and not df_targets.empty:
                    for _, row in df_targets.iterrows():
                        code = str(row["org_code"]).strip().replace(".0", "")
                        year = int(float(row["year"]))
                        amt = int(float(row["target_amount"]))
                        targets[(code, year)] = amt
            except Exception:
                pass

            if df_users is not None and not df_users.empty:
                df_users = df_users.fillna("")
                
                for _, row in df_users.iterrows():
                    def clean_str(val):
                        s = str(val).strip()
                        if s.endswith(".0"):
                            return s[:-2]
                        return s

                    uid = clean_str(row["username"])
                    if not uid:
                        continue
                        
                    users[uid] = {
                        "password": clean_str(row["password"]),
                        "role": clean_str(row["role"]),
                        "org_code": clean_str(row["org_code"]),
                    }
                    
                    if row["role"] == "user" and row.get("org_name"):
                        orgs[clean_str(row["org_code"])] = {"org_name": clean_str(row["org_name"])}
        except Exception as e:
            st.warning(f"⚠️ Google Sheets 데이터를 불러오는 중 오류 발생 (기본 설정으로 구동): {e}")

    if "admin" not in users:
        users["admin"] = {
            "password": "1234",
            "role": "super_admin",
            "org_code": "ALL",
            "org_name": "전체(총 관리자)",
        }

    return orgs, users, targets

def save_sales_data(df):
    """매출 데이터를 백업용 로컬 CSV 저장과 동시에 Google Sheets 'sales' 워크시트에 업데이트합니다."""
    if df is not None:
        df = clean_dataframe_types(df)
        df.to_csv(SALES_FILE_PATH, index=False, encoding="utf-8-sig")
        try:
            with st.spinner("Running..."):
                sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
                conn.update(spreadsheet=sheet_url, worksheet="sales", data=df)
                st.cache_data.clear()
            st.toast("✅ Google Sheets에 매출 데이터가 안전하게 저장되었습니다!", icon="💾")
        except Exception as e:
            st.error(f"⚠️ Google Sheets 매출 데이터 저장 중 오류 발생: {e}")

def save_targets_data():
    """st.session_state['targets_db'] 데이터를 구글 시트 'targets' 워크시트에 보존합니다."""
    targets_db = st.session_state.get("targets_db", {})
    data = []
    for (code, year), amt in targets_db.items():
        data.append({"org_code": code, "year": int(year), "target_amount": int(amt)})
    
    df_targets = pd.DataFrame(data)
    try:
        with st.spinner("Running..."):
            sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
            conn.update(spreadsheet=sheet_url, worksheet="targets", data=df_targets)
            st.cache_data.clear()
        st.toast("✅ Google Sheets에 목표 매출 데이터가 안전하게 저장되었습니다!", icon="💾")
    except Exception as e:
        st.error(f"⚠️ Google Sheets 목표 매출 데이터 저장 중 오류 발생: {e}")


# ==========================================
# 1. 금액 한글 변환 함수
# ==========================================
def format_korean_currency_detail(val):
    if not val or val == 0:
        return "0원"
    
    units = ["", "만", "억", "조"]
    num_str = str(int(val))
    length = len(num_str)
    result_parts = []
    
    for i in range(0, length, 4):
        part = int(num_str[max(0, length - i - 4):length - i])
        if part > 0:
            unit_idx = i // 4
            unit = units[unit_idx] if unit_idx < len(units) else ""
            
            part_str = ""
            cheon = part // 1000
            baek = (part % 1000) // 100
            sip = (part % 100) // 10
            il = part % 10
            
            if cheon > 0 or baek > 0:
                if cheon > 0: part_str += f"{cheon}천 "
                if baek > 0: part_str += f"{baek}백 "
                if sip > 0: part_str += f"{sip}십 "
                if il > 0: part_str += f"{il}"
            else:
                part_str = str(part)
            
            part_str = part_str.strip()
            if part_str:
                result_parts.append(f"{part_str}{unit}")
                
    return " ".join(reversed(result_parts)) + "원"


def format_korean_currency(val):
    if val == 0:
        return "0원"
    eok = val // 100_000_000
    remainder = val % 100_000_000
    cheon = remainder // 10_000_000
    res = ""
    if eok > 0:
        res += f"{int(eok)}억 "
    if cheon > 0:
        res += f"{int(cheon)}천만 "
    elif eok == 0 and remainder > 0:
        res += f"{int(remainder // 10_000)}만 "
    return res.strip() + "원"


# -----------------------------------------------------------------------------
# 2. 페이지 기본 설정 및 세션 초기화
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="인싸이트 지사 매출 확인", page_icon="📊", layout="wide"
)

st.markdown(
    """
    <style>
    div[data-testid="stSelectbox"] {
        max-width: 220px !important;
    }
    </style>
""",
    unsafe_allow_html=True,
)

loaded_orgs, loaded_users, loaded_targets = load_persistent_db()

if "orgs_db" not in st.session_state:
    st.session_state["orgs_db"] = loaded_orgs
if "user_db" not in st.session_state:
    st.session_state["user_db"] = loaded_users
if "targets_db" not in st.session_state:
    st.session_state["targets_db"] = loaded_targets
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "user_info" not in st.session_state:
    st.session_state["user_info"] = None
if "selected_detail_org" not in st.session_state:
    st.session_state["selected_detail_org"] = None

if "df_accumulated" not in st.session_state:
    st.session_state["df_accumulated"] = load_sales_data()


# -----------------------------------------------------------------------------
# 4. 로그인 화면
# -----------------------------------------------------------------------------
def login_screen():
    _, center_col, _ = st.columns([3.75, 2.5, 3.75])
    
    with center_col:
        st.markdown("<h2 style='text-align: center;'>인싸이트 지사 매출</h2>", unsafe_allow_html=True)
        st.markdown("---")
        
        with st.form(key="login_form"):
            username = st.text_input("아이디 (ID)", key="login_username_input").strip()
            password = st.text_input("비밀번호 (Password)", type="password", key="login_password_input").strip()
            submit_login = st.form_submit_button("로그인", use_container_width=True, type="primary")
        
        if submit_login:
            user_db = st.session_state["user_db"]
            orgs_db = st.session_state["orgs_db"]

            if username in user_db and user_db[username]["password"] == password:
                u_info = user_db[username]
                role = u_info.get("role", "user")
                org_code = u_info.get("org_code", "ALL")

                if role == "super_admin":
                    current_org_name = "전체(총 관리자)"
                elif role == "hq_admin":
                    current_org_name = "전체(본사 관리자)"
                else:
                    current_org_name = orgs_db.get(org_code, {}).get("org_name", "미지정 기관")

                st.session_state["logged_in"] = True
                st.session_state["user_info"] = {
                    "username": username,
                    "role": role,
                    "org_code": org_code,
                    "org_name": current_org_name,
                }
                st.success("로그인 성공!")
                st.rerun()
            else:
                st.error("아이디 또는 비밀번호가 올바르지 않습니다.")


# -----------------------------------------------------------------------------
# 5. 계정 관리 화면
# -----------------------------------------------------------------------------
def admin_account_page():
    st.title("👤 계정 관리")
    st.markdown("---")

    current_role = st.session_state["user_info"]["role"]

    tab_reg, tab_edit_user, tab_edit_org, tab_delete_user = st.tabs([
        "➕ 계정 신규 등록",
        "✏️ 계정/비밀번호 수정",
        "🏢 기관명 변경",
        "🗑️ 계정 삭제",
    ])

    with tab_reg:
        st.subheader("신규 계정 생성")
        
        form_col, _ = st.columns([5.5, 4.5])
        with form_col:
            with st.form("add_user_form"):
                if current_role == "super_admin":
                    role_type = st.radio(
                        "계정 권한 선택",
                        ["🏢 일반 지사 회원", "🏢 본사 관리자", "👑 총 관리자"],
                        horizontal=True
                    )
                else:
                    st.info("💡 본사 관리자 권한으로는 **일반 지사 회원** 계정만 생성할 수 있습니다.")
                    role_type = "🏢 일반 지사 회원"

                c1, c2 = st.columns(2)
                with c1:
                    if role_type == "🏢 일반 지사 회원":
                        new_org_code = st.text_input("기관 고유코드", placeholder="예: ORG_004").strip()
                    else:
                        new_org_code = "ALL"
                        st.info("💡 관리자 전용 기관코드 (ALL)")
                    new_id = st.text_input("로그인 아이디 (ID)", placeholder="예: admin2 또는 org_d").strip()
                
                with c2:
                    if role_type == "🏢 일반 지사 회원":
                        new_org_name = st.text_input("기관 표시명", placeholder="예: D기관").strip()
                    else:
                        new_org_name = "전체(관리자)"
                        st.info("💡 관리자 전용 기관명")
                    new_pw = st.text_input("비밀번호 (Password)", type="password").strip()

                submit_add = st.form_submit_button("신규 계정 생성", use_container_width=True)

            if submit_add:
                if not new_id or not new_pw:
                    st.warning("아이디와 비밀번호를 모두 입력해 주세요.")
                elif role_type == "🏢 일반 지사 회원" and (not new_org_code or not new_org_name):
                    st.warning("지사 계정 생성 시 기관 고유코드와 기관명을 필수 입력해야 합니다.")
                elif new_id in st.session_state["user_db"]:
                    st.error("이미 존재하는 아이디입니다. 다른 아이디를 사용해 주세요.")
                elif role_type == "🏢 일반 지사 회원" and new_org_code in st.session_state["orgs_db"]:
                    st.error("이미 존재하는 기관 고유코드입니다.")
                else:
                    if role_type == "👑 총 관리자":
                        target_role = "super_admin"
                    elif role_type == "🏢 본사 관리자":
                        target_role = "hq_admin"
                    else:
                        target_role = "user"
                    
                    if target_role == "user":
                        st.session_state["orgs_db"][new_org_code] = {"org_name": new_org_name}
                    
                    st.session_state["user_db"][new_id] = {
                        "password": new_pw,
                        "role": target_role,
                        "org_code": new_org_code,
                    }
                    
                    role_str_map = {"super_admin": "총 관리자", "hq_admin": "본사 관리자", "user": f"'{new_org_name}' 지사 회원"}
                    st.success(f"🎉 **{role_str_map[target_role]}** 계정('{new_id}')이 등록되었습니다.")
                    st.rerun()

    with tab_edit_user:
        st.subheader("계정 ID 및 비밀번호 수정")
        
        if current_role == "super_admin":
            user_ids = list(st.session_state["user_db"].keys())
        else:
            user_ids = [
                uid for uid, uinfo in st.session_state["user_db"].items()
                if uinfo.get("role") == "user"
            ]

        if not user_ids:
            st.info("수정 가능한 지사 회원 계정이 없습니다.")
        else:
            selected_user = st.selectbox("수정할 계정 선택", user_ids)
            curr_user_info = st.session_state["user_db"][selected_user]

            edit_form_col, _ = st.columns([5.5, 4.5])
            with edit_form_col:
                with st.form("edit_user_form"):
                    st.write(f"현재 선택된 계정 권한: **{curr_user_info['role']}** | 연동 기관 코드: **{curr_user_info['org_code']}**")
                    
                    c_id, c_pw = st.columns(2)
                    with c_id:
                        new_user_id = st.text_input("변경할 아이디 (ID)", value=selected_user)
                    with c_pw:
                        new_user_pw = st.text_input("변경할 비밀번호 (Password)", value=curr_user_info["password"])
                    
                    submit_user_edit = st.form_submit_button("계정 정보 변경 저장", use_container_width=True)

                if submit_user_edit:
                    if not new_user_id.strip() or not new_user_pw.strip():
                        st.warning("아이디와 비밀번호를 올바르게 입력해 주세요.")
                    else:
                        new_id_clean = new_user_id.strip()
                        if new_id_clean != selected_user and new_id_clean in st.session_state["user_db"]:
                            st.error("이미 존재하는 다른 아이디입니다. 다른 아이디를 입력해 주세요.")
                        else:
                            info = st.session_state["user_db"].pop(selected_user)
                            info["password"] = new_user_pw.strip()
                            st.session_state["user_db"][new_id_clean] = info

                            if st.session_state["user_info"]["username"] == selected_user:
                                st.session_state["user_info"]["username"] = new_id_clean

                            st.success(f"계정 정보가 성공적으로 변경되었습니다. (ID: **{new_id_clean}**)")
                            st.rerun()

    with tab_edit_org:
        st.subheader("기관명 변경 (상호명/지사명 변경 시)")
        org_codes = list(st.session_state["orgs_db"].keys())
        if org_codes:
            selected_code = st.selectbox(
                "명칭을 변경할 기관 선택",
                org_codes,
                format_func=lambda x: f"[{x}] {st.session_state['orgs_db'][x]['org_name']}",
            )
            current_name = st.session_state["orgs_db"][selected_code]["org_name"]

            org_edit_col, _ = st.columns([5.5, 4.5])
            with org_edit_col:
                with st.form("edit_org_form"):
                    st.write(f"현재 선택된 기관 고유코드: **{selected_code}**")
                    updated_name = st.text_input("새로운 기관명 입력", value=current_name)
                    submit_edit = st.form_submit_button("기관명 수정 반영", use_container_width=True)

                if submit_edit:
                    if updated_name.strip() == "":
                        st.warning("기관명을 입력해주세요.")
                    else:
                        new_name_clean = updated_name.strip()
                        st.session_state["orgs_db"][selected_code]["org_name"] = new_name_clean

                        if st.session_state["df_accumulated"] is not None and not st.session_state["df_accumulated"].empty:
                            df_acc = st.session_state["df_accumulated"]
                            if "기관코드" in df_acc.columns:
                                df_acc.loc[df_acc["기관코드"] == selected_code, "기관"] = new_name_clean
                            else:
                                df_acc.loc[df_acc["기관"] == current_name, "기관"] = new_name_clean
                            st.session_state["df_accumulated"] = df_acc
                            save_sales_data(df_acc)

                        st.success(f"기관명이 **'{current_name}'** ➡️ **'{new_name_clean}'**(으)로 변경되었습니다.")
                        st.rerun()

    with tab_delete_user:
        st.subheader("계정 삭제")
        st.caption("삭제하려는 계정 아이디(ID)를 검색/선택한 후 삭제를 진행할 수 있습니다.")

        if current_role == "super_admin":
            deletable_users = list(st.session_state["user_db"].keys())
        else:
            deletable_users = [
                uid for uid, uinfo in st.session_state["user_db"].items()
                if uinfo.get("role") == "user"
            ]

        if not deletable_users:
            st.info("삭제할 수 있는 계정이 존재하지 않습니다.")
        else:
            del_form_col, _ = st.columns([5.5, 4.5])
            with del_form_col:
                search_query = st.text_input("🔍 아이디 검색", placeholder="검색할 아이디 입력...", key="search_user_del_input").strip()

                if search_query:
                    matched_users = [uid for uid in deletable_users if search_query.lower() in uid.lower()]
                else:
                    matched_users = deletable_users

                if not matched_users:
                    st.warning(f"'{search_query}' 검색어와 일치하는 계정이 없습니다.")
                else:
                    selected_del_user = st.selectbox(
                        "삭제할 계정 선택",
                        matched_users,
                        key="selected_del_user_selectbox"
                    )

                    user_info_to_del = st.session_state["user_db"][selected_del_user]
                    del_role = user_info_to_del.get("role", "user")
                    del_org_code = user_info_to_del.get("org_code", "ALL")
                    
                    if del_role == "super_admin":
                        del_org_name = "전체(총 관리자)"
                    elif del_role == "hq_admin":
                        del_org_name = "전체(본사 관리자)"
                    else:
                        del_org_name = st.session_state["orgs_db"].get(del_org_code, {}).get("org_name", "미지정 기관")

                    role_label_map = {"super_admin": "총 관리자", "hq_admin": "본사 관리자", "user": "지사 회원"}

                    st.markdown("---")
                    st.markdown(f"**선택된 계정 정보**")
                    st.write(f"- **아이디**: `{selected_del_user}`")
                    st.write(f"- **권한**: {role_label_map.get(del_role, del_role)}")
                    st.write(f"- **소속 기관**: {del_org_name} ({del_org_code})")

                    if selected_del_user == st.session_state["user_info"]["username"]:
                        st.error("⚠️ 현재 로그인 중인 계정은 삭제할 수 없습니다.")
                    else:
                        st.warning("⚠️ 삭제된 계정 정보는 복구할 수 없습니다.")
                        if st.button("🚨 해당 계정 삭제", type="primary", use_container_width=True):
                            st.session_state["user_db"].pop(selected_del_user)
                            st.success(f"계정 **'{selected_del_user}'** 이(가) 성공적으로 삭제되었습니다.")
                            st.rerun()


# -----------------------------------------------------------------------------
# 6. 기관 관리 화면
# -----------------------------------------------------------------------------
def admin_organization_page():
    st.title("🏢 기관 관리")
    st.markdown("---")
    st.subheader("📋 등록된 계정 및 기관 매칭 현황")
    
    current_role = st.session_state["user_info"]["role"]
    user_list = []
    
    for uid, uinfo in st.session_state["user_db"].items():
        role = uinfo["role"]
        
        if current_role == "hq_admin" and role != "user":
            continue

        if role == "super_admin":
            org_display = "전체(총 관리자)"
        elif role == "hq_admin":
            org_display = "전체(본사 관리자)"
        else:
            code = uinfo["org_code"]
            org_display = st.session_state["orgs_db"].get(code, {}).get("org_name", "미지정")

        role_label_map = {"super_admin": "👑 총 관리자", "hq_admin": "🏢 본사 관리자", "user": "🏢 지사 회원"}

        user_list.append({
            "아이디": uid,
            "비밀번호": uinfo["password"],
            "권한": role_label_map.get(role, role),
            "고유 코드": uinfo["org_code"],
            "매칭된 기관명": org_display,
        })
        
    st.dataframe(pd.DataFrame(user_list), hide_index=True, use_container_width=False)


# -----------------------------------------------------------------------------
# 7. Target 설정
# -----------------------------------------------------------------------------
def admin_target_page():
    st.title("🎯 지사 목표 매출 등록")
    st.markdown("---")
    st.caption("각 기관의 회계연도별 목표 매출 금액을 설정합니다.")

    orgs_db = st.session_state["orgs_db"]
    org_codes = list(orgs_db.keys())

    if not org_codes:
        st.warning("등록된 기관이 없습니다. 계정 관리 메뉴에서 기관을 먼저 추가해 주세요.")
        return

    col_fy_year, _ = st.columns([1.5, 8.5])
    with col_fy_year:
        selected_fy = st.number_input("설정할 회계연도 (년)", min_value=2020, max_value=2030, value=2026, step=1)
    
    st.subheader(f"📅 {selected_fy} 회계연도 기관별 목표 매출 설정")

    def update_target_input(code):
        key = f"target_input_{code}_{selected_fy}"
        raw = st.session_state.get(key, "")
        nums = "".join(filter(str.isdigit, str(raw)))
        if nums:
            val_int = int(nums)
            st.session_state[key] = f"{val_int:,}"
            st.session_state[f"kr_str_{code}_{selected_fy}"] = format_korean_currency_detail(val_int)
        else:
            st.session_state[key] = ""
            st.session_state[f"kr_str_{code}_{selected_fy}"] = "0원"

    for code in org_codes:
        org_name = orgs_db[code]["org_name"]
        input_key = f"target_input_{code}_{selected_fy}"
        kr_key = f"kr_str_{code}_{selected_fy}"

        if input_key not in st.session_state:
            curr_target = st.session_state["targets_db"].get((code, selected_fy), 0)
            st.session_state[input_key] = f"{curr_target:,}" if curr_target > 0 else "0"
            st.session_state[kr_key] = format_korean_currency_detail(curr_target)

        col_title, col_input, col_kr, col_btn, _ = st.columns([1.8, 1.0, 2.2, 0.8, 4.2])

        with col_title:
            st.markdown(f"<div style='padding-top: 6px;'><b>[{code}] {org_name}</b></div>", unsafe_allow_html=True)

        with col_input:
            st.text_input(
                label=f"[{code}] 목표 매출액",
                key=input_key,
                on_change=update_target_input,
                args=(code,),
                label_visibility="collapsed",
                placeholder="0",
            )

        with col_kr:
            current_kr = st.session_state.get(kr_key, "0원")
            st.markdown(f"<div style='padding-top: 6px; font-weight: bold; color: #1E88E5;'>💬 {current_kr}</div>", unsafe_allow_html=True)

        with col_btn:
            if st.button("💾 저장", key=f"btn_save_{code}_{selected_fy}"):
                val_str = st.session_state.get(input_key, "0")
                cleaned_num = "".join(filter(str.isdigit, val_str))
                final_amount = int(cleaned_num) if cleaned_num else 0

                st.session_state["targets_db"][(code, int(selected_fy))] = final_amount
                
                save_targets_data()
                
                st.toast(
                    f"✅ [{org_name}] {selected_fy}년 목표 매출이 **{final_amount:,}원** ({st.session_state[kr_key]})으로 저장되었습니다!",
                    icon="🎉",
                )

    st.markdown("---")
    st.subheader(f"📊 {selected_fy} 회계연도 설정된 목표 매출 현황")
    summary_data = []
    for code in org_codes:
        org_name = orgs_db[code]["org_name"]
        amt = st.session_state["targets_db"].get((code, int(selected_fy)), 0)
        summary_data.append({
            "기관코드": code,
            "기관명": org_name,
            "목표 매출액": f"{amt:,.0f} 원",
            "한글 표기": format_korean_currency_detail(amt),
        })
    st.dataframe(pd.DataFrame(summary_data), hide_index=True, use_container_width=False)


# -----------------------------------------------------------------------------
# 8. 매출 데이터 업로드, 다운로드 & 데이터 삭제 관리 화면
# -----------------------------------------------------------------------------
def admin_upload_page():
    st.title("📂 매출 데이터 업로드, 다운로드 & 삭제 관리")
    st.markdown("---")

    current_role = st.session_state["user_info"]["role"]

    if current_role == "super_admin":
        tab_upload, tab_download, tab_delete = st.tabs([
            "📤 데이터 업로드",
            "📥 매출 데이터 다운로드",
            "🗑️ 데이터 삭제 관리",
        ])
    else:
        tab_download = st.container()

    if current_role == "super_admin":
        with tab_upload:
            st.subheader("매출 데이터 엑셀 누적 업로드")
            st.caption("1개월 또는 다수 월의 매출 엑셀 데이터를 기존 데이터에 추가 누적합니다.")

            uploaded_file = st.file_uploader("매출 데이터 엑셀/CSV 파일 업로드", type=["xlsx", "csv"])

            if uploaded_file is not None:
                try:
                    if uploaded_file.name.endswith(".csv"):
                        new_df = pd.read_csv(uploaded_file)
                    else:
                        new_df = pd.read_excel(uploaded_file)

                    if "기관코드" not in new_df.columns:
                        for code_col in ["지사코드", "고유코드", "code", "org_code"]:
                            if code_col in new_df.columns:
                                new_df.rename(columns={code_col: "기관코드"}, inplace=True)
                                break

                    req_cols = {"년도", "월", "매출금액"}
                    if not req_cols.issubset(set(new_df.columns)) or ("기관코드" not in new_df.columns and "기관" not in new_df.columns):
                        st.error(
                            f"필수 컬럼(년도, 월, 매출금액 및 기관코드/기관명)이 엑셀에 포함되어 있어야 합니다."
                        )
                    else:
                        new_df = clean_dataframe_types(new_df)
                        orgs_db = st.session_state["orgs_db"]
                        
                        if "기관코드" in new_df.columns:
                            new_df["기관코드"] = new_df["기관코드"].astype(str).str.strip().str.replace(r"\.0$", "", regex=True)
                            new_df["기관"] = new_df["기관코드"].apply(
                                lambda code: orgs_db.get(code, {}).get("org_name", f"미등록지사({code})")
                            )

                        group_cols = [
                            col
                            for col in ["년도", "월", "기관코드", "기관"]
                            if col in new_df.columns
                        ]
                        new_df = (
                            new_df.groupby(group_cols, as_index=False)[
                                "매출금액"
                            ]
                            .sum()
                        )

                        curr_acc = st.session_state["df_accumulated"]
                        if curr_acc is None or curr_acc.empty:
                            merged_df = new_df
                        else:
                            combined = pd.concat(
                                [curr_acc, new_df], ignore_index=True
                            )
                            acc_group_cols = [
                                col
                                for col in ["년도", "월", "기관코드", "기관"]
                                if col in combined.columns
                            ]
                            merged_df = (
                                combined.groupby(
                                    acc_group_cols, as_index=False
                                )["매출금액"]
                                .sum()
                            )

                        merged_df = clean_dataframe_types(merged_df)
                        st.session_state["df_accumulated"] = merged_df
                        save_sales_data(merged_df)
                        
                        st.success(f"🎉 데이터 업로드 완료! (현재 총 {len(merged_df):,}건 보관 중)")
                        st.dataframe(new_df.head(10), use_container_width=False)
                except Exception as e:
                    st.error(f"파일을 읽는 도중 오류가 발생했습니다: {e}")

    with tab_download:
        st.subheader("📥 선택 기간/기관 매출 데이터 엑셀 추출")
        df_acc = st.session_state["df_accumulated"]

        if df_acc is not None and not df_acc.empty:
            df_acc = clean_dataframe_types(df_acc)
            df_acc_calc = df_acc.copy()
            df_acc_calc["period_key"] = df_acc_calc["년도"] * 100 + df_acc_calc["월"]

            all_years = sorted([int(y) for y in df_acc["년도"].unique()])
            all_months = list(range(1, 13))
            all_orgs = ["전체"] + sorted(list(df_acc["기관"].unique()))

            col_drop_area, _ = st.columns([5, 5])
            with col_drop_area:
                col_d1, col_d2, col_d3, col_d4 = st.columns(4)
                with col_d1:
                    start_year = st.selectbox("시작 년도", all_years, index=0, key="dl_sy")
                with col_d2:
                    start_month = st.selectbox("시작 월", all_months, index=0, key="dl_sm")
                with col_d3:
                    end_year = st.selectbox("종료 년도", all_years, index=len(all_years) - 1, key="dl_ey")
                with col_d4:
                    end_month = st.selectbox("종료 월", all_months, index=11, key="dl_em")

            selected_dl_org = st.selectbox("기관 선택", all_orgs, index=0, key="dl_org_select")

            start_key = int(start_year) * 100 + int(start_month)
            end_key = int(end_year) * 100 + int(end_month)

            if start_key > end_key:
                st.error("시작 기간이 종료 기간보다 이후일 수 없습니다.")
            else:
                filtered_dl_df = df_acc_calc[
                    (df_acc_calc["period_key"] >= start_key) & (df_acc_calc["period_key"] <= end_key)
                ]

                if selected_dl_org != "전체":
                    filtered_dl_df = filtered_dl_df[filtered_dl_df["기관"] == selected_dl_org]

                output_cols = [col for col in ["년도", "월", "기관코드", "기관", "매출금액"] if col in filtered_dl_df.columns]
                final_export_df = filtered_dl_df[output_cols].sort_values(by=["년도", "월"]).reset_index(drop=True)

                st.write(f"📊 검색 결과: 총 **{len(final_export_df):,}** 건")
                st.dataframe(final_export_df, hide_index=True, use_container_width=False)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    final_export_df.to_excel(writer, index=False, sheet_name="매출데이터")
                
                excel_data = buffer.getvalue()
                
                file_org_str = "전체" if selected_dl_org == "전체" else selected_dl_org
                file_name = f"매출데이터_{file_org_str}_{start_year}{start_month:02d}_{end_year}{end_month:02d}.xlsx"

                st.download_button(
                    label="📥 선택 조건 엑셀 파일 다운로드",
                    data=excel_data,
                    file_name=file_name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
        else:
            st.info("다운로드할 매출 데이터가 존재하지 않습니다.")

    if current_role == "super_admin":
        with tab_delete:
            st.subheader("🗓️ 기간 지정을 통한 데이터 삭제")
            df_acc = st.session_state["df_accumulated"]

            if df_acc is not None and not df_acc.empty:
                df_acc = clean_dataframe_types(df_acc)
                st.write(f"현재 총 **{len(df_acc):,} 건**의 데이터가 보관 중입니다.")
                df_acc_calc = df_acc.copy()
                df_acc_calc["period_key"] = df_acc_calc["년도"] * 100 + df_acc_calc["월"]

                all_years = sorted([int(y) for y in df_acc["년도"].unique()])
                all_months = list(range(1, 13))

                col_s1, col_s2, col_e1, col_e2 = st.columns(4)
                with col_s1:
                    start_year = st.selectbox("시작 년도", all_years, index=0)
                with col_s2:
                    start_month = st.selectbox("시작 월", all_months, index=0)
                with col_e1:
                    end_year = st.selectbox("종료 년도", all_years, index=len(all_years) - 1)
                with col_e2:
                    end_month = st.selectbox("종료 월", all_months, index=11)

                start_key = int(start_year) * 100 + int(start_month)
                end_key = int(end_year) * 100 + int(end_month)

                if start_key > end_key:
                    st.error("시작 기간이 종료 기간보다 이후일 수 없습니다.")
                else:
                    del_targets = df_acc_calc[
                        (df_acc_calc["period_key"] >= start_key) & (df_acc_calc["period_key"] <= end_key)
                    ]
                    st.info(f"선택 기간: **{start_year}년 {start_month}월 ~ {end_year}년 {end_month}월** (삭제 대상: 총 **{len(del_targets)}건** 데이터)")

                    if st.button("🚨 선택 기간 데이터 삭제", type="primary"):
                        remaining_df = df_acc_calc[
                            ~((df_acc_calc["period_key"] >= start_key) & (df_acc_calc["period_key"] <= end_key))
                        ]
                        updated_df = remaining_df.drop(columns=["period_key"]).reset_index(drop=True)
                        st.session_state["df_accumulated"] = updated_df
                        save_sales_data(updated_df)
                        st.success("해당 기간의 매출 데이터가 정상 삭제되었습니다.")
                        st.rerun()

                st.markdown("---")
                st.subheader("⚠️ 전체 데이터 초기화")
                st.caption("실수를 방지하기 위해 관리자 비밀번호를 다시 확인합니다.")

                with st.form("reset_form"):
                    admin_pw_confirm = st.text_input("관리자 비밀번호 확인", type="password")
                    reset_submit = st.form_submit_button("🔥 전체 데이터 완전 삭제")

                    if reset_submit:
                        admin_actual_pw = st.session_state["user_db"]["admin"]["password"]
                        if admin_pw_confirm == admin_actual_pw:
                            empty_df = pd.DataFrame(columns=["년도", "월", "기관코드", "기관", "매출금액"])
                            st.session_state["df_accumulated"] = empty_df
                            save_sales_data(empty_df)
                            st.success("모든 매출 데이터가 초기화되었습니다.")
                            st.rerun()
                        else:
                            st.error("관리자 비밀번호가 올바르지 않습니다.")
            else:
                st.info("현재 저장된 매출 데이터가 없습니다.")


# -----------------------------------------------------------------------------
# 9. 메인 대시보드 화면 및 앱 제어
# -----------------------------------------------------------------------------
def main_dashboard():
    user = st.session_state["user_info"]

    role_display_map = {
        "super_admin": "👑 총 관리자",
        "hq_admin": "🏢 본사 관리자",
        "user": "🏢 지사 회원"
    }

    with st.sidebar:
        st.title("👤 접속 정보")
        st.write(f"**사용자:** {user['username']}")
        st.write(f"**권한:** {role_display_map.get(user['role'], user['role'])}")
        st.write(f"**소속 기관:** {user['org_name']}")

        if st.button("로그아웃", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["user_info"] = None
            st.rerun()

        st.markdown("<br><hr><br>", unsafe_allow_html=True)

        menu_selection = "📈 매출 분석 대시보드"
        
        if user["role"] in ["super_admin", "hq_admin"]:
            st.subheader("⚙️ 관리자 메뉴")
            st.markdown(
                """
                <style>
                div[data-testid="stRadio"] > label { font-weight: bold; margin-bottom: 8px; }
                div[data-testid="stRadio"] div[role="radiogroup"] > label { padding-top: 10px; padding-bottom: 10px; }
                </style>
            """,
                unsafe_allow_html=True,
            )

            admin_menu_options = [
                "📈 매출 분석 대시보드",
                "👤 지사 계정 관리",
                "🏢 지사 등록 현황",
                "🎯 지사 목표 매출 등록",
            ]
            
            if user["role"] == "super_admin":
                admin_menu_options.append("📂 매출 데이터 업로드")
            else:
                admin_menu_options.append("📥 매출 데이터 다운로드")

            menu_selection = st.radio(
                "메뉴 이동",
                admin_menu_options,
                label_visibility="collapsed",
            )
            st.markdown("<br>", unsafe_allow_html=True)

    if user["role"] in ["super_admin", "hq_admin"]:
        if menu_selection == "👤 지사 계정 관리":
            admin_account_page()
            return
        elif menu_selection == "🏢 지사 등록 현황":
            admin_organization_page()
            return
        elif menu_selection == "🎯 지사 목표 매출 등록":
            admin_target_page()
            return
        elif menu_selection in ["📂 매출 데이터 업로드", "📥 매출 데이터 다운로드"]:
            admin_upload_page()
            return

    df_raw = st.session_state["df_accumulated"]
    if df_raw is None or df_raw.empty:
        st.info("등록된 매출 데이터가 없습니다. 관리자에게 문의해 주세요.")
        return

    # 정수 타입 강제 적용
    df_raw = clean_dataframe_types(df_raw)
    
    df_raw["회계연도"] = df_raw.apply(
        lambda row: int(row["년도"]) + 1 if int(row["월"]) == 12 else int(row["년도"]), axis=1
    )

    render_dashboard_content(df_raw, user)


def render_dashboard_content(df_raw, user):
    st.title("📈 매출 분석 대시보드")
    st.caption("※ 회계연도 기준: 전년도 12월 ~ 당해년도 11월")

    registered_org_names = sorted([info["org_name"] for info in st.session_state["orgs_db"].values()])

    selected_org = "전체"
    if user["role"] in ["super_admin", "hq_admin"]:
        st.subheader("👑 관리자 모드: 전체 기관 데이터 조회")
        all_orgs = ["전체"] + registered_org_names
        selected_org = st.selectbox("조회할 기관 선택", all_orgs)

        if selected_org != "전체":
            filtered_df = df_raw[df_raw["기관"] == selected_org]
        else:
            filtered_df = df_raw
    else:
        st.subheader(f"🏢 {user['org_name']} 매출 분석")

        if "기관코드" in df_raw.columns:
            filtered_df = df_raw[df_raw["기관코드"].astype(str).str.strip() == str(user["org_code"]).strip()].copy()
            filtered_df["기관"] = user["org_name"]
        else:
            filtered_df = df_raw[df_raw["기관"] == user["org_name"]]

        if filtered_df.empty:
            st.warning(f"등록된 [{user['org_code']}] 코드({user['org_name']})의 매출 데이터가 없습니다. 관리자에게 문의해 주세요.")
            return

    st.markdown("---")

    latest_fiscal_year = int(filtered_df["회계연도"].max())
    prev_fiscal_year = latest_fiscal_year - 1

    latest_rows = filtered_df[filtered_df["회계연도"] == latest_fiscal_year]
    latest_year = int(latest_rows["년도"].max())
    latest_month = int(latest_rows[latest_rows["년도"] == latest_year]["월"].max())

    curr_sales = filtered_df[(filtered_df["년도"] == latest_year) & (filtered_df["월"] == latest_month)]["매출금액"].sum()
    prev_sales = filtered_df[(filtered_df["년도"] == latest_year - 1) & (filtered_df["월"] == latest_month)]["매출금액"].sum()

    month_yoy_diff = curr_sales - prev_sales
    month_yoy_rate = (month_yoy_diff / prev_sales * 100) if prev_sales > 0 else 0

    curr_fy_cum_sales = filtered_df[filtered_df["회계연도"] == latest_fiscal_year]["매출금액"].sum()
    prev_fy_cum_sales = filtered_df[filtered_df["회계연도"] == prev_fiscal_year]["매출금액"].sum()

    if user["role"] in ["super_admin", "hq_admin"] and selected_org == "전체":
        target_sales = sum([v for k, v in st.session_state["targets_db"].items() if int(k[1]) == latest_fiscal_year])
    else:
        target_code = user.get("org_code")
        if user["role"] in ["super_admin", "hq_admin"] and selected_org != "전체":
            target_code = filtered_df["기관코드"].iloc[0] if "기관코드" in filtered_df.columns else None

        target_sales = st.session_state["targets_db"].get((target_code, latest_fiscal_year), 0)

    target_diff = curr_fy_cum_sales - target_sales
    achievement_rate = (curr_fy_cum_sales / target_sales * 100) if target_sales > 0 else 0

    fy_yoy_diff = curr_fy_cum_sales - prev_fy_cum_sales
    fy_yoy_rate = (fy_yoy_diff / prev_fy_cum_sales * 100) if prev_fy_cum_sales > 0 else 0

    row1_col1, row1_col2 = st.columns(2)
    with row1_col1:
        st.metric(
            label=f"당월 매출 ({latest_year}년 {latest_month}월)",
            value=f"{curr_sales:,.0f} 원",
            delta=f"{month_yoy_diff:+,.0f} 원 ({month_yoy_rate:+.1f}%)",
        )
    with row1_col2:
        st.metric(
            label=f"전년 동월 매출 ({latest_year-1}년 {latest_month}월)",
            value=f"{prev_sales:,.0f} 원",
        )

    row2_col1, row2_col2 = st.columns(2)
    with row2_col1:
        st.metric(
            label=f"{latest_fiscal_year} 회계연도 누적 매출",
            value=f"{curr_fy_cum_sales:,.0f} 원",
            delta=f"{fy_yoy_diff:+,.0f} 원 ({fy_yoy_rate:+.1f}% 전년 대비)",
        )

        if target_sales > 0:
            if target_diff >= 0:
                diff_str = f"목표 초과: +{target_diff:,.0f}원"
                status_color = "#2e7d32"
            else:
                diff_str = f"목표 미달: {target_diff:,.0f}원"
                status_color = "#d32f2f"

            sub_text = f"🎯 {latest_fiscal_year}년 설정 목표액: <b>{target_sales:,.0f}원</b> | 달성률: <b>{achievement_rate:.1f}%</b> (<span style='color: {status_color}; font-weight: bold;'>{diff_str}</span>)"
        else:
            sub_text = f"🎯 {latest_fiscal_year}년 설정 목표액: <b>미설정 (0원)</b>"

        st.markdown(
            f"""<div style="font-size: 0.85rem; color: #555555; margin-top: -10px;">{sub_text}</div>""",
            unsafe_allow_html=True,
        )

    with row2_col2:
        st.metric(
            label=f"{prev_fiscal_year} 회계연도 누적 매출 (전년 실적)",
            value=f"{prev_fy_cum_sales:,.0f} 원",
        )

    st.markdown("---")

    chart_title_prefix = f"[{selected_org}] " if selected_org != "전체" else (f"[{user['org_name']}] " if user["role"] == "user" else "")
    st.subheader(f"📊 {chart_title_prefix}매출 추이")

    fy_month_order = {12: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 11: 12}
    month_labels = ["12월", "1월", "2월", "3월", "4월", "5월", "6월", "7월", "8월", "9월", "10월", "11월"]
    month_map = {12: "12월", 1: "1월", 2: "2월", 3: "3월", 4: "4월", 5: "5월", 6: "6월", 7: "7월", 8: "8월", 9: "9월", 10: "10월", 11: "11월"}

    chart_df = filtered_df.copy()
    chart_df["월_순서"] = chart_df["월"].map(fy_month_order)
    chart_df["월_라벨"] = chart_df["월"].map(month_map)

    grouped = chart_df.groupby(["회계연도", "년도", "월", "월_순서", "월_라벨"], as_index=False)["매출금액"].sum()
    grouped = grouped.sort_values(by=["회계연도", "월_순서"])

    available_fys = sorted([int(fy) for fy in grouped["회계연도"].unique()], reverse=True)
    comparison_pairs = []
    for i in range(len(available_fys) - 1):
        curr_fy = available_fys[i]
        prev_fy = available_fys[i + 1]
        comparison_pairs.append((curr_fy, prev_fy))

    if comparison_pairs:
        pair_options = [f"{pair[1]}-{pair[0]}년도 비교" for pair in comparison_pairs]
        selected_pair_str = st.selectbox("비교할 회계연도 선택", pair_options)
        selected_idx = pair_options.index(selected_pair_str)
        target_curr_fy, target_prev_fy = comparison_pairs[selected_idx]

        sub_grouped = grouped[grouped["회계연도"].isin([target_curr_fy, target_prev_fy])].copy()

        sub_grouped["tooltip_text"] = ""
        for index, row in sub_grouped.iterrows():
            if row["회계연도"] == target_curr_fy:
                p_row = sub_grouped[(sub_grouped["회계연도"] == target_prev_fy) & (sub_grouped["월"] == row["월"])]
                if not p_row.empty:
                    p_val = p_row["매출금액"].values[0]
                    diff = row["매출금액"] - p_val
                    rate = (diff / p_val * 100) if p_val > 0 else 0
                    rate_sign = "+" if rate >= 0 else ""
                    txt = f"{int(row['년도'])}년 {int(row['월'])}월: {row['매출금액']:,.0f}원 (전년 동월 대비 {diff:+,.0f}원, {rate_sign}{rate:.1f}%)"
                else:
                    txt = f"{int(row['년도'])}년 {int(row['월'])}월: {row['매출금액']:,.0f}원"
            else:
                txt = f"{int(row['년도'])}년 {int(row['월'])}월: {row['매출금액']:,.0f}원"
            sub_grouped.at[index, "tooltip_text"] = txt

        sub_grouped["회계연도_라벨"] = sub_grouped["회계연도"].astype(int).astype(str) + "년도"
        curr_label = f"{target_curr_fy}년도"
        prev_label = f"{target_prev_fy}년도"

        fig = px.line(
            sub_grouped,
            x="월_라벨",
            y="매출금액",
            color="회계연도_라벨",
            markers=True,
            custom_data=["tooltip_text"],
            color_discrete_map={curr_label: "#E53935", prev_label: "#9E9E9E"},
            category_orders={"회계연도_라벨": [curr_label, prev_label]},
        )
        fig.update_traces(hovertemplate="%{customdata[0]}<extra></extra>")

        max_val = sub_grouped["매출금액"].max() if not sub_grouped.empty else 1000
        y_step = max_val / 5 if max_val > 0 else 100
        y_ticks = [i * y_step for i in range(6)]
        y_tick_texts = [format_korean_currency(v) for v in y_ticks]

        fig.update_layout(
            yaxis=dict(title="", tickvals=y_ticks, ticktext=y_tick_texts, range=[0, max_val * 1.35], fixedrange=True),
            xaxis=dict(title="", categoryorder="array", categoryarray=month_labels, tickangle=0, fixedrange=True),
            hovermode="closest",
            legend_title_text="회계연도",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("비교할 회계연도 데이터가 2개 이상 존재하지 않습니다.")

    st.markdown("---")
    st.subheader("🔍 상세 데이터 테이블")

    all_fy_list = sorted([int(fy) for fy in df_raw["회계연도"].unique()], reverse=True)

    if user["role"] in ["super_admin", "hq_admin"] and selected_org == "전체":
        selected_rank_fy = st.selectbox("📅 기준 연도", all_fy_list, index=0, key="rank_table_base_fy")
        prev_rank_fy = selected_rank_fy - 1

        curr_fy_df = df_raw[df_raw["회계연도"] == selected_rank_fy]
        existing_months = curr_fy_df["월"].unique()

        curr_rank_df = curr_fy_df.groupby("기관", as_index=False)["매출금액"].sum().rename(columns={"매출금액": "당해매출"})
        prev_rank_df = df_raw[df_raw["회계연도"] == prev_rank_fy].groupby("기관", as_index=False)["매출금액"].sum().rename(columns={"매출금액": "전년전체매출"})
        prev_same_period_df = df_raw[(df_raw["회계연도"] == prev_rank_fy) & (df_raw["월"].isin(existing_months))].groupby("기관", as_index=False)["매출금액"].sum().rename(columns={"매출금액": "전년동기매출"})

        merged_rank = pd.merge(curr_rank_df, prev_rank_df, on="기관", how="left").fillna({"전년전체매출": 0})
        merged_rank = pd.merge(merged_rank, prev_same_period_df, on="기관", how="left").fillna({"전년동기매출": 0})
        merged_rank = merged_rank.sort_values(by="당해매출", ascending=False).reset_index(drop=True)

        merged_rank["연도"] = f"{selected_rank_fy}년"
        merged_rank["순위"] = merged_rank.index + 1
        
        merged_rank["전년전체_증감액"] = merged_rank["당해매출"] - merged_rank["전년전체매출"]
        merged_rank["전년동기_증감액"] = merged_rank["당해매출"] - merged_rank["전년동기매출"]

        def calc_diff_str(diff):
            if diff > 0: return f"▲ +{diff:,.0f} 원"
            elif diff < 0: return f"▼ {diff:,.0f} 원"
            return "0 원"

        def calc_rate_str(diff, base):
            if base == 0: return "- (신규)"
            rate = (diff / base) * 100
            if rate > 0: return f"▲ +{rate:.1f}%"
            elif rate < 0: return f"▼ {rate:.1f}%"
            return "0.0%"

        merged_rank["전년 전체 대비 증감액"] = merged_rank["전년전체_증감액"].apply(calc_diff_str)
        merged_rank["전년 전체 대비 증감율"] = merged_rank.apply(lambda r: calc_rate_str(r["전년전체_증감액"], r["전년전체매출"]), axis=1)

        merged_rank["전년 동기 대비 증감액"] = merged_rank["전년동기_증감액"].apply(calc_diff_str)
        merged_rank["전년 동기 대비 증감율"] = merged_rank.apply(lambda r: calc_rate_str(r["전년동기_증감액"], r["전년동기매출"]), axis=1)

        merged_rank["당해 누적 매출"] = merged_rank["당해매출"].apply(lambda x: f"{x:,.0f} 원")

        st.caption(f"🏆 **{selected_rank_fy} 회계연도 기관별 누적 매출 순위 (전년 전체 실적 및 전년 동기 누적 비교)**")

        final_rank_df = merged_rank[[
            "연도", "순위", "기관", "당해 누적 매출",
            "전년 동기 대비 증감액", "전년 동기 대비 증감율",
            "전년 전체 대비 증감액", "전년 전체 대비 증감율",
            "전년동기_증감액", "전년전체_증감액"
        ]]

        def style_rank_table(row):
            동기_val = row["전년동기_증감액"]
            전체_val = row["전년전체_증감액"]
            
            styles = ["" for _ in row.index]
            for idx, col in enumerate(row.index):
                if col in ["전년 동기 대비 증감액", "전년 동기 대비 증감율"]:
                    if 동기_val > 0: styles[idx] = "color: #d32f2f; font-weight: bold;"
                    elif 동기_val < 0: styles[idx] = "color: #1976D2; font-weight: bold;"
                elif col in ["전년 전체 대비 증감액", "전년 전체 대비 증감율"]:
                    if 전체_val > 0: styles[idx] = "color: #d32f2f; font-weight: bold;"
                    elif 전체_val < 0: styles[idx] = "color: #1976D2; font-weight: bold;"
            return styles

        styled_rank_df = final_rank_df.style.apply(style_rank_table, axis=1)

        rank_config = {
            "연도": st.column_config.TextColumn("연도", width=70, alignment="center"),
            "순위": st.column_config.NumberColumn("순위", width=50, alignment="center"),
            "기관": st.column_config.TextColumn("기관", width=140, alignment="left"),
            "당해 누적 매출": st.column_config.TextColumn("당해 누적 매출", width=140, alignment="right"),
            "전년 동기 대비 증감액": st.column_config.TextColumn("전년 동기 대비 증감액", width=160, alignment="right"),
            "전년 동기 대비 증감율": st.column_config.TextColumn("전년 동기 대비 증감율", width=120, alignment="right"),
            "전년 전체 대비 증감액": st.column_config.TextColumn("전년 전체 대비 증감액", width=160, alignment="right"),
            "전년 전체 대비 증감율": st.column_config.TextColumn("전년 전체 대비 증감율", width=120, alignment="right"),
            "전년동기_증감액": None,
            "전년전체_증감액": None,
        }

        st.dataframe(styled_rank_df, column_config=rank_config, hide_index=True, use_container_width=False)

        st.markdown("---")
        
        st.subheader("🌐 회계 연도별 전체 매출")
        selected_all_base_fy = st.selectbox("📅 기준 연도 선택", all_fy_list, index=0, key="all_6y_base_fy")
        render_6year_analysis(df_raw, "전체 지사 총합", int(selected_all_base_fy))

        st.markdown("---")
        st.subheader("🏢 연도별 각 지사 매출")

        selected_base_fy = st.selectbox("📅 기준 연도", all_fy_list, index=0, key="detail_analysis_base_fy")
        st.caption(f"선택한 **{selected_base_fy} 회계연도 포함 직전 6개년** 매출 추이 및 전년 대비 증감 현황을 조회합니다.")

        unique_org_list = registered_org_names

        if unique_org_list:
            search_selected = st.selectbox("🔍 지사 검색", ["선택하세요..."] + unique_org_list, key="org_search_box")
            if search_selected != "선택하세요...":
                st.session_state["selected_detail_org"] = search_selected

            st.write("**각 기관 바로가기**")
            cols_per_row = 5
            for i in range(0, len(unique_org_list), cols_per_row):
                cols = st.columns(cols_per_row)
                for j, org_item in enumerate(unique_org_list[i : i + cols_per_row]):
                    with cols[j]:
                        if st.button(f"📌 {org_item}", key=f"btn_org_det_{i+j}", use_container_width=True):
                            st.session_state["selected_detail_org"] = org_item

            target_detail_org = st.session_state.get("selected_detail_org", None)

            if target_detail_org and target_detail_org in unique_org_list:
                st.markdown("<br>", unsafe_allow_html=True)
                render_6year_analysis(df_raw, target_detail_org, int(selected_base_fy))

    else:
        current_org_title = selected_org if selected_org != "전체" else user["org_name"]
        st.caption(f"📅 **[{current_org_title}] {latest_fiscal_year} 회계연도 월별 상세 및 전년 동월/동기 누적 비교**")

        curr_org_df = filtered_df[filtered_df["회계연도"] == latest_fiscal_year].sort_values(by=["년도", "월"]).copy()
        prev_org_df = filtered_df[filtered_df["회계연도"] == (latest_fiscal_year - 1)].copy()

        fy_month_order = {12: 1, 1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7, 7: 8, 8: 9, 9: 10, 10: 11, 11: 12}
        curr_org_df["월_순서"] = curr_org_df["월"].map(fy_month_order)
        curr_org_df = curr_org_df.sort_values(by="월_순서")

        results = []
        cum_curr = 0
        cum_prev = 0

        for _, row in curr_org_df.iterrows():
            m = int(row["월"])
            c_val = row["매출금액"]
            cum_curr += c_val

            p_match = prev_org_df[prev_org_df["월"] == m]
            p_val = p_match["매출금액"].values[0] if not p_match.empty else 0
            cum_prev += p_val

            m_diff = c_val - p_val
            m_rate = (m_diff / p_val * 100) if p_val > 0 else 0

            cum_diff = cum_curr - cum_prev
            cum_rate = (cum_diff / cum_prev * 100) if cum_prev > 0 else 0

            def fmt_diff_str(diff):
                if diff > 0: return f"▲ +{diff:,.0f} 원"
                elif diff < 0: return f"▼ {diff:,.0f} 원"
                return "0 원"

            def fmt_rate_str(rate):
                if rate > 0: return f"▲ +{rate:.1f}%"
                elif rate < 0: return f"▼ {rate:.1f}%"
                return "0.0%"

            results.append({
                "년도": int(row["년도"]),
                "월": int(row["월"]),
                "당월 매출": f"{c_val:,.0f} 원",
                "전년 동월 대비 증감액": fmt_diff_str(m_diff),
                "전년 동월 대비 증감율": fmt_rate_str(m_rate),
                "전년 동월 매출": f"{p_val:,.0f} 원",
                "당해 누적 매출": f"{cum_curr:,.0f} 원",
                "전년 동기 누적 대비 증감액": fmt_diff_str(cum_diff),
                "전년 동기 누적 대비 증감율": fmt_rate_str(cum_rate),
                "전년 동기 누적": f"{cum_prev:,.0f} 원",
                "m_diff": m_diff,
                "cum_diff": cum_diff
            })

        display_indiv_df = pd.DataFrame(results)

        ordered_cols = [
            "년도", "월", "당월 매출", 
            "전년 동월 대비 증감액", "전년 동월 대비 증감율", "전년 동월 매출", 
            "당해 누적 매출", 
            "전년 동기 누적 대비 증감액", "전년 동기 누적 대비 증감율", "전년 동기 누적",
            "m_diff", "cum_diff"
        ]
        display_indiv_df = display_indiv_df[ordered_cols]

        def style_indiv_table(row):
            m_diff_val = row["m_diff"]
            cum_diff_val = row["cum_diff"]
            styles = ["" for _ in row.index]
            
            m_color = ""
            if m_diff_val > 0: m_color = "color: #d32f2f; font-weight: bold;"
            elif m_diff_val < 0: m_color = "color: #1976D2; font-weight: bold;"

            cum_color = ""
            if cum_diff_val > 0: cum_color = "color: #d32f2f; font-weight: bold;"
            elif cum_diff_val < 0: cum_color = "color: #1976D2; font-weight: bold;"

            for idx, col in enumerate(row.index):
                if col in ["당월 매출", "전년 동월 대비 증감액", "전년 동월 대비 증감율"]:
                    styles[idx] = m_color
                elif col in ["당해 누적 매출", "전년 동기 누적 대비 증감액", "전년 동기 누적 대비 증감율"]:
                    styles[idx] = cum_color
                elif col in ["전년 동월 매출", "전년 동기 누적"]:
                    styles[idx] = "color: #000000;"

            return styles

        styled_indiv_df = display_indiv_df.style.apply(style_indiv_table, axis=1)

        indiv_config = {
            "년도": st.column_config.NumberColumn("년도", width=65, alignment="center", format="%d"),
            "월": st.column_config.NumberColumn("월", width=45, alignment="center", format="%d"),
            "당월 매출": st.column_config.TextColumn("당월 매출", width=120, alignment="right"),
            "전년 동월 대비 증감액": st.column_config.TextColumn("전년 동월 대비 증감액", width=150, alignment="right"),
            "전년 동월 대비 증감율": st.column_config.TextColumn("전년 동월 대비 증감율", width=120, alignment="right"),
            "전년 동월 매출": st.column_config.TextColumn("전년 동월 매출", width=120, alignment="right"),
            "당해 누적 매출": st.column_config.TextColumn("당해 누적 매출", width=130, alignment="right"),
            "전년 동기 누적 대비 증감액": st.column_config.TextColumn("전년 동기 누적 대비 증감액", width=160, alignment="right"),
            "전년 동기 누적 대비 증감율": st.column_config.TextColumn("전년 동기 대비 증감율", width=120, alignment="right"),
            "전년 동기 누적": st.column_config.TextColumn("전년 동기 누적", width=130, alignment="right"),
            "m_diff": None,
            "cum_diff": None,
        }

        st.dataframe(styled_indiv_df, column_config=indiv_config, hide_index=True, use_container_width=False)

        st.markdown("---")
        st.subheader("📅 최근 6개년 연도별 매출 추이")
        selected_user_base_fy = st.selectbox("📅 기준 연도 선택", all_fy_list, index=0, key="user_6y_base_fy")
        render_6year_analysis(filtered_df, current_org_title, int(selected_user_base_fy))


# -----------------------------------------------------------------------------
# 10. 공통 최근 6개년 매출 분석 렌더링 함수
# -----------------------------------------------------------------------------
def render_6year_analysis(df_target_source, org_title, base_fy):
    base_fy = int(base_fy)
    six_years = list(range(base_fy - 5, base_fy + 1))
    st.info(f"📊 **[{org_title}] {six_years[0]}년 ~ {six_years[-1]}년 (6개년) 연도별 매출 상세 분석**")

    if org_title == "전체 지사 총합":
        org_6y_df = df_target_source[df_target_source["회계연도"].isin(six_years)].copy()
    else:
        org_6y_df = df_target_source[(df_target_source["기관"] == org_title) if "기관" in df_target_source.columns else df_target_source["회계연도"].isin(six_years)].copy()
        org_6y_df = org_6y_df[org_6y_df["회계연도"].isin(six_years)]
    
    summary_6y = org_6y_df.groupby("회계연도", as_index=False)["매출금액"].sum()
    summary_6y["회계연도"] = summary_6y["회계연도"].astype(int)
    summary_6y = pd.merge(pd.DataFrame({"회계연도": six_years}), summary_6y, on="회계연도", how="left").fillna({"매출금액": 0}).sort_values(by="회계연도").reset_index(drop=True)

    if not summary_6y.empty:
        summary_6y["전년매출"] = summary_6y["매출금액"].shift(1).fillna(0)
        summary_6y["증감액"] = summary_6y["매출금액"] - summary_6y["전년매출"]

        def calc_yoy_rate(row):
            if row["전년매출"] == 0: return None
            return ((row["매출금액"] - row["전년매출"]) / row["전년매출"]) * 100

        summary_6y["증감율_num"] = summary_6y.apply(calc_yoy_rate, axis=1)
        summary_6y["회계연도_라벨"] = summary_6y["회계연도"].astype(int).astype(str) + "년도"
        summary_6y["tooltip"] = [f"<b>{int(row['회계연도'])}년</b>: {row['매출금액']:,.0f}원" for _, row in summary_6y.iterrows()]

        fig_6y = px.line(summary_6y, x="회계연도_라벨", y="매출금액", markers=True, title=f"[{org_title}] 최근 6개년 ({six_years[0]}~{six_years[-1]}년) 매출 추이", custom_data=["tooltip"])
        fig_6y.update_traces(line=dict(color="#1976D2", width=3), marker=dict(size=9, color="#0D47A1"), hovertemplate="%{customdata[0]}<extra></extra>")

        max_6y_val = summary_6y["매출금액"].max()
        y_step_6y = max_6y_val / 5 if max_6y_val > 0 else 100
        y_ticks_6y = [k * y_step_6y for k in range(6)]
        y_tick_texts_6y = [format_korean_currency(v) for v in y_ticks_6y]

        fig_6y.update_layout(
            yaxis=dict(title="", tickvals=y_ticks_6y, ticktext=y_tick_texts_6y, range=[0, max_6y_val * 1.4] if max_6y_val > 0 else [0, 1000], fixedrange=True),
            xaxis=dict(title="", fixedrange=True),
        )
        st.plotly_chart(fig_6y, use_container_width=True)

        table_6y = summary_6y.sort_values(by="회계연도", ascending=False).copy()
        table_6y["구분"] = table_6y["회계연도"].astype(int).astype(str) + " 회계연도"
        table_6y["매출금액(원)"] = table_6y["매출금액"].apply(lambda x: f"{x:,.0f} 원")

        def fmt_diff_6y(val, rate):
            if pd.isna(rate): return "-"
            if val > 0: return f"▲ +{val:,.0f} 원"
            elif val < 0: return f"▼ {val:,.0f} 원"
            return "0 원"

        def fmt_rate_6y(rate):
            if pd.isna(rate): return "-"
            if rate > 0: return f"▲ +{rate:.1f}%"
            elif rate < 0: return f"▼ {rate:.1f}%"
            return "0.0%"

        table_6y["전년도 대비 증감액"] = table_6y.apply(lambda r: fmt_diff_6y(r["증감액"], r["증감율_num"]), axis=1)
        table_6y["전년도 대비 증감율"] = table_6y["증감율_num"].apply(fmt_rate_6y)

        display_6y_df = table_6y[["구분", "매출금액(원)", "전년도 대비 증감액", "전년도 대비 증감율", "증감액"]]

        def style_6y_table(row):
            val = row["증감액"]
            color_style = ""
            if pd.notna(val) and val > 0: color_style = "color: #d32f2f; font-weight: bold;"
            elif pd.notna(val) and val < 0: color_style = "color: #1976D2; font-weight: bold;"
            return ["" if col == "구분" else color_style for col in row.index]

        styled_6y_df = display_6y_df.style.apply(style_6y_table, axis=1)

        config_6y = {
            "구분": st.column_config.TextColumn("구분", width=140, alignment="center"),
            "매출금액(원)": st.column_config.TextColumn("매출금액(원)", width=160, alignment="right"),
            "전년도 대비 증감액": st.column_config.TextColumn("전년도 대비 증감액", width=170, alignment="right"),
            "전년도 대비 증감율": st.column_config.TextColumn("전년도 대비 증감율", width=120, alignment="right"),
            "증감액": None,
        }

        st.dataframe(styled_6y_df, column_config=config_6y, hide_index=True, use_container_width=False)
    else:
        st.warning("해당 기간의 매출 데이터가 존재하지 않습니다.")


if __name__ == "__main__":
    if not st.session_state["logged_in"]:
        login_screen()
    else:
        main_dashboard()