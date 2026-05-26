import json
import os
import sqlite3
from datetime import datetime

import pandas as pd
import requests
import streamlit as st


DATA_DIR = "data"
CSV_RECORD_FILE = os.path.join(DATA_DIR, "customer_records.csv")
DB_FILE = os.path.join(DATA_DIR, "customer_records.db")
ADMIN_CODE = "csair123"
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/v1/chat/completions")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")


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
        "pending_remove_journey": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def go_home():
    st.session_state.page = "home"
    st.session_state.identity = "未选择"


def go_next():
    st.session_state.step = min(3, st.session_state.step + 1)


def go_back():
    st.session_state.step = max(1, st.session_state.step - 1)


def reset_form():
    form_keys = [
        "contact_name", "phone", "organization", "role", "city", "customer_type",
        "travel_scene", "travel_types", "companion_count_range", "single_trip_people",
        "fixed_plan", "reach_ability", "journey_count", "start_time",
        "rights_focus", "compliance_support", "compliance_detail", "proof_materials",
        "cooperation_goal", "start_time", "remarks", "analysis_agreement", "admin_code_input",
    ]
    for key in list(st.session_state.keys()):
        if str(key).startswith("journey_"):
            form_keys.append(key)
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


def normalize_list(value):
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def normalize_text(value):
    if isinstance(value, list):
        return "；".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def get_primary_journey(answers: dict) -> dict:
    journeys = answers.get("journeys") or []
    return journeys[0] if journeys else {}


def split_city_text(value: str) -> list:
    normalized = str(value or "").replace("，", ",").replace("、", ",").replace("；", ",")
    return [item.strip() for item in normalized.split(",") if item.strip()]


def infer_ticketing_scenario(travel_scene: str) -> str:
    mapping = {
        "公务差旅": "公商务出票",
        "商务拜访": "公商务出票",
        "会议会展": "会议会展出票",
        "团队活动": "客户需求代订 / 渠道出票",
        "学术交流": "公商务出票",
        "校友活动": "客户需求代订 / 渠道出票",
        "文旅出行": "旅游团队出票",
        "员工福利或客户答谢": "员工福利 / 客户答谢出行",
        "个人及家庭出行": "个人会员出行",
    }
    return mapping.get(travel_scene, "其他")


def infer_demand_sources(customer_type: str, travel_scene: str) -> list:
    sources = []
    if customer_type == "企业客户":
        sources.append("企业员工差旅需求")
    if customer_type == "政府或事业单位":
        sources.append("政府 / 事业单位公务需求")
    if customer_type == "高校或校友会" or travel_scene in ["学术交流", "校友活动"]:
        sources.append("会议会展参会需求")
    if travel_scene in ["团队活动", "文旅出行"]:
        sources.append("旅行 / 活动团队需求")
    if travel_scene == "个人及家庭出行":
        sources.append("个人及家庭出行需求")
    return sources


def normalize_answers_for_scoring(answers: dict) -> dict:
    normalized = dict(answers)
    journey = get_primary_journey(answers)
    journeys = answers.get("journeys") or []
    travel_scene_map = {
        "校友活动": "校友返校 / 校友活动",
        "员工福利或客户答谢": "客户答谢 / 员工福利",
    }
    travel_scene = travel_scene_map.get(answers.get("travel_scene") or "", answers.get("travel_scene") or "")
    customer_type_map = {
        "政府或事业单位": "政府 / 事业单位",
        "高校或校友会": "高校 / 校友会",
        "协会、商会或社团": "协会 / 商会 / 社团",
        "文旅、会展或活动合作方": "文旅 / 会展 / 活动合作方",
    }
    normalized["customer_type"] = customer_type_map.get(answers.get("customer_type", ""), answers.get("customer_type", ""))
    normalized["travel_types"] = answers.get("travel_types") or ([travel_scene] if travel_scene else [])
    fixed_plan_map = {
        "已明确固定行程": "有明确固定行程",
        "有大致计划但日期未定": "有年度 / 季度计划但日期未定",
    }
    normalized["fixed_plan"] = fixed_plan_map.get(answers.get("fixed_plan", ""), answers.get("fixed_plan", ""))
    rights_map = {
        "专属活动页或入口": "专属活动页面或入口",
    }
    normalized["rights_focus"] = [rights_map.get(item, item) for item in (answers.get("rights_focus") or [])]
    normalized["ticketing_scenario"] = answers.get("ticketing_scenario") or infer_ticketing_scenario(travel_scene)
    normalized["demand_sources"] = answers.get("demand_sources") or infer_demand_sources(normalized.get("customer_type", ""), travel_scene)
    normalized["travel_frequency"] = answers.get("travel_frequency") or journey.get("travel_frequency", "")
    normalized["departure_city"] = answers.get("departure_city") or journey.get("departure_city", "")
    normalized["arrival_cities"] = answers.get("arrival_cities") or journey.get("arrival_cities", "")
    normalized["time_preferences"] = answers.get("time_preferences") or journey.get("time_preferences", [])
    normalized["group_travel"] = answers.get("group_travel") or journey.get("group_travel", "")
    normalized["route_detail"] = answers.get("route_detail") or "；".join(
        f"{item.get('departure_city', '')}-{item.get('arrival_cities', '')}".strip("-")
        for item in journeys
        if item.get("departure_city") or item.get("arrival_cities")
    )
    normalized["route_need"] = "有，非常明确" if normalized.get("route_detail") else "暂无明确航线"
    try:
        normalized["single_trip_people"] = int(answers.get("single_trip_people") or 0)
    except Exception:
        normalized["single_trip_people"] = 0
    frequency_factor = {
        "单次": 1,
        "每周多次": 80,
        "每月多次": 24,
        "每季度多次": 8,
        "每年数次": 3,
        "不确定": 1,
    }.get(normalized.get("travel_frequency"), 1)
    normalized["annual_trips"] = int(answers.get("annual_trips") or normalized["single_trip_people"] * frequency_factor)
    normalized["org_size"] = answers.get("org_size") or (
        "1000人以上" if normalized["single_trip_people"] >= 200 else
        "200-1000人" if normalized["single_trip_people"] >= 50 else
        "50-200人" if normalized["single_trip_people"] >= 10 else
        "50人以下"
    )
    normalized["platforms"] = answers.get("platforms") or []
    normalized["data_reconciliation"] = answers.get("data_reconciliation") or (
        "偶尔需要" if answers.get("compliance_support") in ["涉及，需要", "不确定"] else "不需要"
    )
    return normalized


