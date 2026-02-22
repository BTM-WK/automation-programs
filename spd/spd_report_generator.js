#!/usr/bin/env node
/**
 * SPD Report Generator v1.0
 * v3 분석 JSON → DOCX 리포트 변환
 * Usage: node spd_report_generator.js <input.json> <output.docx>
 */

const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, PageBreak, LevelFormat, PageNumber
} = require("docx");

// --- 색상 팔레트 ---
const C = {
  navy: "1B365D", blue: "2E75B6", lightBlue: "D6E8F5",
  green: "28A745", lightGreen: "D4EDDA",
  yellow: "FFC107", lightYellow: "FFF3CD",
  red: "DC3545", lightRed: "F8D7DA",
  gray: "6C757D", lightGray: "F2F2F2",
  white: "FFFFFF", black: "000000",
};

const border = { style: BorderStyle.SINGLE, size: 1, color: "CCCCCC" };
const borders = { top: border, bottom: border, left: border, right: border };
const cellMargins = { top: 60, bottom: 60, left: 100, right: 100 };

function headerCell(text, width) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: C.navy, type: ShadingType.CLEAR }, margins: cellMargins, verticalAlign: "center",
    children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text, bold: true, color: C.white, font: "Arial", size: 18 })] })],
  });
}

function dataCell(text, width, opts = {}) {
  return new TableCell({
    borders, width: { size: width, type: WidthType.DXA },
    shading: { fill: opts.fill || C.white, type: ShadingType.CLEAR }, margins: cellMargins, verticalAlign: "center",
    children: [new Paragraph({ alignment: opts.align || AlignmentType.LEFT, children: [new TextRun({ text: String(text || "-"), bold: opts.bold || false, color: opts.color || C.black, font: "Arial", size: 18 })] })],
  });
}

function gradeColor(d) { if (!d) return {bg:C.lightGray,fg:C.gray}; d=d.toUpperCase(); if(d==="GO") return {bg:C.lightGreen,fg:C.green}; if(d==="CONDITIONAL") return {bg:C.lightYellow,fg:"856404"}; return {bg:C.lightRed,fg:C.red}; }
function scoreColor(s) { if(s>=75) return C.green; if(s>=55) return "856404"; return C.red; }
function gradeLabel(s) { if(s>=85) return "S"; if(s>=75) return "A"; if(s>=65) return "B+"; if(s>=55) return "B"; return "C"; }
function capIcon(c) { if(c==="상") return "●"; if(c==="중") return "◐"; return "○"; }

