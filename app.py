import io
import os
import pandas as pd
import numpy as np
import plotly.express as px
import streamlit as st
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 0. 데이터 영구 저장 및 구글 시트 연동 유틸리티
# ==========================================
SALES_FILE_PATH = "sales_data.csv"

# Google Sheets 연결 객체 생성
conn = st.connection("gsheets", type=GSheetsConnection)

DEFAULT_ORGS = {}

def load_sales_data():
    """Google Sheets의 sales 워크시트에서 매출 데이터를 실시간(ttl=0)으로 불러옵니다."""
    try:
        sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
        df_sales = conn.read(spreadsheet=sheet_url, worksheet="sales", ttl=0) if sheet_url else conn.read(worksheet="sales", ttl=0)
        
        if df_sales is None or df_sales.empty or "매출금액" not in df_sales.columns:
            return pd.DataFrame(columns=["년도", "월", "기관코드", "기관", "매출금액"])
            
        return df_sales
    except Exception as e:
        if os.path.exists(SALES_FILE_PATH):
            return pd.read_csv(SALES_FILE_PATH)
        return pd.DataFrame(columns=["년도", "월", "기관코드", "기관", "매출금액"])

def load_persistent_db():
    """Google Sheets에서 계정(users), 기관 DB, 목표 매출(targets)을 실시간(ttl=0)으로 읽어옵니다."""
    users = {}
    orgs = DEFAULT_ORGS.copy()
    targets = {}

    try:
        sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
        
        # 1. users 시트 읽기
        df_users = conn.read(spreadsheet=sheet_url, worksheet="users", ttl=0) if sheet_url else conn.read(worksheet="users", ttl=0)
        
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

        # 2. targets 시트 읽기
        df_targets = conn.read(spreadsheet=sheet_url, worksheet="targets", ttl=0) if sheet_url else conn.read(worksheet="targets", ttl=0)
        
        if df_targets is not None and not df_targets.empty:
            df_targets = df_targets.fillna(0)
            for _, row in df_targets.iterrows():
                try:
                    t_year = int(row.get("year", 0))
                    t_code = str(row.get("org_code", "")).strip()
                    t_amt = int(row.get("target_amount", 0))
                    if t_code and t_year > 0:
                        targets[(t_code, t_year)] = t_amt
                except Exception:
                    continue

    except Exception as e:
        st.warning(f"⚠️ Google Sheets 데이터를 불러오는 중 오류 발생: {e}")

    if "admin" not in users:
        users["admin"] = {
            "password": "adminpassword",
            "role": "super_admin",
            "org_code": "ALL",
            "org_name": "전체(총 관리자)",
        }

    return orgs, users, targets

def save_sales_data(df):
    """매출 데이터를 백업용 로컬 CSV 저장과 동시에 Google Sheets 'sales' 워크시트에 업데이트합니다."""
    if df is not None:
        df.to_csv(SALES_FILE_PATH, index=False, encoding="utf-8-sig")
        try:
            sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
            conn.update(spreadsheet=sheet_url, worksheet="sales", data=df)
            st.toast("✅ Google Sheets에 매출 데이터가 저장되었습니다!", icon="💾")
        except Exception as e:
            st.error(f"⚠️ Google Sheets 매출 데이터 저장 중 오류 발생: {e}")

def save_targets_data(targets_dict):
    """목표 매출(targets) 정보 딕셔너리를 Google Sheets 'targets' 시트에 업데이트합니다."""
    rows = []
    for (code, year), amt in targets_dict.items():
        rows.append({"year": year, "org_code": code, "target_amount": amt})
    df_targets = pd.DataFrame(rows)
    try:
        sheet_url = st.secrets["connections"]["gsheets"].get("spreadsheet")
        conn.update(spreadsheet=sheet_url, worksheet="targets", data=df_targets)
        st.toast("✅ Google Sheets에 목표 매출 데이터가 안전하게 저장되었습니다!", icon="🎯")
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
st.set_page_config(page_title="인싸이트 지사 매출 확인", page_icon="📊", layout="wide")