def extract_json_object(text: str):
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                return {}
    return {}


def build_rule_profile_summary(result: dict) -> str:
    score_detail = result.get("score_detail", {})
    tags = "、".join(result.get("tags", [])) or "待进一步沟通"
    risks = "；".join(result.get("risk_notes", [])) or "暂无明显风险"
    return (
        f"系统规则判断该客户为{result.get('customer_segment', '未分类')}，"
        f"匹配等级为{result.get('match_level', '未评级')}，综合评分{result.get('score', 0)}分。"
        f"推荐政策方向为{result.get('recommended_policy', '待确认')}。"
        f"主要标签：{tags}。待核实事项：{risks}。"
        f"评分明细：{json.dumps(score_detail, ensure_ascii=False)}"
    )


def generate_quote_result(answers: dict, result: dict) -> dict:
    normalized = normalize_answers_for_scoring(answers)
    score = int(result.get("score", 0) or 0)
    people = int(normalized.get("single_trip_people", 0) or 0)
    start_time = normalized.get("start_time", "")
    fixed_plan = normalized.get("fixed_plan", "")
    rights = normalized.get("rights_focus", [])
    compliance = normalized.get("compliance_support", "")
    risks = result.get("risk_notes", []) or []

    if score >= 80:
        discount = "7.5-8.5折"
        plan = "重点合作报价方案"
    elif score >= 60:
        discount = "8-9折"
        plan = "团队/差旅合作报价方案"
    elif score >= 40:
        discount = "9-9.5折"
        plan = "基础合作报价方案"
    else:
        discount = "以实时票价及会员权益为准"
        plan = "普通出行权益参考方案"

    if people >= 50 and "团队票支持" in rights:
        plan = "团队出行报价方案"
    if compliance in ["涉及，需要", "是，需要"]:
        plan = f"{plan}（含合规材料支持）"

    confidence = "高"
    if risks or fixed_plan in ["暂无明确计划", ""] or start_time == "暂不确定":
        confidence = "中"
    if len(risks) >= 3 or people <= 0:
        confidence = "低"

    review_required = confidence == "低" or bool(risks)
    customer_tip = f"本次出行可优先参考{plan}，预计可享受{discount}的合作优惠，最终价格需结合实际航班、舱位、人数和出票时间确认。"
    if review_required:
        customer_tip = "您的需求已提交，因部分信息仍需确认，客户经理将结合航线、人数和材料情况为您提供更准确的报价参考。"

    return {
        "quote_plan": plan,
        "quote_range": discount,
        "customer_tip": customer_tip,
        "quote_confidence": confidence,
        "manual_review_required": review_required,
        "quote_basis": [
            f"综合评分：{score}",
            f"同行人数：{people or '待确认'}",
            f"行程确定度：{fixed_plan or '待确认'}",
            f"启动时间：{start_time or '待确认'}",
            f"权益偏好：{list_to_text(rights) or '待确认'}",
        ],
    }


def build_fallback_ai_profile(result: dict, status: str, error: str = "") -> dict:
    return {
        "ai_status": status,
        "ai_error": error,
        "ai_profile": build_rule_profile_summary(result),
        "ai_suggestions": "；".join(result.get("next_actions", [])),
        "ai_opportunities": result.get("reason", []),
        "ai_risk_review": result.get("risk_notes", []),
        "ai_follow_up_questions": [
            "请进一步确认重点航线、预计出行人数和启动时间。",
            "请补充可提供的合作证明材料或组织证明。",
        ],
        "ai_confidence": "规则兜底",
    }