async function generateReport(inputPath, outputPath) {
  const raw = JSON.parse(fs.readFileSync(inputPath, "utf-8"));
  const analyses = raw.analyses || [];
  const genAt = raw.generated_at || new Date().toISOString();
  const totalAnalyzed = raw.total_analyzed || analyses.length;
  const cost = raw.total_cost_estimate || "$0";
  const promptVer = raw.prompt_version || "v3";

  const items = analyses.map((a) => {
    const gpt = a.analysis || {};
    const basic = gpt.basic_info || {};
    const scoring = gpt.scoring || {};
    const goNogo = gpt.go_no_go || {};
    const deliv = gpt.deliverables_analysis || {};
    const strategy = gpt.strategy || {};
    const similar = gpt.similar_projects_assessment || {};
    const competitive = gpt.competitive_landscape || {};
    const totalScore = scoring.total_score || 0;
    const decision = typeof goNogo === "string" ? goNogo : (goNogo.decision || "UNKNOWN");
    return { title: a.bid_title || basic.title || "제목 없음", bidNo: a.bid_number || "", agency: a.agency || "", budget: a.budget_text || "",
      totalScore, decision, grade: gradeLabel(totalScore), basic, scoring, goNogo, deliv, strategy, similar, competitive, fileCount: a.file_count || 0, rfpLength: a.rfp_text_length || 0 };
  });

  items.sort((a, b) => b.totalScore - a.totalScore);
  const goCount = items.filter(i => i.decision === "GO").length;
  const condCount = items.filter(i => i.decision === "CONDITIONAL").length;
  const nogoCount = items.filter(i => i.decision === "NO-GO").length;
  const children = [];

  // === 표지 ===
  children.push(
    new Paragraph({ spacing: { before: 2400 }, children: [] }),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 200 }, children: [
      new TextRun({ text: "SPD 분석 리포트", font: "Arial", size: 52, bold: true, color: C.navy }),
    ]}),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 100 }, children: [
      new TextRun({ text: "Strategic Procurement Dashboard — v3 Deep Analysis", font: "Arial", size: 22, color: C.gray }),
    ]}),
    new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 600 }, children: [
      new TextRun({ text: genAt.split("T")[0].replace(/-/g, "."), font: "Arial", size: 24, color: C.blue }),
    ]}),
    new Table({ width: { size: 6000, type: WidthType.DXA }, columnWidths: [2000, 2000, 2000], alignment: AlignmentType.CENTER, rows: [
      new TableRow({ children: [
        dataCell(`분석 ${totalAnalyzed}건`, 2000, { align: AlignmentType.CENTER, bold: true }),
        dataCell(`프롬프트 ${promptVer}`, 2000, { align: AlignmentType.CENTER, bold: true }),
        dataCell(`비용 ${cost}`, 2000, { align: AlignmentType.CENTER, bold: true }),
      ]}),
      new TableRow({ children: [
        dataCell(`GO ${goCount}건`, 2000, { align: AlignmentType.CENTER, color: C.green, bold: true, fill: C.lightGreen }),
        dataCell(`COND ${condCount}건`, 2000, { align: AlignmentType.CENTER, color: "856404", bold: true, fill: C.lightYellow }),
        dataCell(`NO-GO ${nogoCount}건`, 2000, { align: AlignmentType.CENTER, color: C.red, bold: true, fill: C.lightRed }),
      ]}),
    ]}),
    new Paragraph({ children: [new PageBreak()] }),
  );


  // === 1. 공고 분석 총괄표 ===
  children.push(
    new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 200, after: 200 }, children: [
      new TextRun({ text: "1. 공고 분석 총괄표", font: "Arial", bold: true }),
    ]}),
  );

  const sColW = [600, 2800, 1500, 1100, 700, 800, 860];
  const sRows = [
    new TableRow({ children: [
      headerCell("등급", sColW[0]), headerCell("공고명", sColW[1]), headerCell("발주기관", sColW[2]),
      headerCell("예산", sColW[3]), headerCell("점수", sColW[4]), headerCell("판정", sColW[5]), headerCell("커버리지", sColW[6]),
    ]}),
  ];
  items.forEach((it) => {
    const gc = gradeColor(it.decision);
    const cov = it.deliv.wkmg_coverage_pct || 0;
    sRows.push(new TableRow({ children: [
      dataCell(it.grade, sColW[0], { align: AlignmentType.CENTER, bold: true, color: scoreColor(it.totalScore) }),
      dataCell(it.title.substring(0, 40), sColW[1]),
      dataCell(it.agency, sColW[2]),
      dataCell(it.budget, sColW[3], { align: AlignmentType.RIGHT }),
      dataCell(`${it.totalScore}점`, sColW[4], { align: AlignmentType.CENTER, bold: true, color: scoreColor(it.totalScore) }),
      dataCell(it.decision, sColW[5], { align: AlignmentType.CENTER, bold: true, fill: gc.bg, color: gc.fg }),
      dataCell(`${cov}%`, sColW[6], { align: AlignmentType.CENTER }),
    ]}));
  });
  children.push(
    new Table({ width: { size: 8360, type: WidthType.DXA }, columnWidths: sColW, rows: sRows }),
    new Paragraph({ spacing: { after: 200 }, children: [] }),
    new Paragraph({ children: [new PageBreak()] }),
  );

  // === 2. 개별 공고 상세 분석 ===
  children.push(
    new Paragraph({ heading: HeadingLevel.HEADING_1, spacing: { before: 200, after: 200 }, children: [
      new TextRun({ text: "2. 개별 공고 상세 분석", font: "Arial", bold: true }),
    ]}),
  );

  items.forEach((it, idx) => {
    const gc = gradeColor(it.decision);
    const goSec = typeof it.goNogo === "object" ? it.goNogo : {};
    const decReason = goSec.decision_reason || "";

    // 공고 헤더
    children.push(
      new Paragraph({ heading: HeadingLevel.HEADING_2, spacing: { before: 300, after: 100 }, children: [
        new TextRun({ text: `[${it.grade}] ${it.title}`, font: "Arial", bold: true }),
      ]}),
    );

    // 기본 정보 테이블
    const iW = [2000, 6360];
    const infoData = [
      ["공고번호", it.bidNo], ["발주기관", it.agency], ["추정예산", it.budget],
      ["GPT 점수", `${it.totalScore}/100`], ["Go/No-Go", it.decision],
      ["사업 유형", it.basic.bid_type || ""], ["핵심 요약", it.basic.summary || ""],
    ];
    const iRows = infoData.map(([l, v]) => new TableRow({ children: [
      dataCell(l, iW[0], { bold: true, fill: C.lightGray }),
      dataCell(v, iW[1], l === "Go/No-Go" ? { bold: true, fill: gc.bg, color: gc.fg } : {}),
    ]}));
    children.push(new Table({ width: { size: 8360, type: WidthType.DXA }, columnWidths: iW, rows: iRows }));
    children.push(new Paragraph({ spacing: { after: 150 }, children: [] }));

    // 4영역 채점 테이블
    const scW = [2200, 800, 5360];
    const scFields = [
      { label: "도메인 전문성", key: "domain_expertise" },
      { label: "수행실적 매칭", key: "track_record" },
      { label: "경쟁우위", key: "competitive_edge" },
      { label: "수주 가능성", key: "win_probability" },
    ];
    const scRows = [new TableRow({ children: [
      headerCell("평가영역", scW[0]), headerCell("점수", scW[1]), headerCell("판단 근거", scW[2]),
    ]})];
    scFields.forEach((sf) => {
      const s = it.scoring[sf.key] || {};
      scRows.push(new TableRow({ children: [
        dataCell(sf.label, scW[0], { bold: true }),
        dataCell(`${s.score||0}/25`, scW[1], { align: AlignmentType.CENTER, bold: true, color: scoreColor((s.score||0)*4) }),
        dataCell((s.reason||"-").substring(0, 100), scW[2]),
      ]}));
    });
    scRows.push(new TableRow({ children: [
      dataCell("합계", scW[0], { bold: true, fill: C.lightGray }),
      dataCell(`${it.totalScore}/100`, scW[1], { align: AlignmentType.CENTER, bold: true, color: scoreColor(it.totalScore), fill: C.lightGray }),
      dataCell(decReason.substring(0, 100), scW[2], { fill: C.lightGray }),
    ]}));
    children.push(
      new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ 4영역 채점 상세", font: "Arial", size: 20, bold: true, color: C.navy })] }),
      new Table({ width: { size: 8360, type: WidthType.DXA }, columnWidths: scW, rows: scRows }),
      new Paragraph({ spacing: { after: 150 }, children: [] }),
    );

    // 세부 과업 분석 (deliverables_analysis)
    const dItems = (it.deliv.items || []);
    if (dItems.length > 0) {
      const dW = [2600, 600, 4160, 1000];
      const dRows = [new TableRow({ children: [
        headerCell("세부 과업/산출물", dW[0]), headerCell("역량", dW[1]), headerCell("판단 근거", dW[2]), headerCell("파트너", dW[3]),
      ]})];
      dItems.forEach((d) => {
        const cap = d.wkmg_capability || "하";
        const cc = cap === "상" ? C.green : cap === "중" ? "856404" : C.red;
        dRows.push(new TableRow({ children: [
          dataCell(d.deliverable || "-", dW[0]),
          dataCell(`${capIcon(cap)} ${cap}`, dW[1], { align: AlignmentType.CENTER, color: cc, bold: true }),
          dataCell((d.capability_reason || "-").substring(0, 80), dW[2]),
          dataCell(d.needs_partner ? (d.partner_type || "필요") : "-", dW[3], { align: AlignmentType.CENTER }),
        ]}));
      });
      const cov = it.deliv.wkmg_coverage_pct || 0;
      children.push(
        new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: `▸ 세부 과업 분석 (${dItems.length}개 / WKMG 커버리지 ${cov}%)`, font: "Arial", size: 20, bold: true, color: C.navy })] }),
        new Table({ width: { size: 8360, type: WidthType.DXA }, columnWidths: dW, rows: dRows }),
        new Paragraph({ spacing: { after: 150 }, children: [] }),
      );
    }

    // 전략 요약
    const st = it.strategy;
    if (st && st.core_message) {
      children.push(new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ 제안 전략", font: "Arial", size: 20, bold: true, color: C.navy })] }));
      const stW = [2000, 6360];
      const stR = [];
      stR.push(new TableRow({ children: [dataCell("핵심 메시지", stW[0], { bold: true, fill: C.lightGray }), dataCell(st.core_message || "-", stW[1])] }));
      if (st.top3_emphasis) stR.push(new TableRow({ children: [dataCell("강조 포인트", stW[0], { bold: true, fill: C.lightGray }), dataCell((st.top3_emphasis||[]).join(" / "), stW[1])] }));
      if (st.evaluator_concerns) stR.push(new TableRow({ children: [dataCell("약점/우려", stW[0], { bold: true, fill: C.lightGray }), dataCell((st.evaluator_concerns||[]).join(" / "), stW[1])] }));
      if (st.needed_partners && st.needed_partners.length > 0) stR.push(new TableRow({ children: [dataCell("필요 파트너", stW[0], { bold: true, fill: C.lightGray }), dataCell((st.needed_partners||[]).join(", "), stW[1])] }));
      if (st.proposal_pages) stR.push(new TableRow({ children: [dataCell("제안서 분량", stW[0], { bold: true, fill: C.lightGray }), dataCell(`${st.proposal_pages} / 준비기간 ${st.prep_days||"?"}일`, stW[1])] }));
      children.push(new Table({ width: { size: 8360, type: WidthType.DXA }, columnWidths: stW, rows: stR }), new Paragraph({ spacing: { after: 150 }, children: [] }));
    }

    // 유사 프로젝트
    if (it.similar.best_match) {
      children.push(
        new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ 유사 프로젝트", font: "Arial", size: 20, bold: true, color: C.navy })] }),
        new Paragraph({ spacing: { after: 50 }, children: [new TextRun({ text: `최적 매칭: ${it.similar.best_match}`, font: "Arial", size: 18 })] }),
      );
      if (it.similar.reusable_assets && it.similar.reusable_assets.length > 0) {
        children.push(new Paragraph({ spacing: { after: 50 }, children: [new TextRun({ text: `재활용 자산: ${it.similar.reusable_assets.join(", ")}`, font: "Arial", size: 18, color: C.gray })] }));
      }
    }

    // 경쟁 환경
    if (it.competitive.wkmg_unique_selling_point) {
      children.push(
        new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ 경쟁 환경", font: "Arial", size: 20, bold: true, color: C.navy })] }),
        new Paragraph({ spacing: { after: 50 }, children: [new TextRun({ text: `WKMG USP: ${it.competitive.wkmg_unique_selling_point}`, font: "Arial", size: 18 })] }),
      );
    }

    // Go/No-Go 조건 (CONDITIONAL)
    const conds = goSec.conditions || [];
    if (it.decision === "CONDITIONAL" && conds.length > 0) {
      children.push(new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ GO 전환 조건", font: "Arial", size: 20, bold: true, color: "856404" })] }));
      conds.forEach((c, ci) => {
        children.push(new Paragraph({ spacing: { after: 30 }, children: [new TextRun({ text: `  ${ci+1}. ${c}`, font: "Arial", size: 18 })] }));
      });
    }

    // NO-GO 사유
    const nogoReasons = goSec.nogo_reasons || [];
    if (it.decision === "NO-GO" && nogoReasons.length > 0) {
      children.push(new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ NO-GO 사유", font: "Arial", size: 20, bold: true, color: C.red })] }));
      nogoReasons.forEach((r, ri) => {
        children.push(new Paragraph({ spacing: { after: 30 }, children: [new TextRun({ text: `  ${ri+1}. ${r}`, font: "Arial", size: 18, color: C.red })] }));
      });
    }

    // Action Items
    const actions = (it.strategy.action_items || []);
    if (actions.length > 0) {
      const aW = [3500, 800, 1200, 860];
      const aRows = [new TableRow({ children: [
        headerCell("행동", aW[0]), headerCell("우선순위", aW[1]), headerCell("시점", aW[2]), headerCell("담당", aW[3]),
      ]})];
      actions.forEach((act) => {
        const pc = act.priority === "HIGH" ? C.red : act.priority === "MEDIUM" ? "856404" : C.gray;
        aRows.push(new TableRow({ children: [
          dataCell(act.action || "-", aW[0]),
          dataCell(act.priority || "-", aW[1], { align: AlignmentType.CENTER, bold: true, color: pc }),
          dataCell(act.deadline || "-", aW[2], { align: AlignmentType.CENTER }),
          dataCell(act.owner || "-", aW[3], { align: AlignmentType.CENTER }),
        ]}));
      });
      children.push(
        new Paragraph({ spacing: { before: 100 }, children: [new TextRun({ text: "▸ Action Items", font: "Arial", size: 20, bold: true, color: C.navy })] }),
        new Table({ width: { size: 6360, type: WidthType.DXA }, columnWidths: aW, rows: aRows }),
        new Paragraph({ spacing: { after: 150 }, children: [] }),
      );
    }

    // 페이지 구분
    if (idx < items.length - 1) children.push(new Paragraph({ children: [new PageBreak()] }));
  });

  // === 푸터 & 문서 빌드 ===
  const footer = new Footer({ children: [
    new Paragraph({ alignment: AlignmentType.CENTER, children: [
      new TextRun({ text: "WKMG Strategic Procurement Dashboard — SPD v3.0 | ", font: "Arial", size: 14, color: C.gray }),
      new TextRun({ children: [PageNumber.CURRENT], font: "Arial", size: 14, color: C.gray }),
    ]}),
  ]});

  const doc = new Document({
    styles: {
      default: { document: { run: { font: "Arial", size: 20 } } },
      paragraphStyles: [
        { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 32, bold: true, font: "Arial", color: C.navy },
          paragraph: { spacing: { before: 240, after: 200 }, outlineLevel: 0 }},
        { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
          run: { size: 26, bold: true, font: "Arial", color: C.blue },
          paragraph: { spacing: { before: 200, after: 150 }, outlineLevel: 1 }},
      ],
    },
    sections: [{
      properties: {
        page: { size: { width: 11906, height: 16838 }, margin: { top: 1200, right: 1200, bottom: 1200, left: 1200 } },
      },
      footers: { default: footer },
      children,
    }],
  });

  const buffer = await Packer.toBuffer(doc);
  fs.writeFileSync(outputPath, buffer);
  console.log(`✅ DOCX 리포트 생성: ${outputPath} (${items.length}건, ${buffer.length} bytes)`);
}

// --- CLI ---
const args = process.argv.slice(2);
if (args.length < 2) { console.log("Usage: node spd_report_generator.js <input.json> <output.docx>"); process.exit(1); }
generateReport(args[0], args[1]).catch((err) => { console.error("❌ 리포트 생성 실패:", err.message); process.exit(1); });
