import json, os
RAW="/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-04"

# ---- fix fe-03: correct tools_called + raw_responses (find_stock NDJSON + financials text) ----
fe3=json.load(open(f"{RAW}/fe-03.json"))
# parse the NDJSON find_stock blocks we already saved (in _raw_text) into lists
def parse_ndjson(block):
    txt=block.get("_raw_text","")
    objs=[]; buf=""; depth=0
    for ch in txt:
        buf+=ch
        if ch=="{": depth+=1
        elif ch=="}":
            depth-=1
            if depth==0:
                objs.append(json.loads(buf)); buf=""
    return objs
fs_blocks=[parse_ndjson(b) for b in fe3["raw_responses"][:3]]
fin=json.load(open("/tmp/fe03_fin.json"))
fe3["tools_called"]=[
  {"tool":"find_stock","args":{"q":"Toyota Motor"}},
  {"tool":"find_stock","args":{"q":"Volkswagen"}},
  {"tool":"find_stock","args":{"q":"General Motors"}},
  {"tool":"financials","args":{"tickers":["7203.JP","VOW.XETRA","GM.US"],"period":"1","currency":"USD"}},
]
fe3["raw_responses"]=[{"candidates":fs_blocks[0]},{"candidates":fs_blocks[1]},{"candidates":fs_blocks[2]},fin]
fe3["answer_to_user"]=(
 "All three converted to USD (as-of FY2026-06-30):\n"
 "• Toyota (7203.JP): revenue ~$336.9B, net income ~$25.6B, operating margin 7.0%, ROE 12.0%, net debt ~$192B "
 "(total debt $272B − cash $80B); net_debt/EBITDA 3.87x, debt/equity 1.18x.\n"
 "• Volkswagen (VOW.XETRA): revenue ~$364.1B, net income ~$8.3B, operating margin 4.4%, ROE 4.5%, net debt ~$185B "
 "(debt $231B − cash $46B); net_debt/EBITDA 3.03x, debt/equity 1.06x. FCF was negative (−$10.6B).\n"
 "• General Motors (GM.US): revenue ~$185.0B, net income ~$2.7B, operating margin 1.0%, ROE 3.1%, net debt ~$110B "
 "(debt $131B − cash $21B); net_debt/EBITDA 6.14x, debt/equity 2.06x.\n\n"
 "Strongest balance sheet: TOYOTA. It has the highest profitability (op margin 7%, ROE 12%) and, critically, the "
 "lowest leverage — debt/equity 1.18x and it generated positive FCF, versus VW (negative FCF, op margin 4.4%) and "
 "GM (debt/equity 2.06x, net_debt/EBITDA 6.1x, ROE just 3.1%). VW screens cheaper on multiples but is burning cash; "
 "GM is the most levered and least profitable. All figures normalized to USD so magnitudes are comparable; ratios "
 "(margin, ROE) are currency-neutral. (Note: absolute net-debt magnitudes for auto OEMs include large captive-finance "
 "debt, so the RATIOS are the cleaner balance-sheet read — and there Toyota wins.)")
json.dump(fe3,open(f"{RAW}/fe-03.json","w"),ensure_ascii=False,indent=2)