def call_deepseek_customer_profile(answers: dict, result: dict) -> dict:
    api_key = DEEPSEEK_API_KEY.strip()
    if not api_key:
        return build_fallback_ai_profile(result, "未启用", "未配置 DEEPSEEK_API_KEY")

    system_prompt = (
        "你是南方航空新型渠道合作客户画像分析助手。"
        "请基于客户问卷答案、多个行程信息和系统规则评分，生成可供南航内部客户经理查看的客户画像。"
        "客户画像请突出客户身份、出行场景、同行规模、主要航线、时间偏好、合作诉求和报价策略参考。"
        "必须严格输出 JSON，不要输出 Markdown，不要输出解释性前后缀。"
        "JSON 字段包括："
        "customer_profile 字符串；"
        "suggestions 字符串，给客户经理的具体跟进建议，用一段完整自然语言表达，约100字，不要分条；"
        "opportunity_points 字符串数组，合作机会点；"
        "risk_review 字符串数组，待核实风险或不确定事项；"
        "follow_up_questions 字符串数组，建议下一步询问客户的问题；"
        "confidence 字符串，只能是 高、中、低。"
    )
    user_payload = {
        "customer_answers": answers,
        "rule_result": result,
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
        ],
        "temperature": 0.2,
        "max_tokens": 900,
        "response_format": {"type": "json_object"},
    }
    try:
        response = requests.post(
            DEEPSEEK_API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=(5, 20),
        )
        response.raise_for_status()
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        parsed = extract_json_object(content)
        profile = str(parsed.get("customer_profile", "")).strip()
        if not profile:
            profile = build_rule_profile_summary(result)
        return {
            "ai_status": "成功",
            "ai_error": "",
            "ai_profile": profile,
            "ai_suggestions": normalize_text(parsed.get("suggestions")),
            "ai_opportunities": normalize_list(parsed.get("opportunity_points")),
            "ai_risk_review": normalize_list(parsed.get("risk_review")),
            "ai_follow_up_questions": normalize_list(parsed.get("follow_up_questions")),
            "ai_confidence": str(parsed.get("confidence", "中")).strip() or "中",
        }
    except Exception as exc:
        return build_fallback_ai_profile(result, "失败", str(exc))


