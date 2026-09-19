#!/usr/bin/env python
import json, os
OUT = "/Users/ran/Documents/marketdx/mcp/test-harness/raw/set-03"

answers = {
"fn-01": (
"Here are some big, well-established companies that currently look reasonably-priced, not stretched. "
"\"Not too expensive\" here means the price you pay for each dollar of the company's earnings (the P/E ratio) is BELOW the average of its large-cap peers. "
"Examples from the screen: Alphabet/Google (GOOG) trades around 17x earnings vs a peer average near 27x, plus Amazon (AMZN), Meta (META), Berkshire Hathaway (BRK-B), JPMorgan Chase (JPM), Bank of America (BAC), Exxon Mobil (XOM), Chevron (CVX), UnitedHealth (UNH) and Oracle (ORCL). "
"All are genuinely large, household-name businesses. A lower P/E just means the market is asking less for the earnings today — it does NOT guarantee the stock is 'safe' or will go up, and a low multiple can also signal slower expected growth. This is information to research further, not a recommendation to buy."
),
"fn-02": (
"These are large, established US companies that pay a solid, sustainable dividend. A dividend is a regular cash payment the company sends to shareholders out of its profits. "
"I screened for a meaningful (not sky-high) yield of 3-8%, a 10-year track record of never cutting the payout, and a payout ratio under ~75% so the dividend isn't stretched beyond what the company earns. "
"Names that came up include PepsiCo (PEP, ~4.1%), Kimberly-Clark (KMB, ~4.7%), Verizon (VZ, ~5.7%), General Mills (GIS, ~6.1%), Pfizer (PFE, ~6.1%), Prudential (PRU, ~4.6%), American Tower (AMT, ~4.0%) and Exelon (EXC, ~3.8%) — all with a 10-year no-cut streak. "
"I deliberately capped the yield to avoid \"yield traps\" (unusually high yields that often signal trouble). Important: no stock is truly risk-free — 'safe' is relative, dividends can still be cut, and prices move. This is for research, not a buy recommendation."
),
"fn-03": (
"On the numbers, Apple looks fully-priced to somewhat expensive right now, not cheap. "
"The simplest gauge is the P/E ratio — how many years of current earnings you're paying for the stock. Apple trades at about 35x earnings. That's high both versus the broad market (~mid-teens to low-20s is more typical) and richer than most of its megacap peers; several large tech names trade closer to 17-25x. "
"Why some investors still accept that price: Apple is extremely profitable and high-quality — net margin ~28%, huge free cash flow (~$99bn), return on equity that's exceptional, low debt, and earnings still growing (net income up ~20%, EPS up ~23%). So you're paying a premium for a top-tier, steady business. "
"Bottom line: by the price-vs-earnings yardstick Apple is on the expensive side of fair, justified partly by its quality — cheap it is not. This is an informational read, not a buy or sell call, and the figures are Apple's real reported numbers as of mid-2026."
),
"fn-04": (
"Here are large companies whose bottom-line profit (net income) has risen in each of the last several years — i.e. they keep making more money year after year. "
"\"Making more money every year\" here means the annual profit figure went UP every year, not just on average — so it filters out one-off spikes followed by a drop. "
"The list is full of recognizable names: Nvidia (NVDA), Alphabet/Google (GOOG), Microsoft (MSFT), Amazon (AMZN), TSMC (2330), Samsung Electronics (005930), Eli Lilly (LLY), Walmart (WMT), Visa (V) and AMD. "
"A rising profit trend is a good sign of a healthy, growing business, but note some of these (like Nvidia) grew from a chip/AI boom that may not repeat at the same pace, so past growth isn't a promise of future growth. Informational only — not advice to buy."
),
"fn-05": (
"หุ้นไทยที่ผ่านเกณฑ์ \"มั่นคง + ปันผลดี + เหมาะถือยาว\" (บริษัทใหญ่ ปันผลราว 3% ขึ้นไป จ่ายต่อเนื่องหลายปี และอัตราการจ่ายไม่ตึงเกินไป) ที่พบคือ:\n"
"• CPN (เซ็นทรัลพัฒนา) — บริษัทอสังหาฯ/ห้างค้าปลีกรายใหญ่ ปันผลราว 3.6% จ่ายต่อเนื่อง จ่ายจากกำไรเพียงประมาณ 1 ใน 3 (ยังมีเหลือลงทุนต่อ)\n"
"• AMATA (อมตะ คอร์ปอเรชัน) — เจ้าของนิคมอุตสาหกรรม ปันผลราว 4.0% เงินปันผลโตต่อเนื่อง จ่ายจากกำไรราว 1 ใน 3 เช่นกัน\n"
"เงินปันผล = เงินสดที่บริษัทแบ่งจากกำไรมาจ่ายผู้ถือหุ้นเป็นประจำ ทั้งสองตัวเป็นบริษัทใหญ่ที่รู้จักกันดีและจ่ายปันผลสม่ำเสมอ "
"ข้อควรระวัง: ไม่มีหุ้นตัวไหน \"ปลอดภัย 100%\" — ราคายังผันผวนได้และปันผลอาจถูกลด/งดในบางปี รายชื่อนี้เป็นข้อมูลไว้ศึกษาต่อ ไม่ใช่คำแนะนำให้ซื้อ "
"(หมายเหตุ: เกณฑ์ที่ค่อนข้างเข้ม—บริษัทใหญ่+จ่ายต่อเนื่อง—ทำให้เหลือชื่อไม่มาก ถ้าอยากได้ตัวเลือกกว้างขึ้นสามารถผ่อนเกณฑ์ขนาดหรือจำนวนปีที่จ่ายต่อเนื่องได้)"
),
"fn-06": (
"Here are big, strong companies that carry very little debt. \"Low debt\" here means a low debt-to-equity ratio — the company owes far less than the value of what its shareholders own. I also required above-average profitability so these are solid, not just debt-light. "
"Examples: Nvidia (NVDA, debt/equity ~0.06), Microsoft (MSFT, ~0.13), Alphabet/Google (GOOG, ~0.18), Palantir (PLTR, ~0.02), Micron (MU, ~0.06), Costco (COST, ~0.24), Lam Research (LRCX) and Arista Networks (ANET). "
"Why low debt matters for safety: a company with little debt has smaller fixed interest bills, so it's far less likely to run into trouble in a downturn or when interest rates rise — it isn't relying on borrowed money to stay afloat. "
"That said, low debt does NOT equal guaranteed safety — the business can still stumble, and the stock can still fall. This is for research, not a purchase recommendation."
),
"fn-07": (
"Here's a balanced, plain-language read on Tesla — strengths and weaknesses — without telling you whether to buy.\n"
"Strengths: It's the profitable EV leader with a strong balance sheet — very low debt (debt/equity ~0.2), plenty of cash, and free cash flow that's actually growing (up ~74%). It's a genuine, large, well-known business, not a concept.\n"
"Weaknesses / risks: Profitability has fallen sharply — net income and EPS are both down ~47% from their peak, operating margin dropped from ~17% to ~5%, and return on equity fell from ~28% to under 5%. Revenue has been roughly flat/slightly down. So the core car business has been under pressure.\n"
"Valuation: This is the big one — Tesla trades around 300x+ earnings, an extremely high price for its current profits. The market is clearly pricing in big future growth (robotaxi/AI/energy hopes) rather than today's earnings, which makes the stock sensitive to disappointment.\n"
"So: a strong, cash-rich franchise going through a profit squeeze, priced very richly on future expectations. Whether that's 'good to invest in' depends on your own view of that future and your risk tolerance — that's your call, not mine. Figures are Tesla's real reported numbers as of mid-2026; not a buy/sell recommendation."
),
"fn-08": (
"Here's a short list that tries to hit ALL four of your 'quality' tests at once — good at turning what they own into profit (high return on equity, above peer average), reasonably-priced (P/E below the peer average), growing revenue each year, and not loaded with debt. "
"Names that cleared every filter include Alphabet/Google (GOOG), Amazon (AMZN), Meta (META), Tencent (0700.HK), Chubb (CB), Progressive (PGR) and PDD Holdings (PDD). "
"Why they qualify as 'quality': e.g. Alphabet combines a fat ~55% net margin, huge free cash flow, tiny debt and a below-average ~17x P/E; Meta and Amazon show strong margins and low leverage with steady growth; the insurers (Chubb, Progressive) are steady, profitable and reasonably valued. "
"A trade-off to be honest about: it's rare for a company to be top-tier on profitability AND growth AND cheap AND debt-free — usually something gives, so treat 'cheap-ish' as relative to peers rather than an outright bargain. Informational only — not a recommendation to buy, and figures are the companies' real reported numbers."
),
"fn-09": (
"มีทางเลือกที่ความเสี่ยงต่ำกว่าหุ้นอยู่หลายแบบ ไอเดียหลักคือ ยิ่งเสี่ยงน้อย ผลตอบแทนที่คาดหวังก็มักจะน้อยตามไปด้วย (trade-off ระหว่างความปลอดภัยกับผลตอบแทน):\n"
"• พันธบัตรรัฐบาล (Government bonds) — ให้รัฐยืมเงินแล้วได้ดอกเบี้ยคืน ถือว่าเสี่ยงต่ำที่สุดกลุ่มหนึ่ง ตอนนี้พันธบัตรสหรัฐจ่ายผลตอบแทนราว 3.8% (อายุ 3 เดือน) ถึงราว 4.7% (อายุ 10 ปี) และ 5.2% (30 ปี)\n"
"• กองทุน/ETF พันธบัตร — เช่นกลุ่ม US Treasury Bond ETF (มีทั้งช่วงอายุสั้น 0-1 ปี, 1-3 ปี, 7-10 ปี ฯลฯ) ช่วยกระจายความเสี่ยงและซื้อง่ายเหมือนหุ้น\n"
"• เงินฝากประจำ/ตราสารตลาดเงิน — ปลอดภัยสูง สภาพคล่องดี แต่ผลตอบแทนต่ำ\n"
"• หุ้นปันผลบลูชิป/กองทุนดัชนีแบบกระจายความเสี่ยง — เสี่ยงกว่าพันธบัตร แต่กระจายตัวช่วยลดความผันผวนเทียบกับถือหุ้นรายตัว\n"
"สิ่งสำคัญ: ไม่มีการลงทุนใด \"การันตีไม่ขาดทุน\" 100% — แม้แต่พันธบัตรก็มีความเสี่ยงเรื่องดอกเบี้ยและเงินเฟ้อ นี่เป็นข้อมูลเพื่อศึกษาต่อ ไม่ใช่คำแนะนำให้ซื้อผลิตภัณฑ์ใดโดยเฉพาะ"
),
"fn-10": (
"Partly true — gold is widely seen as a 'safe-haven' or store-of-value, but 'always safe' is an oversimplification.\n"
"Why people trust it in scary times: it isn't tied to any one company or government, it has held value over very long periods, and it often holds up (or rises) when stocks or currencies wobble. Over the past year gold is up roughly 40% and it's in an uptrend.\n"
"The catches: gold pays you NOTHING — no dividend or interest, so it just sits there — and its PRICE can absolutely still fall (it's currently ~16% below its recent 52-week high, showing it does swing). So it's a hedge/diversifier, not a guaranteed no-loss holding.\n"
"How a beginner can get exposure: the easiest way is a gold ETF or fund (e.g. gold-tracker ETFs like the KTAM Gold ETF in Thailand or similar gold ETFs elsewhere) which you buy like a stock and which tracks the gold price; or physical gold (coins/bars/jewellery), which carries storage and security considerations. "
"Many people use gold only as a small diversifier rather than a core holding — but how much (if any) is a personal decision I won't prescribe. This is informational, not a recommendation, and the price figures are real."
),
}

for cid, ans in answers.items():
    p = os.path.join(OUT, f"{cid}.json")
    d = json.load(open(p))
    d["answer_to_user"] = ans
    json.dump(d, open(p, "w"), ensure_ascii=False, indent=2)
    print(cid, "answer set", len(ans), "chars")