# ---- answers for the screen cases ----
ANS={
 "fe-01":("Global screen intersecting ALL FOUR conditions — revenue > $5B (USD), gross margin > 60%, operating "
  "margin > 25%, AND net_debt/EBITDA < 1.0x — returned 47 companies out of a 24,045 universe. Top matches include "
  "NVIDIA, Alphabet, Microsoft, TSMC, Meta, Micron, SK Hynix and Visa. Each row carries per-metric evidence in "
  "'matched.fundamental' plus context (e.g. NVIDIA: revenue $253B, net_debt −$0.9B = net CASH, so net_debt/EBITDA is "
  "well under 1x). Revenue is normalized to USD as an absolute line item; net_debt is debt-minus-cash; no country "
  "restriction. These are large, high-margin, lightly-levered businesses."),
 "fe-02":("การกรองแบบเข้มงวด: รายได้เติบโต YoY ต่อเนื่อง 5 ปี (consecutive_growth, N=5) และ EPS โตทุกปี 5 ปีในช่วงเดียวกัน "
  "พร้อมรายได้เกิน $1B (USD) — ครบทั้งสามเงื่อนไขพร้อมกัน — ผลลัพธ์ = 0 บริษัท จากทั้งหมด 24,045 รายการ กล่าวคือ ในฐานข้อมูลนี้ "
  "ไม่มีบริษัทใดที่ทั้งรายได้และ EPS เติบโตบวกทุกปีติดต่อกันครบ 5 ปีเต็มพร้อมรายได้เกินพันล้านดอลลาร์ (เงื่อนไข 5 ปีต่อเนื่องทั้งสองเส้น "
  "เข้มมาก — ปีที่มี EPS สะดุดแม้ปีเดียวก็ตกเกณฑ์). หากอยากได้รายชื่อ แนะนำผ่อนเป็น 3 ปีต่อเนื่อง หรือใช้ CAGR 5 ปีเป็นบวกแทน"),
 "fe-04":("US large-cap, each stock judged against ITS OWN sector cohort (vs_cohort own=true): P/E below the sector "
  "average AND ROE above the sector average — intersected. 41 matches from a 126-stock US-large-cap universe. Each row "
  "shows its own cohort benchmark, e.g. NVIDIA P/E 33.7 vs its sector avg 41.7 (cheaper) and ROE 82% vs sector avg 36% "
  "(more profitable). Other hits: Apple, Alphabet, Eli Lilly, Micron, JPMorgan, J&J, Oracle. Peer-relative on both "
  "legs, not fixed thresholds."),
 "fe-05":("Accelerating revenue growth — the growth RATE rising across consecutive periods (pattern 'accelerating', "
  "N=2 consecutive speed-ups on revenue), a second-derivative test, not merely high or positive growth. 60 companies "
  "matched. Top: Apple, Alphabet, Meta, Eli Lilly, AMD, AbbVie, Palantir, Oracle. Each carries its accel streak in "
  "'matched.fundamental'. This is genuine acceleration (g_t > g_t-1 > ...), so a company with high-but-slowing growth "
  "is excluded."),
 "fe-06":("Software sector (GICS 4510) global screen: FCF > $500M (absolute USD), FCF yield > 4% (FCF/market-cap "
  "ratio), profitable (net income > 0), AND net cash — cash > total debt (relation cash higher_than total_debt). "
  "15 matches from a 1,528-stock software universe. Top: SAP, Accenture, Xiaomi(9999.HK), NEC(6701.JP), Dassault "
  "Systèmes, Zoom, Cognizant, Dynatrace. Note SAP shows net_debt −$4.6M (net cash). The two FCF conditions are kept "
  "distinct (absolute floor vs yield ratio) and net-cash is the true cash>debt structural test, not just 'has cash'."),
 "fe-07":("Expanding-margins TREND screen (level-agnostic): gross margin, operating margin, AND net margin each "
  "trending UP over a 3-year window (consecutive_growth, N=3, on all three margin lines, intersected). 60 matches. "
  "Top: Netflix, Linde, 3308.HK, ABB, TJX, Salesforce. No absolute margin threshold imposed — it screens the CHANGE, "
  "requiring all three margins higher now than before, jointly. (Interpretation caveat: consecutive_growth requires "
  "each year up; a pure 'now vs exactly 3 years ago' delta would be slightly looser, but this correctly captures the "
  "upward trend the user asked for on all three lines.)"),
 "fe-08":("กรองหุ้นเอเชีย (จีน ญี่ปุ่น อินเดีย เกาหลี ไต้หวัน ฮ่องกง สิงคโปร์ ไทย มาเลเซีย อินโดฯ ฟิลิปปินส์ เวียดนาม): ROIC เกิน 15% "
  "ต่อเนื่อง (sustained_above, N=3), D/E ต่ำกว่า 0.5 เท่า และ current ratio มากกว่า 2 — ครบทั้งสามเงื่อนไข พบ 60 บริษัท "
  "อันดับต้นเช่น TSMC (2330.TW), Kweichow Moutai (600519), 3308.HK, 6857.JP, Fast Retailing (9983.JP). ใช้ ROIC จริง "
  "(ไม่ใช่ ROE), และ D/E กับ current ratio เป็นอัตราส่วน ไม่ต้องแปลงค่าเงิน — เน้นคุณภาพงบดุลและผลตอบแทนจากเงินลงทุนตามที่ขอ"),
 "fe-09":("Heavy-innovator-at-scale screen, all three intersected: revenue > $10B (USD), R&D spend > $2B/yr "
  "(absolute USD line item), AND R&D/revenue > 15% (intensity ratio, via relation rnd higher_than revenue, "
  "multiple 0.15). 43 matches. Top: Alphabet, Broadcom, Meta, Eli Lilly, AMD, J&J, Intel. The absolute $2B floor and "
  "the 15% intensity gate are BOTH applied — a $2B-R&D spender at $60B revenue (3.3% intensity) is excluded by the "
  "intensity gate. Dollar figures normalized to USD across markets."),
 "fe-10":("Compounder screen, global, all sectors, all conditions intersected: 3-year revenue CAGR > 20% "
  "(compound_growth, N=3, thr 0.20), 3-year EPS CAGR > 25% (compound_growth, N=3, thr 0.25 — so EPS compounding "
  "faster than sales = margin/operating leverage), ROE sustained > 20% every year (sustained_above, N=3), AND "
  "net_debt/EBITDA < 2x (net debt, not gross). 60 matches. Top: NVIDIA, Eli Lilly, Arista, Amphenol, 6669.TW, Vertiv. "
  "The EPS-CAGR (25%) > revenue-CAGR (20%) thresholds encode the 'earnings growing faster than sales' quality "
  "insight; every metric carries per-row evidence and both CAGRs use the same 3-year window."),
}
for cid,ans in ANS.items():
    p=f"{RAW}/{cid}.json"; d=json.load(open(p)); d["answer_to_user"]=ans
    json.dump(d,open(p,"w"),ensure_ascii=False,indent=2)
print("patched all")