st.markdown(
    """
    <style>
    div[data-testid="stSelectbox"] { max-width: 220px !important; }
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
                    st.info("💡 본사 관리자 권한으로는 일반 지사 회원 계정만 생성할 수 있습니다.")
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
                    target_role = "super_admin" if role_type == "👑 총 관리자" else ("hq_admin" if role_type == "🏢 본사 관리자" else "user")
                    
                    if target_role == "user":
                        st.session_state["orgs_db"][new_org_code] = {"org_name": new_org_name}
                    
                    st.session_state["user_db"][new_id] = {
                        "password": new_pw,
                        "role": target_role,
                        "org_code": new_org_code,
                    }
                    
                    st.success(f"🎉 계정('{new_id}')이 성공적으로 생성되었습니다.")
                    st.rerun()

    with tab_edit_user:
        st.subheader("계정 ID 및 비밀번호 수정")
        user_ids = list(st.session_state["user_db"].keys()) if current_role == "super_admin" else [
            uid for uid, uinfo in st.session_state["user_db"].items() if uinfo.get("role") == "user"
        ]

        if not user_ids:
            st.info("수정 가능한 계정이 없습니다.")
        else:
            selected_user = st.selectbox("수정할 계정 선택", user_ids)
            curr_user_info = st.session_state["user_db"][selected_user]

            edit_form_col, _ = st.columns([5.5, 4.5])
            with edit_form_col:
                with st.form("edit_user_form"):
                    c_id, c_pw = st.columns(2)
                    with c_id:
                        new_user_id = st.text_input("변경할 아이디 (ID)", value=selected_user)
                    with c_pw:
                        new_user_pw = st.text_input("변경할 비밀번호 (Password)", value=curr_user_info["password"])
                    
                    submit_user_edit = st.form_submit_button("계정 정보 변경 저장", use_container_width=True)

                if submit_user_edit:
                    new_id_clean = new_user_id.strip()
                    if not new_id_clean or not new_user_pw.strip():
                        st.warning("아이디와 비밀번호를 입력해 주세요.")
                    else:
                        info = st.session_state["user_db"].pop(selected_user)
                        info["password"] = new_user_pw.strip()
                        st.session_state["user_db"][new_id_clean] = info

                        if st.session_state["user_info"]["username"] == selected_user:
                            st.session_state["user_info"]["username"] = new_id_clean

                        st.success(f"계정 정보가 성공적으로 변경되었습니다. (ID: **{new_id_clean}**)")
                        st.rerun()

    with tab_edit_org:
        st.subheader("기관명 변경")
        org_codes = list(st.session_state["orgs_db"].keys())
        if org_codes:
            selected_code = st.selectbox("명칭을 변경할 기관 선택", org_codes, format_func=lambda x: f"[{x}] {st.session_state['orgs_db'][x]['org_name']}")
            current_name = st.session_state["orgs_db"][selected_code]["org_name"]

            org_edit_col, _ = st.columns([5.5, 4.5])
            with org_edit_col:
                with st.form("edit_org_form"):
                    updated_name = st.text_input("새로운 기관명 입력", value=current_name)
                    submit_edit = st.form_submit_button("기관명 수정 반영", use_container_width=True)

                if submit_edit and updated_name.strip():
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

                    st.success(f"기관명이 **'{new_name_clean}'**(으)로 변경되었습니다.")
                    st.rerun()

    with tab_delete_user:
        st.subheader("계정 삭제")
        deletable_users = list(st.session_state["user_db"].keys()) if current_role == "super_admin" else [
            uid for uid, uinfo in st.session_state["user_db"].items() if uinfo.get("role") == "user"
        ]

        if deletable_users:
            selected_del_user = st.selectbox("삭제할 계정 선택", deletable_users)
            if selected_del_user == st.session_state["user_info"]["username"]:
                st.error("⚠️ 현재 로그인 중인 계정은 삭제할 수 없습니다.")
            else:
                if st.button("🚨 해당 계정 삭제", type="primary"):
                    st.session_state["user_db"].pop(selected_del_user)
                    st.success(f"계정 **'{selected_del_user}'** 이(가) 삭제되었습니다.")
                    st.rerun()


# -----------------------------------------------------------------------------
# 6. 기관 관리 화면
# -----------------------------------------------------------------------------
def admin_organization_page():
    st.title("🏢 기관 관리")
    st.markdown("---")
    
    current_role = st.session_state["user_info"]["role"]
    user_list = []
    
    for uid, uinfo in st.session_state["user_db"].items():
        role = uinfo["role"]
        if current_role == "hq_admin" and role != "user":
            continue

        org_display = "전체(총 관리자)" if role == "super_admin" else ("전체(본사 관리자)" if role == "hq_admin" else st.session_state["orgs_db"].get(uinfo["org_code"], {}).get("org_name", "미지정"))
        user_list.append({
            "아이디": uid,
            "비밀번호": uinfo["password"],
            "권한": role,
            "고유 코드": uinfo["org_code"],
            "매칭된 기관명": org_display,
        })
        
    st.dataframe(pd.DataFrame(user_list), hide_index=True, use_container_width=False)


# -----------------------------------------------------------------------------
# 7. Target 설정 (구글 시트 'targets' 연동)
# -----------------------------------------------------------------------------
def admin_target_page():
    st.title("🎯 지사 목표 매출 등록 (Google Sheets 연동)")
    st.markdown("---")

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

                st.session_state["targets_db"][(code, selected_fy)] = final_amount
                # Google Sheets 저장 호출
                save_targets_data(st.session_state["targets_db"])


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
            uploaded_file = st.file_uploader("매출 데이터 엑셀/CSV 파일 업로드", type=["xlsx", "csv"])

            if uploaded_file is not None:
                try:
                    new_df = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)

                    if "기관코드" not in new_df.columns:
                        for code_col in ["지사코드", "고유코드", "code", "org_code"]:
                            if code_col in new_df.columns:
                                new_df.rename(columns={code_col: "기관코드"}, inplace=True)
                                break

                    orgs_db = st.session_state["orgs_db"]
                    if "기관코드" in new_df.columns:
                        new_df["기관코드"] = new_df["기관코드"].astype(str).str.strip()
                        new_df["기관"] = new_df["기관코드"].apply(lambda code: orgs_db.get(code, {}).get("org_name", f"미등록지사({code})"))

                    group_cols = [col for col in ["년도", "월", "기관코드", "기관"] if col in new_df.columns]
                    new_df = new_df.groupby(group_cols, as_index=False)["매출금액"].sum()

                    curr_acc = st.session_state["df_accumulated"]
                    merged_df = new_df if curr_acc is None or curr_acc.empty else pd.concat([curr_acc, new_df], ignore_index=True).groupby(group_cols, as_index=False)["매출금액"].sum()

                    st.session_state["df_accumulated"] = merged_df
                    save_sales_data(merged_df)
                    st.success(f"🎉 데이터 업로드 완료! Google Sheets에 반영되었습니다.")
                except Exception as e:
                    st.error(f"파일을 읽는 도중 오류가 발생했습니다: {e}")

    with tab_download:
        st.subheader("📥 선택 기간/기관 매출 데이터 엑셀 추출")
        df_acc = st.session_state["df_accumulated"]

        if df_acc is not None and not df_acc.empty:
            df_acc_calc = df_acc.copy()
            df_acc_calc["period_key"] = df_acc_calc["년도"] * 100 + df_acc_calc["월"]

            all_years = sorted(list(df_acc["년도"].unique()))
            all_months = list(range(1, 13))
            all_orgs = ["전체"] + sorted(list(df_acc["기관"].unique()))

            col_d1, col_d2, col_d3, col_d4 = st.columns(4)
            with col_d1: start_year = st.selectbox("시작 년도", all_years, index=0)
            with col_d2: start_month = st.selectbox("시작 월", all_months, index=0)
            with col_d3: end_year = st.selectbox("종료 년도", all_years, index=len(all_years) - 1)
            with col_d4: end_month = st.selectbox("종료 월", all_months, index=11)

            selected_dl_org = st.selectbox("기관 선택", all_orgs, index=0)

            start_key = start_year * 100 + start_month
            end_key = end_year * 100 + end_month

            if start_key <= end_key:
                filtered_dl_df = df_acc_calc[(df_acc_calc["period_key"] >= start_key) & (df_acc_calc["period_key"] <= end_key)]
                if selected_dl_org != "전체":
                    filtered_dl_df = filtered_dl_df[filtered_dl_df["기관"] == selected_dl_org]

                output_cols = [col for col in ["년도", "월", "기관코드", "기관", "매출금액"] if col in filtered_dl_df.columns]
                final_export_df = filtered_dl_df[output_cols].sort_values(by=["년도", "월"]).reset_index(drop=True)

                buffer = io.BytesIO()
                with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
                    final_export_df.to_excel(writer, index=False, sheet_name="매출데이터")
                
                st.download_button(
                    label="📥 선택 조건 엑셀 파일 다운로드",
                    data=buffer.getvalue(),
                    file_name=f"매출데이터_{selected_dl_org}_{start_year}_{end_year}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )


# -----------------------------------------------------------------------------
# 9. 메인 대시보드 화면 및 앱 제어
# -----------------------------------------------------------------------------
def main_dashboard():
    user = st.session_state["user_info"]

    with st.sidebar:
        st.title("👤 접속 정보")
        st.write(f"**사용자:** {user['username']}")
        st.write(f"**소속 기관:** {user['org_name']}")

        if st.button("로그아웃", use_container_width=True):
            st.session_state["logged_in"] = False
            st.session_state["user_info"] = None
            st.rerun()

        st.markdown("<br><hr><br>", unsafe_allow_html=True)

        menu_selection = "📈 매출 분석 대시보드"
        if user["role"] in ["super_admin", "hq_admin"]:
            st.subheader("⚙️ 관리자 메뉴")
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

            menu_selection = st.radio("메뉴 이동", admin_menu_options, label_visibility="collapsed")

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

    # 대시보드 진입 시 구글 시트에서 최신 매출 데이터 동기화
    df_raw = load_sales_data()
    st.session_state["df_accumulated"] = df_raw

    if df_raw is None or df_raw.empty:
        st.info("등록된 매출 데이터가 없습니다. 엑셀을 업로드해 주세요.")
        return

    df_raw = df_raw.copy()
    df_raw["회계연도"] = df_raw.apply(lambda row: row["년도"] + 1 if row["월"] == 12 else row["년도"], axis=1)

    render_dashboard_content(df_raw, user)


def render_dashboard_content(df_raw, user):
    st.title("📈 매출 분석 대시보드")
    registered_org_names = sorted([info["org_name"] for info in st.session_state["orgs_db"].values()])

    if user["role"] in ["super_admin", "hq_admin"]:
        all_orgs = ["전체"] + registered_org_names
        selected_org = st.selectbox("조회할 기관 선택", all_orgs)
        filtered_df = df_raw if selected_org == "전체" else df_raw[df_raw["기관"] == selected_org]
    else:
        selected_org = user["org_name"]
        filtered_df = df_raw[df_raw["기관코드"].astype(str).str.strip() == str(user["org_code"]).strip()].copy() if "기관코드" in df_raw.columns else df_raw[df_raw["기관"] == user["org_name"]]

    if filtered_df.empty:
        st.warning("등록된 매출 데이터가 없습니다.")
        return

    latest_fiscal_year = filtered_df["회계연도"].max()
    curr_fy_cum_sales = filtered_df[filtered_df["회계연도"] == latest_fiscal_year]["매출금액"].sum()

    st.metric(label=f"{latest_fiscal_year} 회계연도 누적 매출", value=f"{curr_fy_cum_sales:,.0f} 원")

    # 최근 6개년 그래프
    st.markdown("---")
    render_6year_analysis(filtered_df, selected_org, latest_fiscal_year)


def render_6year_analysis(df_target_source, org_title, base_fy):
    six_years = list(range(base_fy - 5, base_fy + 1))
    org_6y_df = df_target_source[df_target_source["회계연도"].isin(six_years)].copy()
    summary_6y = org_6y_df.groupby("회계연도", as_index=False)["매출금액"].sum()
    summary_6y = pd.merge(pd.DataFrame({"회계연도": six_years}), summary_6y, on="회계연도", how="left").fillna({"매출금액": 0})

    fig_6y = px.line(summary_6y, x="회계연도", y="매출금액", markers=True, title=f" 최근 6개년 ({six_years[0]}~{six_years[-1]}년) 매출 추이")
    st.plotly_chart(fig_6y, use_container_width=True)


if __name__ == "__main__":
    if not st.session_state["logged_in"]:
        login_screen()
    else:
        main_dashboard()