def enrich_customer_profile_with_ai(answers: dict, result: dict) -> dict:
    ai_result = call_deepseek_customer_profile(answers, result)
    enriched = result.copy()
    enriched.update(ai_result)
    enriched.update(generate_quote_result(answers, enriched))
    return enriched


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
        "ai_status": result.get("ai_status", ""),
        "ai_error": result.get("ai_error", ""),
        "ai_profile": result.get("ai_profile", ""),
        "ai_suggestions_json": json.dumps(result.get("ai_suggestions", ""), ensure_ascii=False),
        "ai_opportunities_json": json.dumps(result.get("ai_opportunities", []), ensure_ascii=False),
        "ai_risk_review_json": json.dumps(result.get("ai_risk_review", []), ensure_ascii=False),
        "ai_follow_up_questions_json": json.dumps(result.get("ai_follow_up_questions", []), ensure_ascii=False),
        "ai_confidence": result.get("ai_confidence", ""),
        "quote_plan": result.get("quote_plan", ""),
        "quote_range": result.get("quote_range", ""),
        "customer_tip": result.get("customer_tip", ""),
        "quote_confidence": result.get("quote_confidence", ""),
        "manual_review_required": "是" if result.get("manual_review_required") else "否",
        "quote_basis_json": json.dumps(result.get("quote_basis", []), ensure_ascii=False),
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
                all_answers_json TEXT,
                ai_status TEXT,
                ai_error TEXT,
                ai_profile TEXT,
                ai_suggestions_json TEXT,
                ai_opportunities_json TEXT,
                ai_risk_review_json TEXT,
                ai_follow_up_questions_json TEXT,
                ai_confidence TEXT,
                quote_plan TEXT,
                quote_range TEXT,
                customer_tip TEXT,
                quote_confidence TEXT,
                manual_review_required TEXT,
                quote_basis_json TEXT
            )
            """
        )
        ensure_database_columns(conn)
        conn.commit()
    migrate_csv_to_database()


def ensure_database_columns(conn):
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(customer_records)").fetchall()}
    columns_to_add = {
        "ai_status": "TEXT",
        "ai_error": "TEXT",
        "ai_profile": "TEXT",
        "ai_suggestions_json": "TEXT",
        "ai_opportunities_json": "TEXT",
        "ai_risk_review_json": "TEXT",
        "ai_follow_up_questions_json": "TEXT",
        "ai_confidence": "TEXT",
        "quote_plan": "TEXT",
        "quote_range": "TEXT",
        "customer_tip": "TEXT",
        "quote_confidence": "TEXT",
        "manual_review_required": "TEXT",
        "quote_basis_json": "TEXT",
    }
    for column, column_type in columns_to_add.items():
        if column not in existing_columns:
            conn.execute(f"ALTER TABLE customer_records ADD COLUMN {column} {column_type}")


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
    answers = normalize_answers_for_scoring(answers)
    score_detail = {
        "基础信息完整度": 0,
        "出行规模与场景价值": 0,
        "行程与航线明确度": 0,
        "组织协同与落地条件": 0,
        "合作诉求与材料配合": 0,
    }
    tags = []
    reasons = []
    risk_notes = []

    customer_type = answers.get("customer_type", "")
    reach_ability = answers.get("reach_ability", "")
    travel_types = answers.get("travel_types", []) or []
    ticketing_scenario = answers.get("ticketing_scenario", "")
    demand_sources = answers.get("demand_sources", []) or []
    fixed_plan = answers.get("fixed_plan", "")
    travel_frequency = answers.get("travel_frequency", "")
    annual_trips = int(answers.get("annual_trips") or 0)
    route_detail = answers.get("route_detail", "")
    group_travel = answers.get("group_travel", "")
    rights_focus = answers.get("rights_focus", []) or []
    compliance_support = answers.get("compliance_support", "")
    proof_materials = answers.get("proof_materials", "")
    start_time = answers.get("start_time", "")
    journeys = answers.get("journeys") or []
    single_trip_people = int(answers.get("single_trip_people") or 0)

    if answers.get("contact_name"):
        score_detail["基础信息完整度"] += 3
    if answers.get("phone"):
        score_detail["基础信息完整度"] += 3
    if answers.get("city"):
        score_detail["基础信息完整度"] += 2
    if customer_type:
        score_detail["基础信息完整度"] += 2
    if answers.get("organization"):
        score_detail["基础信息完整度"] += 2
    if answers.get("role"):
        score_detail["基础信息完整度"] += 1
    score_detail["基础信息完整度"] = min(12, score_detail["基础信息完整度"])

    scene_scores = {
        "公务差旅": 6,
        "商务拜访": 6,
        "会议会展": 7,
        "团队活动": 6,
        "学术交流": 5,
        "校友返校 / 校友活动": 5,
        "文旅出行": 5,
        "客户答谢 / 员工福利": 4,
        "个人及家庭出行": 2,
        "其他": 1,
    }
    scene_score = max([scene_scores.get(item, 0) for item in travel_types] or [0])
    score_detail["出行规模与场景价值"] += scene_score
    if scene_score >= 5:
        tags.append("合作场景清晰")
        reasons.append("客户选择的出行场景具备团队、差旅或活动合作价值。")
    if single_trip_people >= 200:
        score_detail["出行规模与场景价值"] += 10
        tags.append("大规模同行需求")
    elif single_trip_people >= 50:
        score_detail["出行规模与场景价值"] += 8
        tags.append("团队规模较高")
    elif single_trip_people >= 10:
        score_detail["出行规模与场景价值"] += 5
    elif single_trip_people > 0:
        score_detail["出行规模与场景价值"] += 2
    if travel_frequency == "每周多次":
        score_detail["出行规模与场景价值"] += 5
        tags.append("高频出行")
    elif travel_frequency == "每月多次":
        score_detail["出行规模与场景价值"] += 4
    elif travel_frequency == "每季度多次":
        score_detail["出行规模与场景价值"] += 3
    elif travel_frequency == "每年数次":
        score_detail["出行规模与场景价值"] += 2
    elif travel_frequency == "单次":
        score_detail["出行规模与场景价值"] += 1
    if annual_trips >= 1000:
        score_detail["出行规模与场景价值"] += 3
        tags.append("年度出行规模较高")
    elif annual_trips >= 200:
        score_detail["出行规模与场景价值"] += 2
    score_detail["出行规模与场景价值"] = min(25, score_detail["出行规模与场景价值"])

    if fixed_plan == "有明确固定行程":
        score_detail["行程与航线明确度"] += 7
        tags.append("行程明确")
        reasons.append("客户行程安排较明确，便于客户经理快速核价。")
    elif fixed_plan == "有年度 / 季度计划但日期未定":
        score_detail["行程与航线明确度"] += 5
        tags.append("计划型需求")
    elif fixed_plan == "出行不固定但频率较高":
        score_detail["行程与航线明确度"] += 4
    if route_detail:
        score_detail["行程与航线明确度"] += 6
        tags.append("航线信息已补充")
        reasons.append("客户已填写出发城市和到达城市，可进入航线资源匹配。")
    if journeys:
        score_detail["行程与航线明确度"] += min(3, len(journeys))
    if any(item.get("time_preferences") for item in journeys):
        score_detail["行程与航线明确度"] += 2
        tags.append("时间偏好已补充")
    if start_time in ["立即启动", "1个月内"]:
        score_detail["行程与航线明确度"] += 5
        tags.append("启动紧迫")
    elif start_time == "3个月内":
        score_detail["行程与航线明确度"] += 4
    elif start_time == "半年内":
        score_detail["行程与航线明确度"] += 2
    score_detail["行程与航线明确度"] = min(22, score_detail["行程与航线明确度"])

    if reach_ability == "能够统一通知和组织成员":
        score_detail["组织协同与落地条件"] += 8
        tags.append("组织能力强")
        reasons.append("客户具备统一通知和组织同行人员的能力。")
    elif reach_ability == "能够部分触达成员":
        score_detail["组织协同与落地条件"] += 5
        tags.append("具备部分组织能力")
    elif reach_ability == "主要依赖个人自愿参与":
        score_detail["组织协同与落地条件"] += 2
    if group_travel == "经常需要":
        score_detail["组织协同与落地条件"] += 5
        tags.append("需要统一往返")
    elif group_travel == "偶尔需要":
        score_detail["组织协同与落地条件"] += 3
    elif group_travel == "基本不需要":
        score_detail["组织协同与落地条件"] += 1
    if len(journeys) >= 2:
        score_detail["组织协同与落地条件"] += 2
        tags.append("多行程需求")
    score_detail["组织协同与落地条件"] = min(16, score_detail["组织协同与落地条件"])

    if rights_focus:
        score_detail["合作诉求与材料配合"] += min(8, len(rights_focus) * 2)
        tags.append("支持项诉求明确")
    if "团队票支持" in rights_focus:
        score_detail["合作诉求与材料配合"] += 3
    if "票价优惠" in rights_focus:
        score_detail["合作诉求与材料配合"] += 2
    if "品牌联合推广" in rights_focus or "专属活动页面或入口" in rights_focus:
        score_detail["合作诉求与材料配合"] += 2
        tags.append("存在合作共建诉求")
    if compliance_support in ["涉及，需要", "是，需要"]:
        score_detail["合作诉求与材料配合"] += 4
        tags.append("涉及合规需求")
    elif compliance_support == "不确定":
        score_detail["合作诉求与材料配合"] += 1
    if proof_materials in ["可以提供合同 / 邀请函 / 会议通知等材料", "可以提供组织证明或成员证明", "可以提供"]:
        score_detail["合作诉求与材料配合"] += 5
        tags.append("材料可配合")
        reasons.append("客户表示可配合提供后续核实材料。")
    elif proof_materials == "视情况而定":
        score_detail["合作诉求与材料配合"] += 2
    if answers.get("cooperation_goal"):
        score_detail["合作诉求与材料配合"] += 2
    score_detail["合作诉求与材料配合"] = min(25, score_detail["合作诉求与材料配合"])

    score = int(sum(score_detail.values()))
    if score >= 80:
        match_level = "A级，高优先级合作客户"
    elif score >= 60:
        match_level = "B级，具备合作潜力客户"
    elif score >= 40:
        match_level = "C级，需进一步培育客户"
    else:
        match_level = "D级，普惠权益引导客户"

    if customer_type == "政府 / 事业单位" and compliance_support in ["是，需要", "涉及，需要"]:
        customer_segment = "公务合规型客户"
        recommended_policy = "公务出行合规支持方案"
    elif customer_type == "企业客户" and ("公务差旅" in travel_types or "商务拜访" in travel_types or ticketing_scenario == "公商务出票"):
        customer_segment = "企业差旅型客户"
        recommended_policy = "企业差旅合作方案"
    elif customer_type == "高校 / 校友会" and ("学术交流" in travel_types or "校友返校 / 校友活动" in travel_types or "校友活动" in travel_types):
        customer_segment = "高校校友合作客户"
        recommended_policy = "高校 / 校友专项出行方案"
    elif (
        customer_type == "文旅 / 会展 / 活动合作方"
        or ticketing_scenario in ["旅游团队出票", "会议会展出票"]
        or "会议会展" in travel_types
    ) and (group_travel in ["经常涉及", "偶尔涉及", "经常需要", "偶尔需要"] or ticketing_scenario in ["旅游团队出票", "会议会展出票"]):
        customer_segment = "会展文旅团队客户"
        recommended_policy = "会展团队出行支持方案"
    elif ticketing_scenario == "客户需求代订 / 渠道出票" or "长期渠道销售需求" in demand_sources:
        customer_segment = "渠道运营型客户"
        recommended_policy = "渠道会员权益共建方案"
    elif single_trip_people >= 50 and "团队票支持" in rights_focus:
        customer_segment = "团队报价客户"
        recommended_policy = "团队出行报价方案"
    else:
        customer_segment = "普通潜力客户"
        recommended_policy = "普通会员权益引导方案"

    if fixed_plan in ["暂无明确计划", ""]:
        risk_notes.append("暂未提供明确固定行程，建议人工进一步确认需求周期。")
    if reach_ability in ["主要依赖个人自愿参与", "暂不具备", ""]:
        risk_notes.append("暂未体现统一触达渠道，建议核实客户组织动员能力。")
    if proof_materials in ["暂时无法提供", ""]:
        risk_notes.append("暂无法提供证明材料，建议进入人工复核。")
    if not route_detail:
        risk_notes.append("尚未填写完整出发城市或到达城市，建议补充航线后再精确报价。")
    if not ticketing_scenario or ticketing_scenario == "其他":
        risk_notes.append("出票或合作场景仍需进一步明确，建议人工确认客户真实需求类型。")
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
    st.progress(st.session_state.step / 3)
    st.markdown(f"**第 {st.session_state.step} 步 / 共 3 步**")


def set_widget_default(key, default):
    if key not in st.session_state:
        st.session_state[key] = st.session_state.answers.get(key, default)


def collect_answers(keys):
    for key in keys:
        if key == "journeys":
            st.session_state.answers[key] = collect_journeys()
        else:
            st.session_state.answers[key] = st.session_state.get(key)


def list_to_text(value):
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            return "；".join(
                f"{idx + 1}. {item.get('departure_city', '')} 至 {item.get('arrival_cities', '')}，{item.get('travel_frequency', '')}，{item.get('group_travel', '')}"
                for idx, item in enumerate(value)
            )
        return "，".join(value)
    return value if value is not None else ""


def collect_journeys():
    journeys = []
    count = int(st.session_state.get("journey_count", 1) or 1)
    for idx in range(count):
        journey = {
            "time_preferences": st.session_state.get(f"journey_{idx}_time_preferences", []),
            "departure_city": st.session_state.get(f"journey_{idx}_departure_city", ""),
            "arrival_cities": st.session_state.get(f"journey_{idx}_arrival_cities", ""),
            "travel_frequency": st.session_state.get(f"journey_{idx}_travel_frequency", ""),
            "group_travel": st.session_state.get(f"journey_{idx}_group_travel", ""),
        }
        if any(journey.values()):
            journeys.append(journey)
    return journeys


def remove_journey(remove_idx: int):
    count = int(st.session_state.get("journey_count", 1) or 1)
    fields = ["time_preferences", "departure_city", "arrival_cities", "travel_frequency", "group_travel"]
    snapshots = []
    for idx in range(count):
        snapshots.append({field: st.session_state.get(f"journey_{idx}_{field}", [] if field == "time_preferences" else "") for field in fields})
    snapshots.pop(remove_idx)
    for idx, data in enumerate(snapshots):
        for field, value in data.items():
            st.session_state[f"journey_{idx}_{field}"] = value
    last_idx = count - 1
    for field in fields:
        st.session_state.pop(f"journey_{last_idx}_{field}", None)
    st.session_state.journey_count = max(1, count - 1)


def apply_pending_journey_removal():
    remove_idx = st.session_state.get("pending_remove_journey")
    if remove_idx is None:
        return
    st.session_state.pending_remove_journey = None
    remove_journey(int(remove_idx))


def answers_dataframe(answers: dict):
    labels = {
        "contact_name": "联系人姓名", "phone": "联系电话", "organization": "所属单位 / 组织名称",
        "role": "职务 / 角色", "city": "所在城市", "customer_type": "客户类型",
        "travel_scene": "本次出行主要场景", "single_trip_people": "本次预计同行人数",
        "companion_count_range": "同行人数区间", "fixed_plan": "行程确定度",
        "reach_ability": "是否可统一组织", "journeys": "行程信息",
        "start_time": "希望开始购票时间", "rights_focus": "最关注的支持项",
        "compliance_support": "是否涉及报销、审批或合规要求", "compliance_detail": "合规补充说明",
        "proof_materials": "是否方便提供相关材料",
        "cooperation_goal": "希望先解决的问题", "remarks": "补充信息",
    }
    return pd.DataFrame([{"字段": label, "内容": list_to_text(answers.get(key, ""))} for key, label in labels.items()])


def render_step_1_basic_info():
    st.subheader("填写基础信息")
    st.caption("快速完成客户身份确认。")
    defaults = {"contact_name": "", "phone": "", "organization": "", "role": "联系人", "city": "", "customer_type": "企业客户"}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.text_input("您的姓名 *", key="contact_name")
    st.text_input("联系方式（手机号码） *", placeholder="用于报价确认及后续沟通", key="phone")
    st.text_input("您所在的单位、组织或团队名称", key="organization")
    role_choice = st.radio("您在本次出行咨询中的身份", ["组织人", "采购人", "负责人", "联系人", "其他"], key="role")
    if role_choice == "其他":
        st.text_input("请填写您的身份", key="role_other")
    st.text_input("您所在的城市 *", key="city")
    st.radio("您所在的单位、组织或团队类型 *", ["企业客户", "政府或事业单位", "高校或校友会", "协会、商会或社团", "文旅、会展或活动合作方", "其他"], key="customer_type")


def render_step_2_travel_route_time():
    st.subheader("填写出行需求、航线与时间")
    st.caption("快速识别客户需求与规模，用于后续报价策略判断。")
    apply_pending_journey_removal()
    defaults = {"travel_scene": "公务差旅", "companion_count_range": "10-49人", "single_trip_people": 10, "fixed_plan": "有大致计划但日期未定", "reach_ability": "能够部分触达成员", "journey_count": 1, "start_time": "3个月内"}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.radio("本次出行主要属于哪种场景 *", ["公务差旅", "商务拜访", "会议会展", "团队活动", "学术交流", "校友活动", "文旅出行", "员工福利或客户答谢", "个人及家庭出行", "其他"], key="travel_scene")
    st.radio("本次预计有多少人同行 *", ["1-9人", "10-49人", "50-199人", "200人及以上", "暂不确定"], key="companion_count_range")
    st.number_input("如方便，请填写预计具体人数", min_value=1, max_value=100000, step=1, key="single_trip_people")
    st.radio("您这次的行程安排是否已经比较明确 *", ["已明确固定行程", "有大致计划但日期未定", "出行频率较高但不固定", "暂无明确计划"], key="fixed_plan")
    st.radio("是否可统一组织或通知同行人员 *", ["能够统一通知和组织成员", "能够部分触达成员", "主要依赖个人自愿参与", "暂不具备"], key="reach_ability")

    st.markdown("#### 请添加您的行程")
    count = int(st.session_state.get("journey_count", 1) or 1)
    for idx in range(count):
        with st.expander(f"行程 {idx + 1}", expanded=True):
            if count > 1 and idx > 0:
                if st.button("删除该行程", key=f"remove_journey_{idx}"):
                    st.session_state.pending_remove_journey = idx
                    st.rerun()
            if st.session_state.fixed_plan != "已明确固定行程":
                set_widget_default(f"journey_{idx}_time_preferences", [])
                st.multiselect("您更倾向于在哪些时间段出行", ["工作日", "周末", "节假日", "寒暑假", "会展或活动期间", "无固定偏好"], key=f"journey_{idx}_time_preferences")
            set_widget_default(f"journey_{idx}_departure_city", "")
            set_widget_default(f"journey_{idx}_arrival_cities", "")
            set_widget_default(f"journey_{idx}_travel_frequency", "单次")
            set_widget_default(f"journey_{idx}_group_travel", "偶尔需要")
            st.text_input("您从哪个城市出发 *", key=f"journey_{idx}_departure_city")
            st.text_input("您前往哪些城市 *", placeholder="可填写多个城市，用逗号分隔", key=f"journey_{idx}_arrival_cities")
            st.radio("类似出行需求的频率大约是", ["单次", "每周多次", "每月多次", "每季度多次", "每年数次", "不确定"], key=f"journey_{idx}_travel_frequency")
            st.radio("本次是否需要统一出发、统一返回", ["经常需要", "偶尔需要", "基本不需要", "不确定"], key=f"journey_{idx}_group_travel")
    if st.button("+ 继续添加更多行程", key="add_journey"):
        st.session_state.journey_count = count + 1
        st.rerun()
    st.radio("您希望什么时候开始购票", ["立即启动", "1个月内", "3个月内", "半年内", "暂不确定"], key="start_time")


def render_step_3_cooperation_needs():
    st.subheader("填写合作诉求")
    st.caption("辅助生成报价政策与客户画像。")
    defaults = {"rights_focus": [], "compliance_support": "不确定", "compliance_detail": "", "proof_materials": "视情况而定", "cooperation_goal": "", "remarks": "", "analysis_agreement": False}
    for key, default in defaults.items():
        set_widget_default(key, default)
    st.multiselect("您最关注哪些支持项", ["票价优惠", "行李权益", "贵宾服务", "团队票支持", "专属活动页或入口", "品牌联合推广"], key="rights_focus")
    st.radio("本次是否涉及报销、审批或合规要求", ["涉及，需要", "不涉及", "不确定"], key="compliance_support")
    if st.session_state.compliance_support in ["涉及，需要", "不确定"]:
        st.text_input("如方便，请补充说明", placeholder="例如：公务卡报销、对公结算、审批材料等", key="compliance_detail")
    st.radio("如后续需要核实信息，您是否方便提供相关材料", ["可以提供", "暂时无法提供", "视情况而定"], key="proof_materials")
    st.text_area("您这次最希望先解决什么问题", max_chars=200, key="cooperation_goal")
    st.text_area("还有哪些补充信息可以提前告诉我们", max_chars=300, key="remarks")
    st.checkbox("我同意将以上信息用于合作需求分析 *", key="analysis_agreement")


def render_home_page():
    st.markdown('<div class="hero-title">南方航空新型渠道合作客户信息收集系统</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">请选择访问身份，进入对应功能页面</div>', unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.markdown('<div class="card"><h3 style="color:#003399;margin-top:0;">客户填报入口</h3><p class="secondary-note">填写您的出行需求后，我们将为您匹配对应合作方案，并提供初步报价参考。</p></div>', unsafe_allow_html=True)
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
    st.markdown('<div class="hero-title">客户需求收集问卷</div>', unsafe_allow_html=True)
    st.markdown('<div class="hero-subtitle">填写您的出行需求后，我们将为您匹配对应合作方案，并提供初步报价参考。</div>', unsafe_allow_html=True)
    render_progress()
    step = st.session_state.step
    step_keys = {
        1: ["contact_name", "phone", "organization", "role", "city", "customer_type"],
        2: ["travel_scene", "companion_count_range", "single_trip_people", "fixed_plan", "reach_ability", "journeys", "start_time"],
        3: ["rights_focus", "compliance_support", "compliance_detail", "proof_materials", "cooperation_goal", "remarks", "analysis_agreement"],
    }
    [render_step_1_basic_info, render_step_2_travel_route_time, render_step_3_cooperation_needs][step - 1]()
    back_col, next_col = st.columns(2)
    with back_col:
        if st.button("上一步", key=f"back_{step}", disabled=step == 1):
            collect_answers(step_keys[step])
            go_back()
            st.rerun()
    with next_col:
        if step < 3:
            if st.button("下一步", key=f"next_{step}"):
                collect_answers(step_keys[step])
                if step == 1 and (not st.session_state.answers.get("contact_name") or not st.session_state.answers.get("phone") or not st.session_state.answers.get("city") or not st.session_state.answers.get("customer_type")):
                    st.warning("请填写姓名、联系方式、所在城市和单位/组织类型。")
                    return
                if step == 2 and not st.session_state.answers.get("journeys"):
                    st.warning("请至少填写一条行程信息。")
                    return
                go_next()
                st.rerun()
        elif st.button("获取报价参考 / 提交需求 / 获取合作方案", key="submit_form"):
            collect_answers(step_keys[step])
            if not st.session_state.answers.get("analysis_agreement"):
                st.warning("请先勾选同意用于合作需求分析。")
                return
            rule_result = evaluate_customer_profile(st.session_state.answers)
            with st.spinner("正在调用 DeepSeek 生成客户画像与跟进建议..."):
                st.session_state.result = enrich_customer_profile_with_ai(st.session_state.answers, rule_result)
            save_record(st.session_state.answers, st.session_state.result)
            st.session_state.saved = True
            st.session_state.page = "result"
            st.rerun()


def render_result_page():
    render_top_bar()
    answers = st.session_state.answers
    result = st.session_state.result or enrich_customer_profile_with_ai(answers, evaluate_customer_profile(answers))
    if not result.get("quote_plan"):
        result.update(generate_quote_result(answers, result))
        st.session_state.result = result
    st.success("您的需求已提交成功；我们将根据您填写的信息，为您匹配对应合作方案及报价参考；后续将由客户经理与您联系确认。")
    st.markdown('<div class="hero-title">您的报价参考</div>', unsafe_allow_html=True)
    quote_cols = st.columns(3)
    quote_values = [
        ("报价方案", result.get("quote_plan", "待客户经理确认")),
        ("大致报价区间", result.get("quote_range", "待确认")),
        ("结果置信度", result.get("quote_confidence", "中")),
    ]
    for col, (label, value) in zip(quote_cols, quote_values):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value}</div></div>', unsafe_allow_html=True)
    with st.container(border=True):
        st.write(result.get("customer_tip", "客户经理将结合实际航班、舱位、人数和出票时间，为您提供进一步报价参考。"))
    st.info("以上为初步报价参考，最终价格和权益以客户经理确认的航班、舱位、出票时间及合作材料为准。")
    st.subheader("请确认您的填报信息")
    st.dataframe(answers_dataframe(answers), use_container_width=True, hide_index=True)
    payload = {"answers": answers, "result": result, "export_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("补充信息并重新生成", key="result_edit"):
            st.session_state.page = "customer_form"
            st.session_state.step = 3
            st.rerun()
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
    ai_suggestions = parse_json_field(record.get("ai_suggestions_json", ""), "")
    ai_opportunities = parse_json_field(record.get("ai_opportunities_json", ""), [])
    ai_risk_review = parse_json_field(record.get("ai_risk_review_json", ""), [])
    ai_follow_up_questions = parse_json_field(record.get("ai_follow_up_questions_json", ""), [])
    quote_basis = parse_json_field(record.get("quote_basis_json", ""), [])
    manual_review_required = record.get("manual_review_required", "")

    overview_cols = st.columns(4)
    overview_values = [
        ("报价方案", record.get("quote_plan", "") or record.get("recommended_policy", "")),
        ("报价区间", record.get("quote_range", "") or "待确认"),
        ("置信度", record.get("quote_confidence", "") or record.get("ai_confidence", "")),
        ("人工复核", manual_review_required or ("是" if risk_notes else "否")),
    ]
    for col, (label, value) in zip(overview_cols, overview_values):
        with col:
            st.markdown(f'<div class="metric-card"><div class="metric-label">{label}</div><div class="metric-value">{value or "-"}</div></div>', unsafe_allow_html=True)

    with st.expander("客户基础信息", expanded=True):
        st.dataframe(answers_dataframe(all_answers), use_container_width=True, hide_index=True)

    with st.expander("客户画像", expanded=True):
        ai_status = record.get("ai_status", "")
        ai_confidence = record.get("ai_confidence", "")
        ai_error = record.get("ai_error", "")
        if ai_status:
            st.caption(f"AI 状态：{ai_status} | 置信度：{ai_confidence or '-'}")
        if ai_error:
            st.warning(ai_error)
        st.write(record.get("ai_profile", "") or "暂无 DeepSeek 画像。")

    with st.expander("报价建议", expanded=True):
        st.write(record.get("customer_tip", "") or "暂无客户侧报价提示。")
        if ai_suggestions:
            st.markdown("**渠道经理建议：**")
            st.write(normalize_text(ai_suggestions))
        if quote_basis:
            st.markdown("**报价依据：**")
            for item in quote_basis:
                st.write(f"- {item}")

    with st.expander("规则命中详情"):
        st.write(f"**客户分层：** {record.get('customer_segment', '')}")
        st.write(f"**匹配等级：** {record.get('match_level', '')}")
        st.write(f"**综合评分：** {record.get('score', '')}")
        if score_detail:
            score_df = pd.DataFrame(
                [{"评分维度": key, "得分": value} for key, value in score_detail.items()]
            )
            st.dataframe(score_df, use_container_width=True, hide_index=True)
        if tags:
            st.write(f"**命中标签：** {'，'.join(tags)}")
        if reason:
            st.markdown("**命中原因：**")
            for item in reason:
                st.write(f"- {item}")

    with st.expander("合作机会点"):
        if ai_opportunities:
            for item in ai_opportunities:
                st.write(f"- {item}")
        else:
            st.write("暂无")

    with st.expander("风险提示与人工复核", expanded=manual_review_required == "是"):
        st.write(f"**是否建议人工复核：** {manual_review_required or ('是' if risk_notes else '否')}")
        if risk_notes:
            st.markdown("**规则风险提示：**")
            for item in risk_notes:
                st.write(f"- {item}")
        if ai_risk_review:
            st.markdown("**DeepSeek 风险复核：**")
            for item in ai_risk_review:
                st.write(f"- {item}")

    with st.expander("建议追问客户的问题"):
        if ai_follow_up_questions:
            for item in ai_follow_up_questions:
                st.write(f"- {item}")
        else:
            st.write("暂无")

    with st.expander("跟进状态"):
        st.selectbox("当前跟进状态", ["待联系", "已联系", "补充材料中", "报价确认中", "已转合作", "暂不跟进"], key=f"follow_status_{record.get('id', '')}")
        if next_actions:
            st.markdown("**建议动作：**")
            for item in next_actions:
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
