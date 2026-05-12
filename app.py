import json
import os
import sqlite3
from datetime import datetime

import pandas as pd
import streamlit as st


DATA_DIR = "data"
CSV_RECORD_FILE = os.path.join(DATA_DIR, "customer_records.csv")
DB_FILE = os.path.join(DATA_DIR, "customer_records.db")
ADMIN_CODE = "csair123"


def init_session_state():
    defaults = {
        "page": "home",
        "identity": "未选择",
        "step": 1,
        "answers": {},
        "result": None,
        "saved": False,
        "admin_authenticated": False,
        "pending_delete_index": None,
        "pending_delete_label": "",
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go_home():
    st.session_state.page = "home"
    st.session_state.identity = "未选择"


def go_next():
    st.session_state.step = min(6, st.session_state.step + 1)


def go_back():
    st.session_state.step = max(1, st.session_state.step - 1)


def reset_form():
    form_keys = [
        "contact_name", "phone", "organization", "role", "city", "customer_type",
        "org_size", "existing_channel", "reach_ability", "platforms",
        "travel_types", "ticketing_scenario", "demand_sources", "fixed_plan", "travel_frequency", "single_trip_people", "annual_trips",
        "departure_city", "arrival_cities", "route_need", "route_detail", "time_preferences", "group_travel",
        "rights_focus", "compliance_support", "data_reconciliation", "proof_materials",
        "cooperation_goal", "start_time", "remarks", "analysis_agreement", "admin_code_input",
    ]
    for key in form_keys:
        st.session_state.pop(key, None)
    st.session_state.answers = {}
    st.session_state.result = None
    st.session_state.saved = False
    st.session_state.step = 1
    st.session_state.page = "customer_form"
    st.session_state.identity = "合作客户"


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def parse_json_field(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if not str(value).strip():
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def build_record_row(answers: dict, result: dict):
    return {
        "submit_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "contact_name": answers.get("contact_name", ""),
        "phone": answers.get("phone", ""),
        "organization": answers.get("organization", ""),
        "role": answers.get("role", ""),
        "city": answers.get("city", ""),
        "customer_type": answers.get("customer_type", ""),
        "score": result.get("score", 0),
        "match_level": result.get("match_level", ""),
        "customer_segment": result.get("customer_segment", ""),
        "recommended_policy": result.get("recommended_policy", ""),
        "tags_json": json.dumps(result.get("tags", []), ensure_ascii=False),
        "reason_json": json.dumps(result.get("reason", []), ensure_ascii=False),
        "risk_notes_json": json.dumps(result.get("risk_notes", []), ensure_ascii=False),
        "next_actions_json": json.dumps(result.get("next_actions", []), ensure_ascii=False),
        "score_detail_json": json.dumps(result.get("score_detail", {}), ensure_ascii=False),
        "all_answers_json": json.dumps(answers, ensure_ascii=False),
    }


def init_database():
    ensure_data_dir()
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS customer_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                submit_time TEXT,
                contact_name TEXT,
                phone TEXT,
                organization TEXT,
                role TEXT,
                city TEXT,
                customer_type TEXT,
                score INTEGER,
                match_level TEXT,
                customer_segment TEXT,
                recommended_policy TEXT,
                tags_json TEXT,
                reason_json TEXT,
                risk_notes_json TEXT,
                next_actions_json TEXT,
                score_detail_json TEXT,
                all_answers_json TEXT
            )
            """
        )
        conn.commit()
    migrate_csv_to_database()


def migrate_csv_to_database():
    if not os.path.exists(CSV_RECORD_FILE):
        return
    marker_file = os.path.join(DATA_DIR, ".csv_migrated_to_sqlite")
    if os.path.exists(marker_file):
        return
    try:
        csv_df = pd.read_csv(CSV_RECORD_FILE, encoding="utf-8-sig").fillna("")
        if csv_df.empty:
            open(marker_file, "w", encoding="utf-8").close()
            return

        expected_columns = [
            "submit_time", "contact_name", "phone", "organization", "role", "city",
            "customer_type", "score", "match_level", "customer_segment", "recommended_policy",
            "tags_json", "reason_json", "risk_notes_json", "next_actions_json",
            "score_detail_json", "all_answers_json",
        ]
        for col in expected_columns:
            if col not in csv_df.columns:
                csv_df[col] = ""

        with sqlite3.connect(DB_FILE) as conn:
            existing_count = conn.execute("SELECT COUNT(*) FROM customer_records").fetchone()[0]
            if existing_count == 0:
                csv_df[expected_columns].to_sql("customer_records", conn, if_exists="append", index=False)
                conn.commit()
        open(marker_file, "w", encoding="utf-8").close()
    except Exception:
        pass


def save_record(answers: dict, result: dict):
    init_database()
    row = build_record_row(answers, result)
    columns = list(row.keys())
    placeholders = ",".join(["?"] * len(columns))
    with sqlite3.connect(DB_FILE) as conn:
        conn.execute(
            f"INSERT INTO customer_records ({','.join(columns)}) VALUES ({placeholders})",
            [row[col] for col in columns],
        )
        conn.commit()


def load_records() -> pd.DataFrame:
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            return pd.read_sql_query(
                "SELECT * FROM customer_records ORDER BY id DESC",
                conn,
            ).fillna("")
    except Exception:
        return pd.DataFrame()


def records_to_download_csv(df):
    export_df = df.drop(columns=["id"], errors="ignore")
    return export_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")


def delete_record_by_id(record_id):
    init_database()
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cur = conn.execute("DELETE FROM customer_records WHERE id = ?", (int(record_id),))
            conn.commit()
            return cur.rowcount > 0
    except Exception:
        return False


def evaluate_customer_profile(answers: dict) -> dict:
    score_detail = {
        "组织稳定性": 0,
        "出行需求明确度": 0,
        "政策适配度": 0,
        "渠道合作潜力": 0,
        "合规与落地条件": 0,
    }
    tags = []
    reasons = []
    risk_notes = []

    customer_type = answers.get("customer_type", "")
    org_size = answers.get("org_size", "")
    reach_ability = answers.get("reach_ability", "")
    platforms = answers.get("platforms", []) or []
    travel_types = answers.get("travel_types", []) or []
    ticketing_scenario = answers.get("ticketing_scenario", "")
    demand_sources = answers.get("demand_sources", []) or []
    fixed_plan = answers.get("fixed_plan", "")
    travel_frequency = answers.get("travel_frequency", "")
    annual_trips = int(answers.get("annual_trips") or 0)
    route_need = answers.get("route_need", "")
    route_detail = answers.get("route_detail", "")
    group_travel = answers.get("group_travel", "")
    rights_focus = answers.get("rights_focus", []) or []
    compliance_support = answers.get("compliance_support", "")
    data_reconciliation = answers.get("data_reconciliation", "")
    proof_materials = answers.get("proof_materials", "")
    start_time = answers.get("start_time", "")

    score_detail["组织稳定性"] += {
        "50人以下": 3,
        "50-200人": 6,
        "200-1000人": 9,
        "1000人以上": 12,
    }.get(org_size, 0)
    if reach_ability == "能够统一通知和组织成员":
        score_detail["组织稳定性"] += 5
        tags.append("组织触达能力强")
        reasons.append("具备统一组织和触达成员的能力。")
    elif reach_ability == "能够部分触达成员":
        score_detail["组织稳定性"] += 3
        tags.append("具备部分触达能力")
    if [p for p in platforms if p != "暂无"]:
        score_detail["组织稳定性"] += 3
        tags.append("已有触达渠道")
        reasons.append("已具备社群、会员系统或内部平台等成员触达基础。")
    score_detail["组织稳定性"] = min(20, score_detail["组织稳定性"])

    if fixed_plan == "有明确固定行程":
        score_detail["出行需求明确度"] += 7
        tags.append("行程明确")
        reasons.append("已体现明确或可验证的出行计划。")
    elif fixed_plan == "有年度 / 季度计划但日期未定":
        score_detail["出行需求明确度"] += 5
        tags.append("计划型需求")
    elif fixed_plan == "出行不固定但频率较高":
        score_detail["出行需求明确度"] += 4
    if annual_trips >= 5000:
        score_detail["出行需求明确度"] += 7
        tags.append("高年度出行规模")
    elif annual_trips >= 1000:
        score_detail["出行需求明确度"] += 5
        tags.append("中高年度出行规模")
    elif annual_trips >= 200:
        score_detail["出行需求明确度"] += 3
    elif annual_trips > 0:
        score_detail["出行需求明确度"] += 1
    score_detail["出行需求明确度"] += {
        "每周多次": 6,
        "每月多次": 5,
        "每季度多次": 3,
        "每年数次": 2,
        "不确定": 0,
    }.get(travel_frequency, 0)
    if route_need == "有，非常明确":
        score_detail["出行需求明确度"] += 5
        tags.append("重点航线明确")
        if route_detail:
            reasons.append("客户已补充重点航线或方向，有助于进一步核实航线资源与出行计划。")
    elif route_need == "有大致方向":
        score_detail["出行需求明确度"] += 3
        if route_detail:
            tags.append("航线方向已补充")
    score_detail["出行需求明确度"] = min(25, score_detail["出行需求明确度"])

    cooperation_travel_types = ["公务差旅", "商务拜访", "会议会展", "团队活动", "学术交流"]
    matched_travel = [item for item in travel_types if item in cooperation_travel_types]
    score_detail["政策适配度"] += min(8, len(matched_travel) * 2)
    if matched_travel:
        tags.append("合作型出行需求")
        reasons.append("出行场景与渠道合作、团队服务或差旅支持有较高关联。")
    cooperation_rights = ["票价优惠", "改退签灵活性", "团队票支持", "数据统计 / 对账支持", "专属客户经理"]
    matched_rights = [item for item in rights_focus if item in cooperation_rights]
    score_detail["政策适配度"] += min(9, len(matched_rights) * 2)
    if matched_rights:
        tags.append("合作权益诉求明确")
    if data_reconciliation in ["是，需要定期统计", "偶尔需要"]:
        score_detail["政策适配度"] += 3
        tags.append("需要数据支持")
    if ticketing_scenario in ["公商务出票", "会议会展出票", "客户需求代订 / 渠道出票"]:
        score_detail["政策适配度"] += 3
        tags.append("出票场景清晰")
        reasons.append("已明确出票或渠道承接场景，便于进一步匹配合作支持方式。")
    elif ticketing_scenario in ["旅游团队出票", "员工福利 / 客户答谢出行"]:
        score_detail["政策适配度"] += 2
        tags.append("场景型出行需求")
    if proof_materials in ["可以提供合同 / 邀请函 / 会议通知等材料", "可以提供组织证明或成员证明"]:
        score_detail["政策适配度"] += 5
        tags.append("材料基础较好")
        reasons.append("具备进一步核实合作场景的证明材料基础。")
    elif proof_materials == "视情况而定":
        score_detail["政策适配度"] += 2
    score_detail["政策适配度"] = min(25, score_detail["政策适配度"])

    matched_platforms = [item for item in platforms if item in ["会员系统", "小程序 / App", "微信群 / 社群", "企业内网 / OA", "校友平台"]]
    score_detail["渠道合作潜力"] += min(8, len(matched_platforms) * 2)
    if reach_ability == "能够统一通知和组织成员":
        score_detail["渠道合作潜力"] += 6
    elif reach_ability == "能够部分触达成员":
        score_detail["渠道合作潜力"] += 4
    if "品牌联合推广" in rights_focus:
        score_detail["渠道合作潜力"] += 4
        tags.append("品牌共建意愿")
    if "专属活动页面或入口" in rights_focus:
        score_detail["渠道合作潜力"] += 2
        tags.append("专属入口诉求")
    if any(item in demand_sources for item in ["会员 / 社群客户需求", "长期渠道销售需求", "旅行 / 活动团队需求"]):
        score_detail["渠道合作潜力"] += 3
        tags.append("需求来源可运营")
    score_detail["渠道合作潜力"] = min(20, score_detail["渠道合作潜力"])

    if compliance_support == "是，需要":
        score_detail["合规与落地条件"] += 3
        tags.append("关注合规支持")
    elif compliance_support == "不确定":
        score_detail["合规与落地条件"] += 1
    if proof_materials in ["可以提供合同 / 邀请函 / 会议通知等材料", "可以提供组织证明或成员证明"]:
        score_detail["合规与落地条件"] += 4
    elif proof_materials == "视情况而定":
        score_detail["合规与落地条件"] += 2
    if start_time in ["立即启动", "1个月内", "3个月内"]:
        score_detail["合规与落地条件"] += 3
        tags.append("启动时间明确")
    elif start_time == "半年内":
        score_detail["合规与落地条件"] += 1
    score_detail["合规与落地条件"] = min(10, score_detail["合规与落地条件"])

    score = int(sum(score_detail.values()))
    if score >= 80:
        match_level = "A级，高优先级合作客户"
    elif score >= 60:
        match_level = "B级，具备合作潜力客户"
    elif score >= 40:
        match_level = "C级，需进一步培育客户"
    else:
        match_level = "D级，普惠权益引导客户"

    can_reach = reach_ability in ["能够统一通知和组织成员", "能够部分触达成员"]
    has_channel = bool(set(platforms) & {"会员系统", "小程序 / App", "微信群 / 社群"})
    if customer_type == "政府 / 事业单位" and compliance_support == "是，需要":
        customer_segment = "公务合规型客户"
        recommended_policy = "公务出行合规支持方案"
    elif customer_type == "企业客户" and ("公务差旅" in travel_types or "商务拜访" in travel_types or ticketing_scenario == "公商务出票"):
        customer_segment = "企业差旅型客户"
        recommended_policy = "企业差旅合作方案"
    elif customer_type == "高校 / 校友会" and ("学术交流" in travel_types or "校友返校 / 校友活动" in travel_types):
        customer_segment = "高校校友合作客户"
        recommended_policy = "高校 / 校友专项出行方案"
    elif customer_type == "文旅 / 会展 / 活动合作方" and (group_travel in ["经常涉及", "偶尔涉及"] or ticketing_scenario in ["旅游团队出票", "会议会展出票"]):
        customer_segment = "会展文旅团队客户"
        recommended_policy = "会展团队出行支持方案"
    elif ticketing_scenario == "客户需求代订 / 渠道出票" or "长期渠道销售需求" in demand_sources:
        customer_segment = "渠道运营型客户"
        recommended_policy = "渠道会员权益共建方案"
    elif has_channel and can_reach:
        customer_segment = "渠道运营型客户"
        recommended_policy = "渠道会员权益共建方案"
    else:
        customer_segment = "普通潜力客户"
        recommended_policy = "普通会员权益引导方案"

    if fixed_plan in ["暂无明确计划", ""]:
        risk_notes.append("暂未提供明确固定行程，建议人工进一步确认需求周期。")
    if reach_ability in ["主要依赖个人自愿参与", "暂不具备", ""]:
        risk_notes.append("暂未体现统一触达渠道，建议核实客户组织动员能力。")
    if proof_materials in ["暂时无法提供", ""]:
        risk_notes.append("暂无法提供证明材料，建议进入人工复核。")
    if route_need in ["有，非常明确", "有大致方向"] and not route_detail:
        risk_notes.append("已选择存在重点航线需求，但尚未填写具体航线或方向，建议进一步补充。")
    if not ticketing_scenario or ticketing_scenario == "其他":
        risk_notes.append("出票或合作场景仍需进一步明确，建议人工确认客户真实需求类型。")
    if not demand_sources:
        risk_notes.append("需求来源暂未明确，建议补充客户需求来自内部成员、社群渠道还是外部客户。")
    if annual_trips < 100:
        risk_notes.append("年度预估出行人次较低，建议先按普通会员权益培育。")

    if not reasons:
        reasons.append("客户已完成基础需求填报，可作为后续人工沟通与方案匹配依据。")

    return {
        "customer_segment": customer_segment,
        "match_level": match_level,
        "score": score,
        "recommended_policy": recommended_policy,
        "reason": reasons,
        "risk_notes": risk_notes,
        "next_actions": [
            "建议由客户经理联系客户补充合作材料。",
            "建议核实重点航线、预计出行人数与启动时间。",
            "建议评估是否建立专属活动页面或合作入口。",
            "建议纳入渠道合作客户池持续跟进。",
        ],
        "score_detail": score_detail,
        "tags": list(dict.fromkeys(tags)) or ["待进一步沟通"],
    }


def inject_css():
    st.markdown(
        """
        <style>
        .stApp { background: linear-gradient(180deg, #eef5ff 0%, #f7f9fc 48%, #fff 100%); }
        .main .block-container { max-width: 1180px; padding-top: 2rem; }
        .hero-title { color: #003399; font-size: 2rem; font-weight: 800; margin-bottom: .35rem; }
        .hero-subtitle { color: #5d6b82; font-size: 1.05rem; margin-bottom: 1.2rem; }
        .card, .question-card, .result-card, .metric-card {
            background: #fff; border: 1px solid #dfe8f7; border-radius: 8px;
            box-shadow: 0 8px 24px rgba(0, 51, 153, .06);
        }
        .card { padding: 1.2rem; margin-bottom: 1rem; }
        .question-card { border-left: 5px solid #003399; padding: 1.2rem 1.3rem; margin: 1rem 0; }
        .result-card { padding: 1.2rem; margin-bottom: 1rem; }
        .metric-card { padding: 1rem; min-height: 92px; }
        .metric-label { color: #667085; font-size: .86rem; }
        .metric-value { color: #003399; font-size: 1.55rem; font-weight: 800; margin-top: .25rem; }
        .tag {
            display: inline-block; background: #eaf2ff; color: #003399; border: 1px solid #c9dcff;
            border-radius: 999px; padding: .22rem .6rem; margin: .15rem .2rem .15rem 0; font-size: .86rem;
        }
        div.stButton > button {
            width: 100%; border-radius: 8px; border: 1px solid #003399;
            background: #003399; color: white; height: 2.8rem; font-weight: 700;
        }
        div.stButton > button:hover { background: #002a80; color: white; border-color: #002a80; }
        .st-key-submit_record_action div.stButton > button {
            background: #c1121f;
            border-color: #c1121f;
            color: #fff;
            font-weight: 900;
        }
        .st-key-submit_record_action div.stButton > button:hover {
            background: #a60f1a;
            border-color: #a60f1a;
            color: #fff;
        }
        [class*="st-key-delete_record_action"] div.stButton > button {
            background: #c1121f;
            border-color: #c1121f;
            color: #fff;
            font-weight: 900;
            height: 2.35rem;
        }
        [class*="st-key-delete_record_action"] div.stButton > button:hover {
            background: #a60f1a;
            border-color: #a60f1a;
            color: #fff;
        }
        .record-header {
            color: #475467;
            font-weight: 700;
            padding: .55rem .35rem;
            border-bottom: 1px solid #dfe8f7;
        }
        .record-cell {
            padding: .5rem .35rem;
            border-bottom: 1px solid #e8eef8;
            min-height: 2.35rem;
            font-size: .92rem;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .secondary-note { color: #667085; font-size: .92rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_top_bar():
    cols = st.columns([8, 0.62, 0.62], gap="small")
    with cols[0]:
        st.caption(f"当前身份：{st.session_state.identity}")
    with cols[1]:
        if st.button("返回首页", key="top_home"):
            go_home()
            st.rerun()
    with cols[2]:
        if st.button("重新开始", key="top_reset"):
            reset_form()
            st.rerun()


def render_progress():
    st.progress(st.session_state.step / 6)
    st.markdown(f"**第 {st.session_state.step} 步 / 共 6 步**")


def set_widget_default(key, default):
    if key not in st.session_state:
        st.session_state[key] = st.session_state.answers.get(key, default)


def collect_answers(keys):
    for key in keys:
        st.session_state.answers[key] = st.session_state.get(key)


def list_to_text(value):
    return "，".join(value) if isinstance(value, list) else (value if value is not None else "")


def answers_dataframe(answers: dict):
    labels = {
        "contact_name": "联系人姓名", "phone": "联系电话", "organization": "所属单位 / 组织名称",
        "role": "职务 / 角色", "city": "所在城市", "customer_type": "客户类型",
        "org_size": "组织人数规模", "existing_channel": "是否已有固定合作渠道",
        "reach_ability": "是否具备统一组织 / 触达成员能力", "platforms": "专属入口、会员体系、社群或内部平台",
        "travel_types": "主要出行类型", "ticketing_scenario": "主要出票 / 合作场景",
        "demand_sources": "需求来源", "fixed_plan": "是否有固定或可预测行程",
        "travel_frequency": "预计出行频率", "single_trip_people": "预计单次同行人数",
        "annual_trips": "年度预估出行人次", "departure_city": "常用出发城市",
        "arrival_cities": "常用到达城市", "route_need": "是否有重点航线需求",
        "route_detail": "重点航线或方向",
        "time_preferences": "出行时间偏好", "group_travel": "是否涉及团队集中出行",
        "rights_focus": "最关注的合作权益", "compliance_support": "是否需要公务类合规支持",
        "data_reconciliation": "是否需要客户侧数据回收 / 对账", "proof_materials": "是否愿意配合提供证明材料",
        "cooperation_goal": "合作目标", "start_time": "预计启动时间", "remarks": "备注信息",
    }
    return pd.DataFrame([{"字段": label, "内容": list_to_text(answers.get(key, ""))} for key, label in labels.items()])


def render_step_1_basic_info():
    st.subheader("基础身份信息")
    defaults = {"contact_name": "", "phone": "", "organization": "", "role": "", "city": "", "customer_type": "企业客户"}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.text_input("联系人姓名 *", key="contact_name")
    st.text_input("联系电话 *", key="phone")
    st.text_input("所属单位 / 组织名称 *", key="organization")
    st.text_input("职务 / 角色", key="role")
    st.text_input("所在城市", key="city")
    st.radio("客户类型", ["企业客户", "政府 / 事业单位", "高校 / 校友会", "协会 / 商会 / 社团", "文旅 / 会展 / 活动合作方", "客户端渠道客户", "个人高频出行客户", "其他"], key="customer_type")


def render_step_2_org_profile():
    st.subheader("组织属性与合作基础")
    defaults = {"org_size": "50-200人", "existing_channel": "否，暂无固定航司合作", "reach_ability": "能够部分触达成员", "platforms": []}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.radio("组织人数规模", ["50人以下", "50-200人", "200-1000人", "1000人以上"], key="org_size")
    st.radio("是否已有固定合作渠道", ["是，已有南航相关合作", "是，但主要与其他航司合作", "否，暂无固定航司合作", "不确定"], key="existing_channel")
    st.radio("是否具备统一组织 / 触达成员能力", ["能够统一通知和组织成员", "能够部分触达成员", "主要依赖个人自愿参与", "暂不具备"], key="reach_ability")
    st.multiselect("是否有专属入口、会员体系、社群或内部平台", ["企业内网 / OA", "微信群 / 社群", "会员系统", "小程序 / App", "校友平台", "暂无"], key="platforms")


def render_step_3_travel_needs():
    st.subheader("出行需求")
    defaults = {
        "travel_types": [],
        "ticketing_scenario": "公商务出票",
        "demand_sources": [],
        "fixed_plan": "有年度 / 季度计划但日期未定",
        "travel_frequency": "每季度多次",
        "single_trip_people": 1,
        "annual_trips": 0,
    }
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.multiselect("主要出行类型", ["公务差旅", "商务拜访", "会议会展", "团队活动", "学术交流", "校友返校 / 校友活动", "文旅出行", "客户答谢 / 员工福利", "个人及家庭出行"], key="travel_types")
    st.radio("主要出票 / 合作场景", ["公商务出票", "旅游团队出票", "会议会展出票", "客户需求代订 / 渠道出票", "员工福利 / 客户答谢出行", "个人会员出行", "其他"], key="ticketing_scenario")
    st.multiselect("需求来源", ["企业员工差旅需求", "政府 / 事业单位公务需求", "会员 / 社群客户需求", "旅行 / 活动团队需求", "会议会展参会需求", "临时客户咨询需求", "长期渠道销售需求", "个人及家庭出行需求"], key="demand_sources")
    st.radio("是否有固定或可预测行程", ["有明确固定行程", "有年度 / 季度计划但日期未定", "出行不固定但频率较高", "暂无明确计划"], key="fixed_plan")
    st.radio("预计出行频率", ["每周多次", "每月多次", "每季度多次", "每年数次", "不确定"], key="travel_frequency")
    st.slider("预计单次同行人数", 1, 500, key="single_trip_people")
    st.number_input("年度预估出行人次", min_value=0, max_value=100000, step=10, key="annual_trips")


def render_step_4_route_time():
    st.subheader("航线与时间需求")
    defaults = {"departure_city": "", "arrival_cities": "", "route_need": "有大致方向", "route_detail": "", "time_preferences": [], "group_travel": "偶尔涉及"}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.text_input("常用出发城市", key="departure_city")
    st.text_input("常用到达城市，可输入多个，用逗号分隔", key="arrival_cities")
    st.radio("是否有重点航线需求", ["有，非常明确", "有大致方向", "暂无明确航线"], key="route_need")
    if st.session_state.route_need in ["有，非常明确", "有大致方向"]:
        st.text_input(
            "请填写重点航线或方向",
            placeholder="例如：广州-北京、深圳-上海，或华南至华东、广州出发国内重点城市等",
            key="route_detail",
        )
    else:
        st.session_state.route_detail = ""
    st.multiselect("出行时间偏好", ["工作日", "周末", "节假日", "寒暑假", "会展 / 活动期间", "无固定偏好"], key="time_preferences")
    st.radio("是否涉及团队集中出行", ["经常涉及", "偶尔涉及", "基本不涉及", "不确定"], key="group_travel")


def render_step_5_policy_needs():
    st.subheader("政策需求与权益偏好")
    defaults = {"rights_focus": [], "compliance_support": "不确定", "data_reconciliation": "偶尔需要", "proof_materials": "视情况而定"}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.multiselect("最关注的合作权益", ["票价优惠", "改退签灵活性", "行李权益", "贵宾服务", "团队票支持", "专属客户经理", "数据统计 / 对账支持", "专属活动页面或入口", "品牌联合推广"], key="rights_focus")
    st.radio("是否需要公务类合规支持", ["是，需要", "否，不需要", "不确定"], key="compliance_support")
    st.radio("是否需要客户侧数据回收 / 对账", ["是，需要定期统计", "偶尔需要", "不需要"], key="data_reconciliation")
    st.radio("是否愿意配合提供证明材料", ["可以提供合同 / 邀请函 / 会议通知等材料", "可以提供组织证明或成员证明", "暂时无法提供", "视情况而定"], key="proof_materials")


def render_step_6_confirmation():
    st.subheader("补充说明与确认")
    defaults = {"cooperation_goal": "", "start_time": "暂不确定", "remarks": "", "analysis_agreement": False}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.text_area("合作目标", placeholder="例如：希望解决什么问题、希望达成什么合作效果", key="cooperation_goal")
    st.radio("预计启动时间", ["立即启动", "1个月内", "3个月内", "半年内", "暂不确定"], key="start_time")
    st.text_area("备注信息", key="remarks")
    st.checkbox("我同意将以上信息用于合作需求分析 *", key="analysis_agreement")


def render_home_page():
    st.markdown('<div class="hero-title">南方航空新型渠道合作客户信息收集系统</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">请选择访问身份，进入对应功能页面</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="card"><h3 style="color:#003399;margin-top:0;">客户填报入口</h3><p class="secondary-note">通过几个问题生成您的渠道合作画像与适配方案。</p></div>', unsafe_allow_html=True)
        if st.button("我是合作客户，开始填写需求", key="home_customer"):
            reset_form()
            st.rerun()
    with col2:
        st.markdown('<div class="card"><h3 style="color:#003399;margin-top:0;">南航内部入口</h3><p class="secondary-note">查看客户提交记录、系统匹配画像、推荐政策方向及待跟进事项。</p></div>', unsafe_allow_html=True)
        if st.button("我是南航内部人员，查看客户数据", key="home_admin"):
            st.session_state.identity = "南航内部人员"
            st.session_state.page = "admin_login"
            st.rerun()


def render_customer_page():
    render_top_bar()
    st.markdown('<div class="hero-title">合作客户需求测评</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">完成几个问题，生成您的渠道合作画像与适配方案</div>', unsafe_allow_html=True)
    render_progress()
    step = st.session_state.step
    step_keys = {
        1: ["contact_name", "phone", "organization", "role", "city", "customer_type"],
        2: ["org_size", "existing_channel", "reach_ability", "platforms"],
        3: ["travel_types", "ticketing_scenario", "demand_sources", "fixed_plan", "travel_frequency", "single_trip_people", "annual_trips"],
        4: ["departure_city", "arrival_cities", "route_need", "route_detail", "time_preferences", "group_travel"],
        5: ["rights_focus", "compliance_support", "data_reconciliation", "proof_materials"],
        6: ["cooperation_goal", "start_time", "remarks", "analysis_agreement"],
    }
    [render_step_1_basic_info, render_step_2_org_profile, render_step_3_travel_needs, render_step_4_route_time, render_step_5_policy_needs, render_step_6_confirmation][step - 1]()
    back_col, next_col = st.columns(2)
    with back_col:
        if st.button("上一步", key=f"back_{step}", disabled=step == 1):
            collect_answers(step_keys[step])
            go_back()
            st.rerun()
    with next_col:
        if step < 6:
            if st.button("下一步", key=f"next_{step}"):
                collect_answers(step_keys[step])
                if step == 1 and (not st.session_state.answers.get("contact_name") or not st.session_state.answers.get("phone") or not st.session_state.answers.get("organization")):
                    st.warning("请填写联系人姓名、联系电话和所属单位 / 组织名称。")
                    return
                go_next()
                st.rerun()
        elif st.button("提交并生成画像", key="submit_form"):
            collect_answers(step_keys[step])
            if not st.session_state.answers.get("analysis_agreement"):
                st.warning("请先勾选同意用于合作需求分析。")
                return
            st.session_state.result = evaluate_customer_profile(st.session_state.answers)
            st.session_state.saved = False
            st.session_state.page = "result"
            st.rerun()


def render_result_page():
    render_top_bar()
    answers = st.session_state.answers
    result = st.session_state.result or evaluate_customer_profile(answers)
    st.success("提交信息已生成，请确认后提交本次记录。")
    st.markdown('<div class="hero-title">请确认您的填报信息</div>', unsafe_allow_html=True)
    submit_left, submit_mid, submit_right = st.columns([3, 1.2, 3])
    with submit_mid:
        with st.container(key="submit_record_action"):
            if st.button("提交本次记录", key="save_record"):
                if st.session_state.saved:
                    st.info("本次记录已保存，无需重复提交。")
                else:
                    save_record(answers, result)
                    st.session_state.saved = True
                    st.success("已保存")
    st.subheader("答案汇总")
    st.dataframe(answers_dataframe(answers), use_container_width=True, hide_index=True)
    payload = {"answers": answers, "result": result, "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    col1, col2, col3 = st.columns(3)
    with col1:
        st.download_button("导出 JSON", json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"), file_name=f"customer_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json", mime="application/json", key="download_result_json")
    with col2:
        if st.button("重新填写", key="result_restart"):
            reset_form()
            st.rerun()
    with col3:
        if st.button("返回首页", key="result_home"):
            go_home()
            st.rerun()


def render_admin_login():
    cols = st.columns([1.3, 7, 0.8], gap="small")
    with cols[0]:
        st.markdown('<div class="hero-title">南航内部客户数据看板</div>', unsafe_allow_html=True)
        st.markdown('<div class="hero-subtitle">请输入本地演示访问码后查看客户数据</div>', unsafe_allow_html=True)
    with cols[2]:
        if st.button("返回首页", key="login_home"):
            go_home()
            st.rerun()
    code = st.text_input("访问码", type="password", key="admin_code_input")
    if st.button("进入后台", key="admin_login_btn"):
        if code == ADMIN_CODE:
            st.session_state.admin_authenticated = True
            st.session_state.page = "admin_dashboard"
            st.rerun()
        else:
            st.error("访问码错误，请重新输入")
    st.caption("访问码仅用于本地演示。")


def render_metric_cards(df):
    if df.empty:
        values = [0, 0, 0, 0, "-"]
    else:
        values = [
            len(df),
            int(df["match_level"].astype(str).str.startswith("A级").sum()),
            int(df["match_level"].astype(str).str.startswith("B级").sum()),
            int(df["risk_notes_json"].astype(str).apply(lambda x: len(parse_json_field(x, [])) > 0).sum()),
            df["submit_time"].max() if "submit_time" in df.columns else "-",
        ]
    labels = ["总提交数", "A级客户数", "B级客户数", "待人工复核客户数", "最近一次提交时间"]
    for col, label, value in zip(st.columns(5), labels, values):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)


def render_record_filters(df):
    if df.empty:
        return df
    filtered = df.copy()
    st.subheader("筛选客户记录")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        selected_type = st.selectbox("客户类型", ["全部"] + sorted([x for x in filtered["customer_type"].unique().tolist() if x]))
    with c2:
        selected_level = st.selectbox("匹配等级", ["全部"] + sorted([x for x in filtered["match_level"].unique().tolist() if x]))
    with c3:
        selected_segment = st.selectbox("客户分层", ["全部"] + sorted([x for x in filtered["customer_segment"].unique().tolist() if x]))
    with c4:
        selected_city = st.selectbox("城市", ["全部"] + sorted([x for x in filtered["city"].unique().tolist() if x]))
    with c5:
        keyword = st.text_input("关键词搜索")
    if selected_type != "全部":
        filtered = filtered[filtered["customer_type"] == selected_type]
    if selected_level != "全部":
        filtered = filtered[filtered["match_level"] == selected_level]
    if selected_segment != "全部":
        filtered = filtered[filtered["customer_segment"] == selected_segment]
    if selected_city != "全部":
        filtered = filtered[filtered["city"] == selected_city]
    if keyword:
        mask = (
            filtered["organization"].astype(str).str.contains(keyword, case=False, na=False)
            | filtered["contact_name"].astype(str).str.contains(keyword, case=False, na=False)
            | filtered["phone"].astype(str).str.contains(keyword, case=False, na=False)
        )
        filtered = filtered[mask]
    return filtered


def render_record_detail(record):
    st.subheader("客户详情")
    st.write(f"**推荐政策方向：** {record.get('recommended_policy', '')}")

    all_answers = parse_json_field(record.get("all_answers_json", ""), {})
    score_detail = parse_json_field(record.get("score_detail_json", ""), {})
    tags = parse_json_field(record.get("tags_json", ""), [])
    risk_notes = parse_json_field(record.get("risk_notes_json", ""), [])
    next_actions = parse_json_field(record.get("next_actions_json", ""), [])
    reason = parse_json_field(record.get("reason_json", ""), [])

    with st.expander("客户完整答案", expanded=True):
        st.dataframe(answers_dataframe(all_answers), use_container_width=True, hide_index=True)

    with st.expander("评分明细"):
        if score_detail:
            score_df = pd.DataFrame(
                [{"评分维度": key, "得分": value} for key, value in score_detail.items()]
            )
            st.dataframe(score_df, use_container_width=True, hide_index=True)
        else:
            st.write("暂无评分明细。")

    with st.expander("客户标签"):
        st.write("，".join(tags) if tags else "暂无")

    with st.expander("待核实事项"):
        if risk_notes:
            for item in risk_notes:
                st.write(f"- {item}")
        else:
            st.write("暂无明显风险。")

    with st.expander("后续动作"):
        if next_actions:
            for item in next_actions:
                st.write(f"- {item}")
        else:
            st.write("暂无")

    with st.expander("匹配原因"):
        if reason:
            for item in reason:
                st.write(f"- {item}")
        else:
            st.write("暂无")


def render_delete_confirm_dialog():
    if st.session_state.pending_delete_index is None:
        return

    @st.dialog("确认删除")
    def confirm_delete():
        st.write("是否删除该条客户记录？")
        if st.session_state.pending_delete_label:
            st.caption(st.session_state.pending_delete_label)
        col_yes, col_no = st.columns(2)
        with col_yes:
            if st.button("是，删除", key="confirm_delete_yes"):
                ok = delete_record_by_id(st.session_state.pending_delete_index)
                st.session_state.pending_delete_index = None
                st.session_state.pending_delete_label = ""
                st.toast("已删除" if ok else "记录不存在或已删除")
                st.rerun()
        with col_no:
            if st.button("否，返回", key="confirm_delete_no"):
                st.session_state.pending_delete_index = None
                st.session_state.pending_delete_label = ""
                st.rerun()

    confirm_delete()


def render_records_table_with_actions(filtered):
    headers = ["提交时间", "组织名称", "联系人", "电话", "城市", "客户类型", "客户分层", "匹配等级", "综合评分", "推荐政策方向", "待核实事项", "操作"]
    widths = [1.05, 1, .75, .75, .6, .9, 1, 1.25, .7, 1.25, 1.45, .65]
    header_cols = st.columns(widths)
    for col, header in zip(header_cols, headers):
        with col:
            st.markdown(f'<div class="record-header">{header}</div>', unsafe_allow_html=True)

    for idx, row in filtered.iterrows():
        record_id = row.get("id", idx)
        risks = "；".join(parse_json_field(row.get("risk_notes_json", ""), []))
        values = [
            row.get("submit_time", ""),
            row.get("organization", ""),
            row.get("contact_name", ""),
            row.get("phone", ""),
            row.get("city", ""),
            row.get("customer_type", ""),
            row.get("customer_segment", ""),
            row.get("match_level", ""),
            row.get("score", ""),
            row.get("recommended_policy", ""),
            risks,
        ]
        row_cols = st.columns(widths)
        for col, value in zip(row_cols[:-1], values):
            with col:
                st.markdown(f'<div class="record-cell" title="{value}">{value}</div>', unsafe_allow_html=True)
        with row_cols[-1]:
            with st.container(key=f"delete_record_action_{record_id}"):
                if st.button("删除", key=f"delete_record_{record_id}"):
                    st.session_state.pending_delete_index = record_id
                    st.session_state.pending_delete_label = f"{row.get('submit_time', '')} | {row.get('organization', '')} | {row.get('contact_name', '')}"
                    st.rerun()


def render_admin_dashboard():
    if not st.session_state.admin_authenticated:
        st.session_state.page = "admin_login"
        st.rerun()
    cols = st.columns([1.3, 6.6, 0.8, 0.8], gap="small")
    with cols[0]:
        st.markdown('<div class="hero-title">南航内部客户数据看板</div>', unsafe_allow_html=True)
        st.markdown('<div class="hero-subtitle">查看客户填报记录、系统画像、匹配等级、推荐政策方向与待跟进事项</div>', unsafe_allow_html=True)
    with cols[2]:
        if st.button("刷新数据", key="refresh_admin"):
            st.rerun()
    with cols[3]:
        if st.button("返回首页", key="admin_home"):
            go_home()
            st.rerun()
    df = load_records()
    if df.empty:
        st.info("暂无客户提交记录，请先通过客户填报端提交数据。")
        return
    render_metric_cards(df)
    filtered = render_record_filters(df)
    st.subheader("客户记录")
    render_records_table_with_actions(filtered)
    render_delete_confirm_dialog()
    col1, col2, col3 = st.columns([5, 1.35, 1.35], gap="small")
    with col2:
        st.download_button("下载当前筛选结果 CSV", records_to_download_csv(filtered), file_name=f"filtered_customer_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", key="download_filtered_csv")
    with col3:
        st.download_button("下载全部客户数据 CSV", records_to_download_csv(df), file_name=f"all_customer_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv", mime="text/csv", key="download_all_csv")
    if filtered.empty:
        st.warning("当前筛选条件下暂无记录。")
        return
    st.subheader("详情查看")
    options = [(idx, f"{row.get('submit_time', '')} | {row.get('organization', '')} | {row.get('contact_name', '')} | {row.get('match_level', '')}") for idx, row in filtered.iterrows()]
    selected = st.selectbox("选择一条客户记录", options, format_func=lambda x: x[1])
    if selected:
        render_record_detail(filtered.loc[selected[0]].to_dict())


def main():
    st.set_page_config(page_title="南方航空新型渠道合作客户信息收集系统", page_icon="✈️", layout="wide")
    init_session_state()
    inject_css()
    page = st.session_state.page
    if page == "home":
        render_home_page()
    elif page == "customer_form":
        render_customer_page()
    elif page == "result":
        render_result_page()
    elif page == "admin_login":
        render_admin_login()
    elif page == "admin_dashboard":
        render_admin_dashboard()
    else:
        go_home()
        render_home_page()


if __name__ == "__main__":
    main()



