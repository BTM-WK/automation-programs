#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SPD Phase 2: Analysis Dashboard (Streamlit)
============================================
SPD 분석 결과를 시각화하는 웹 대시보드.

사용법:
    streamlit run spd_dashboard.py

Author: WKMG Automation (SPD System)
Version: 1.0.0
"""

import os
import json
import glob
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta

# ============================================================
# 설정
# ============================================================

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
ANALYSIS_DIR = os.path.join(DATA_DIR, "analysis_results")

# ============================================================
# 데이터 로드
# ============================================================

def load_analysis_results(days: int = 30) -> list:
    """최근 N일간 분석 결과 로드"""
    results = []
    if not os.path.exists(ANALYSIS_DIR):
        return results
    
    cutoff = datetime.now() - timedelta(days=days)
    
    for fpath in sorted(glob.glob(os.path.join(ANALYSIS_DIR, "*.json")), reverse=True):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            # 날짜 필터
            date_str = data.get("analysis_date", "")
            if date_str:
                try:
                    dt = datetime.fromisoformat(date_str)
                    if dt < cutoff:
                        continue
                except (ValueError, TypeError):
                    pass
            
            results.append(data)
        except Exception:
            continue
    
    return results


def results_to_dataframe(results: list) -> pd.DataFrame:
    """분석 결과를 DataFrame으로 변환"""
    rows = []
    for r in results:
        row = {
            "날짜": r.get("analysis_date", "")[:10],
            "공고명": r.get("rfp_title", "")[:50],
            "발주기관": r.get("agency", ""),
            "예산(만원)": r.get("budget_man_won", 0),
            "Go/No-Go": r.get("go_nogo", ""),
            "종합점수": r.get("total_score", 0),
            "WKMG적합도": r.get("wkmg_fit_score", 0),
            "도메인": r.get("primary_domain", ""),
            "입찰유형": r.get("bid_type", ""),
            "우선순위": r.get("priority", ""),
        }
        rows.append(row)
    
    return pd.DataFrame(rows) if rows else pd.DataFrame()


# ============================================================
# Streamlit 대시보드 UI
# ============================================================

def main():
    st.set_page_config(page_title="SPD Dashboard", layout="wide", page_icon="📊")
    st.title("📊 SPD Analysis Dashboard")
    st.caption("WKMG Strategic Proposal Development — 공고 분석 현황")
    
    # 사이드바 필터
    st.sidebar.header("🔍 필터")
    days = st.sidebar.slider("조회 기간 (일)", 7, 90, 30)
    
    # 데이터 로드
    results = load_analysis_results(days=days)
    
    if not results:
        st.warning(f"최근 {days}일간 분석 결과가 없습니다.")
        st.info("SPD Analysis Engine을 먼저 실행하세요: `python spd_analysis_engine.py`")
        return
    
    df = results_to_dataframe(results)
    
    # 요약 메트릭
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("분석 건수", len(df))
    with col2:
        go_count = len(df[df["Go/No-Go"] == "GO"])
        st.metric("GO 판정", f"{go_count}건")
    with col3:
        avg_score = df["종합점수"].mean() if len(df) > 0 else 0
        st.metric("평균 점수", f"{avg_score:.1f}")
    with col4:
        high_fit = len(df[df["WKMG적합도"] >= 80])
        st.metric("고적합도(80+)", f"{high_fit}건")
    
    st.divider()
    
    # Go/No-Go 필터
    go_filter = st.sidebar.multiselect(
        "Go/No-Go 필터",
        options=["GO", "CONDITIONAL", "NO-GO"],
        default=["GO", "CONDITIONAL"]
    )
    
    if go_filter:
        df_filtered = df[df["Go/No-Go"].isin(go_filter)]
    else:
        df_filtered = df
    
    # 메인 테이블
    st.subheader(f"📋 분석 결과 ({len(df_filtered)}건)")
    st.dataframe(
        df_filtered.sort_values("종합점수", ascending=False),
        use_container_width=True,
        hide_index=True
    )
    
    # 도메인 분포
    if len(df_filtered) > 0:
        st.subheader("📊 도메인별 분포")
        domain_counts = df_filtered["도메인"].value_counts()
        st.bar_chart(domain_counts)
    
    # 상세 보기
    st.divider()
    st.subheader("🔎 상세 분석 보기")
    
    if results:
        titles = [r.get("rfp_title", "제목없음")[:60] for r in results]
        selected_idx = st.selectbox("공고 선택", range(len(titles)), format_func=lambda i: titles[i])
        
        if selected_idx is not None:
            detail = results[selected_idx]
            
            col_a, col_b = st.columns(2)
            with col_a:
                st.write("**기본 정보**")
                st.json({
                    "공고명": detail.get("rfp_title", ""),
                    "발주기관": detail.get("agency", ""),
                    "예산": detail.get("budget_display", ""),
                    "입찰유형": detail.get("bid_type", ""),
                    "Go/No-Go": detail.get("go_nogo", ""),
                })
            
            with col_b:
                st.write("**점수 상세**")
                scores = detail.get("score_breakdown", {})
                if scores:
                    st.json(scores)
                else:
                    st.write(f"종합점수: {detail.get('total_score', 0)}")
            
            # GPT 분석 결과
            gpt_analysis = detail.get("gpt_analysis", "")
            if gpt_analysis:
                st.write("**GPT 분석 결과**")
                st.text_area("분석 내용", gpt_analysis, height=300)


if __name__ == "__main__":
    main()
