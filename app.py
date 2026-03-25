import streamlit as st
import sqlite3
import hashlib
import time
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────
DB_PATH = "marketing.db"
USERS = {
    "admin": hashlib.sha256("admin1234".encode()).hexdigest(),
}
MAX_ATTEMPTS = 3
LOCKOUT_SECONDS = 300  # 5분

st.set_page_config(
    page_title="마케팅 대시보드",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# 세션 초기화
# ──────────────────────────────────────────────
for key, default in {
    "authenticated": False,
    "failed_attempts": 0,
    "lockout_until": 0.0,
    "username": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ──────────────────────────────────────────────
# 인증
# ──────────────────────────────────────────────
def verify_password(user_id: str, password: str) -> bool:
    hashed = hashlib.sha256(password.encode()).hexdigest()
    return USERS.get(user_id) == hashed


def login_page():
    now = time.time()
    locked = st.session_state.lockout_until > now
    remaining = int(st.session_state.lockout_until - now) if locked else 0

    st.markdown(
        """
        <div style="display:flex;justify-content:center;align-items:center;min-height:80vh">
        <div style="width:400px">
        """,
        unsafe_allow_html=True,
    )

    st.markdown("## 🔐 로그인")

    if locked:
        minutes, seconds = divmod(remaining, 60)
        st.error(f"로그인 {MAX_ATTEMPTS}회 실패로 잠금 상태입니다. {minutes}분 {seconds}초 후 다시 시도해주세요.")
        st.stop()

    with st.form("login_form"):
        user_id = st.text_input("아이디", placeholder="admin")
        password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
        submitted = st.form_submit_button("로그인", use_container_width=True)

    if submitted:
        if not user_id or not password:
            st.warning("아이디와 비밀번호를 모두 입력하세요.")
        elif verify_password(user_id, password):
            st.session_state.authenticated = True
            st.session_state.username = user_id
            st.session_state.failed_attempts = 0
            st.session_state.lockout_until = 0.0
            st.rerun()
        else:
            st.session_state.failed_attempts += 1
            left = MAX_ATTEMPTS - st.session_state.failed_attempts
            if st.session_state.failed_attempts >= MAX_ATTEMPTS:
                st.session_state.lockout_until = time.time() + LOCKOUT_SECONDS
                st.error(f"로그인 {MAX_ATTEMPTS}회 실패! 5분간 잠금됩니다.")
            else:
                st.error(f"아이디 또는 비밀번호가 올바르지 않습니다. (남은 시도: {left}회)")

    st.markdown("</div></div>", unsafe_allow_html=True)


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────
@st.cache_data(ttl=60)
def load_data() -> pd.DataFrame:
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql("SELECT * FROM daily_report", conn)
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    df["cpc"] = (df["cost"] / df["clicks"]).round(0)
    df["ctr"] = (df["clicks"] / df["impressions"] * 100).round(2)
    df["cvr"] = (df["conversions"] / df["clicks"] * 100).round(2)
    df["roas"] = (df["revenue"] / df["cost"] * 100).round(1)
    return df


# ──────────────────────────────────────────────
# 숫자 포매팅
# ──────────────────────────────────────────────
def fmt_number(n):
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(int(n))


def fmt_won(n):
    return f"₩{fmt_number(n)}"


# ──────────────────────────────────────────────
# 사이드바 필터
# ──────────────────────────────────────────────
def sidebar_filters(df: pd.DataFrame) -> pd.DataFrame:
    with st.sidebar:
        st.markdown(f"**👤 {st.session_state.username}** 님 환영합니다")
        if st.button("로그아웃", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.rerun()

        st.divider()
        st.header("📌 필터")

        # 날짜 범위
        min_date = df["date"].min().date()
        max_date = df["date"].max().date()
        date_range = st.date_input(
            "기간",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        # 채널
        channels = st.multiselect(
            "채널",
            options=sorted(df["channel"].unique()),
            default=sorted(df["channel"].unique()),
        )

        # 캠페인
        available_campaigns = sorted(df[df["channel"].isin(channels)]["campaign"].unique()) if channels else []
        campaigns = st.multiselect(
            "캠페인",
            options=available_campaigns,
            default=available_campaigns,
        )

    # 필터 적용
    filtered = df.copy()
    if len(date_range) == 2:
        start, end = date_range
        filtered = filtered[(filtered["date"].dt.date >= start) & (filtered["date"].dt.date <= end)]
    if channels:
        filtered = filtered[filtered["channel"].isin(channels)]
    if campaigns:
        filtered = filtered[filtered["campaign"].isin(campaigns)]

    return filtered


# ──────────────────────────────────────────────
# 대시보드
# ──────────────────────────────────────────────
def dashboard():
    df = load_data()
    filtered = sidebar_filters(df)

    st.title("📊 마케팅 성과 대시보드")

    if filtered.empty:
        st.warning("선택한 필터 조건에 해당하는 데이터가 없습니다.")
        return

    # ── KPI 카드 ──
    total_cost = filtered["cost"].sum()
    total_revenue = filtered["revenue"].sum()
    total_conversions = filtered["conversions"].sum()
    total_clicks = filtered["clicks"].sum()
    total_impressions = filtered["impressions"].sum()
    avg_roas = (total_revenue / total_cost * 100) if total_cost > 0 else 0
    avg_ctr = (total_clicks / total_impressions * 100) if total_impressions > 0 else 0
    avg_cvr = (total_conversions / total_clicks * 100) if total_clicks > 0 else 0

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("총 비용", fmt_won(total_cost))
    kpi2.metric("총 매출", fmt_won(total_revenue))
    kpi3.metric("ROAS", f"{avg_roas:.1f}%")
    kpi4.metric("전환수", fmt_number(total_conversions))

    kpi5, kpi6, kpi7, kpi8 = st.columns(4)
    kpi5.metric("노출수", fmt_number(total_impressions))
    kpi6.metric("클릭수", fmt_number(total_clicks))
    kpi7.metric("CTR", f"{avg_ctr:.2f}%")
    kpi8.metric("CVR", f"{avg_cvr:.2f}%")

    st.divider()

    # ── 일별 추이 ──
    st.subheader("📈 일별 비용 · 매출 추이")
    daily = filtered.groupby("date").agg({"cost": "sum", "revenue": "sum"}).reset_index()
    fig_daily = go.Figure()
    fig_daily.add_trace(go.Bar(x=daily["date"], y=daily["cost"], name="비용", marker_color="#636EFA"))
    fig_daily.add_trace(go.Scatter(x=daily["date"], y=daily["revenue"], name="매출", mode="lines+markers", marker_color="#EF553B", yaxis="y2"))
    fig_daily.update_layout(
        yaxis=dict(title="비용 (₩)"),
        yaxis2=dict(title="매출 (₩)", overlaying="y", side="right"),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        height=400,
        margin=dict(l=20, r=20, t=40, b=20),
    )
    st.plotly_chart(fig_daily, use_container_width=True)

    # ── 채널 비교 ──
    col_left, col_right = st.columns(2)

    with col_left:
        st.subheader("🏷️ 채널별 비용 비중")
        channel_cost = filtered.groupby("channel")["cost"].sum().reset_index()
        fig_pie = px.pie(channel_cost, values="cost", names="channel", hole=0.4)
        fig_pie.update_layout(height=380, margin=dict(l=20, r=20, t=20, b=20))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_right:
        st.subheader("💰 채널별 ROAS")
        channel_roas = filtered.groupby("channel").agg({"cost": "sum", "revenue": "sum"}).reset_index()
        channel_roas["roas"] = (channel_roas["revenue"] / channel_roas["cost"] * 100).round(1)
        channel_roas = channel_roas.sort_values("roas", ascending=True)
        fig_roas = px.bar(channel_roas, x="roas", y="channel", orientation="h", text="roas", color="roas", color_continuous_scale="Tealgrn")
        fig_roas.update_layout(height=380, margin=dict(l=20, r=20, t=20, b=20), coloraxis_showscale=False)
        fig_roas.update_traces(texttemplate="%{text}%", textposition="outside")
        st.plotly_chart(fig_roas, use_container_width=True)

    st.divider()

    # ── 캠페인 성과 테이블 ──
    st.subheader("📋 캠페인별 성과 요약")
    campaign_summary = (
        filtered.groupby(["channel", "campaign"])
        .agg({"impressions": "sum", "clicks": "sum", "cost": "sum", "conversions": "sum", "revenue": "sum"})
        .reset_index()
    )
    campaign_summary["CTR(%)"] = (campaign_summary["clicks"] / campaign_summary["impressions"] * 100).round(2)
    campaign_summary["CVR(%)"] = (campaign_summary["conversions"] / campaign_summary["clicks"] * 100).round(2)
    campaign_summary["CPC(₩)"] = (campaign_summary["cost"] / campaign_summary["clicks"]).round(0).astype(int)
    campaign_summary["ROAS(%)"] = (campaign_summary["revenue"] / campaign_summary["cost"] * 100).round(1)
    campaign_summary = campaign_summary.rename(columns={
        "channel": "채널", "campaign": "캠페인",
        "impressions": "노출", "clicks": "클릭",
        "cost": "비용", "conversions": "전환", "revenue": "매출",
    })
    campaign_summary = campaign_summary.sort_values("ROAS(%)", ascending=False)

    st.dataframe(
        campaign_summary,
        use_container_width=True,
        hide_index=True,
        column_config={
            "비용": st.column_config.NumberColumn(format="₩%d"),
            "매출": st.column_config.NumberColumn(format="₩%d"),
        },
    )

    # ── 일별 채널 히트맵 ──
    st.subheader("🔥 일별 × 채널 전환 히트맵")
    heatmap_data = filtered.groupby([filtered["date"].dt.strftime("%m-%d"), "channel"])["conversions"].sum().reset_index()
    heatmap_data.columns = ["date", "channel", "conversions"]
    heatmap_pivot = heatmap_data.pivot(index="channel", columns="date", values="conversions").fillna(0)
    fig_heat = px.imshow(
        heatmap_pivot,
        color_continuous_scale="YlOrRd",
        labels=dict(x="날짜", y="채널", color="전환수"),
        aspect="auto",
    )
    fig_heat.update_layout(height=300, margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig_heat, use_container_width=True)


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────
if st.session_state.authenticated:
    dashboard()
else:
    login_page()
