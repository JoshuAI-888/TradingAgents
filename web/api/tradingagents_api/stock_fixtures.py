"""Recorded stock-page payloads (fixture mode: TA_STOCK_FIXTURES=1).

Shapes mirror the live moomoo responses field-for-field (verified in the
exploration POC + the CHE-US page inventory, 2026-09-27) so the portal renders
identically with and without moomoo keys. Values are the real CHE-US figures
captured from the live page; where the handbook does not itemize a list's
members (capital flow_list), the moomoo docs convention {time, in_flow,
out_flow} is used.
"""
from __future__ import annotations

_MS_DAY = 86_400_000


def _quote(symbol: str) -> dict:
    return {
        "code": f"US.{symbol}", "name": "Chemed", "sc_name": "Chemed", "tc_name": "Chemed",
        "update_time": 1758835200000, "data_date": "2026-09-25",
        "last_price": 512.16, "open_price": 503.12, "high_price": 514.51, "low_price": 498.79,
        "prev_close_price": 495.65, "close_price_5min": 512.16,
        "volume": 233290, "turnover": 118540000.0, "turnover_rate": 1.97,
        "amplitude": 3.17, "volume_ratio": 1.32, "bid_ask_ratio": 46.2,
        "sec_status": "NORMAL", "dark_status": "NORMAL",
        "listing_date": 424358400000, "bid_price": 512.0, "ask_price": 512.16,
        "bid_vol": 100, "ask_vol": 300, "price_spread": 0.16,
        "highest52weeks_price": 556.268, "lowest52weeks_price": 364.227,
        "highest_history_price": 647.466, "lowest_history_price": 9.502,
        "suspension": False, "avg_price": 508.133, "lot_size": 1,
        "equity_valid": True, "index_valid": False, "plate_valid": False,
        "wrt_valid": False, "trust_valid": False, "option_valid": False, "future_valid": False,
        "issued_shares": 13020000, "total_market_val": 6670000000.0,
        "outstanding_shares": 11854000, "circular_market_val": 6070000000.0,
        "pe_ratio": 27.93, "pe_ttm_ratio": 25.76, "pb_ratio": 8.03,
        "dividend_ttm": 2.40, "dividend_ratio_ttm": 0.47,
        "dividend_lfy": 2.40, "dividend_ratio_lfy": 0.48,
        "net_asset": 830000000.0, "net_asset_per_share": 63.75,
        "net_profit": 239000000.0, "ey_ratio": 3.58, "earning_per_share": 18.34,
        "pct_change": 3.33,
        # Live REST snapshot: flat session fields (the nested pre_market{}/
        # after_market{} shape belongs to the WebSocket QUOTE push).
        "pre_price": 512.16, "pre_change_rate": 0.0, "pre_change_val": 0.0,
        "pre_high_price": 512.16, "pre_low_price": 512.16,
        "pre_volume": 0, "pre_turnover": 0.0, "pre_amplitude": 0.0,
        "after_price": 512.16, "after_change_rate": 0.0, "after_change_val": 0.0,
        "after_high_price": 512.16, "after_low_price": 512.16,
        "after_volume": 4300, "after_turnover": 2203000.0, "after_amplitude": 0.0,
        "overnight_price": 0, "overnight_change_rate": 0, "overnight_volume": 0,
        "overnight_turnover": 0.0,
    }


def _kline(n: int, base: float = 512.16, seed: int = 3) -> list:
    """n daily bars ending at the recorded close; deterministic wobble."""
    out = []
    price = base * (1 - 0.18)
    t = 1758835200000 - n * _MS_DAY
    for i in range(n):
        w = ((i * seed + 7) % 13 - 6) / 220
        o = price
        price = round(price * (1 + 0.0011 + w / n), 3)
        h = round(max(o, price) * 1.004, 3)
        lo = round(min(o, price) * 0.996, 3)
        v = 160000 + (i * 9973) % 210000
        out.append({"time_key": t + i * _MS_DAY, "date": 0, "time_zone": -300,
                    "open": round(o, 3), "close": price, "high": h, "low": lo,
                    "volume": v, "turnover": round(v * price, 2),
                    "last_close": round(o, 3), "turnover_rate": 1.4,
                    "change_rate": round((price / o - 1) * 100, 2)})
    return out


def _rt_points() -> list:
    pts = []
    t0 = 1758802200000  # 09:30 ET
    for i in range(391):
        w = ((i * 31) % 17 - 8) / 900
        p = round(503.12 * (1 + w + i / 391 * 0.018), 3)
        pts.append({"time": t0 + i * 60000, "open": p, "high": round(p * 1.0008, 3),
                    "low": round(p * 0.9992, 3), "cur_price": p,
                    "volume": 380 + (i * 7717) % 2600, "turnover": round(p * 900, 2)})
    return pts


def _chain(symbol: str) -> list:
    strikes = [440, 450, 460, 470, 480, 490, 500, 510, 520, 530]
    rows = []
    for s in strikes:
        for kind, tag in (("CALL", "C"), ("PUT", "P")):
            code = f"{symbol}261016{tag}{int(s * 1000):06d}-US"
            rows.append({"code": code, "stock_id": 0, "name": f"Chemed {tag}{s}",
                         "stock_type": "DRVT", "option_type": kind,
                         "stock_owner": f"US.{symbol}", "strike_time": "2026-10-16",
                         "strike_price": float(s), "lot_size": 100,
                         "index_option_type": "N/A", "expiration_cycle": "MONTHLY",
                         "option_standard_type": "STANDARD"})
    return rows


def _chain_quotes(symbol: str) -> dict:
    px = 60.0
    out = []
    for row in _chain(symbol):
        s = row["strike_price"]
        base = max(2.0, 512.16 - s) if row["option_type"] == "CALL" else max(2.0, s - 512.16)
        last = round(base + (s % 7) / 9, 3)
        out.append({"code": row["code"], "last_price": last,
                    "prev_close_price": round(last * 0.98, 3),
                    "pct_change": 2.04, "bid_price": round(last - 0.6, 2),
                    "ask_price": round(last + 0.6, 2), "volume": int(s * 13) % 420,
                    "turnover": round(last * (s * 13) % 420 * 100, 2),
                    "option_open_interest": int(s * 31) % 1900,
                    "option_implied_volatility": 24.6,
                    "delta": 0.55 if row["option_type"] == "CALL" else -0.45})
    return {"snapshot_list": out}


def _statement(period: str, fin_type: int) -> dict:
    rows = [
        ("Total Revenue", [673.25, 657.51, 639.34, 624.90, 618.80, 646.94, 639.99, 606.18]),
        ("Gross Profit", [221.47, 215.76, 225.17, 196.91, 184.69, 216.41, 234.12, 209.99]),
        ("Operating Profit", [89.20, 84.58, 103.56, 74.75, 68.08, 94.76, 114.32, 92.16]),
        ("Net Profit", [67.70, 66.30, 76.75, 64.24, 52.49, 71.76, 90.32, 75.78]),
        ("Basic EPS", [5.14, 4.85, 5.48, 4.46, 3.60, 4.91, 6.08, 5.04]),
        ("Diluted EPS", [5.13, 4.84, 5.48, 4.46, 3.57, 4.86, 6.02, 5.00]),
        ("Dividend Per Share", [0.60, 0.60, 0.60, 0.60, 0.50, 0.50, 0.50, 0.50]),
    ]
    periods = ["2026/Q2", "2026/Q1", "2025/Q4", "2025/Q3", "2025/Q2", "2025/Q1",
               "2024/Q4", "2024/Q3"]
    idx = periods.index(period)
    items = []
    for name, vals in rows:
        v = vals[idx]
        yoy = round((v / vals[idx + 4] - 1) * 100, 2) if idx + 4 < len(vals) else None
        items.append({"field_id": name.upper().replace(" ", "_"), "display_name": name,
                      "value": v, "yoy": yoy, "qoq": None})
    return {"date_time": 1751328000000, "fiscal_year": int(period[:4]),
            "financial_type": fin_type, "structure": 1, "structure_name": "NORMAL_US",
            "period_text": period, "currency_code": "USD",
            "accounting_standards": "US_GAAP", "auditor_report": "", "item_list": items}


def payload(key: str, symbol: str):
    """Fixture for an API fetch key; None → unknown key (route 404s/available=false)."""
    S = symbol.upper().removesuffix("-US")
    quotes = {"quote": _quote(S),
              "candles:5D": {"kline_list": _kline(65, seed=11)},
              "candles:D": {"kline_list": _kline(370)},
              "candles:W": {"kline_list": _kline(160, seed=5)},
              "candles:M": {"kline_list": _kline(48, seed=9)},
              "candles:Q": {"kline_list": _kline(63)},
              "candles:Y": {"kline_list": _kline(370, seed=2)},
              "intraday": {"symbol": f"US.{S}", "last_close": 495.65, "cur_price": 512.16,
                           "volume_precision": 0, "open": 503.12, "high": 514.51,
                           "low": 498.79, "volume": 233290, "turnover": 118540000.0,
                           "section_list": [{"section": "NORMAL",
                                             "point_list": _rt_points()}]},
              "capital:intraday": {"flow_list": [
                  {"time": 1758802200000 + i * 600000, "in_flow": 52000 + (i * 613) % 40000,
                   "out_flow": 41000 + (i * 397) % 36000} for i in range(39)],
                  "last_valid_time": 1758834900000},
              "capital:day": {"flow_list": [
                  {"time": 1758835200000 - i * _MS_DAY,
                   "in_flow": 8405340 - i * 51300, "out_flow": 6168200 - i * 42100}
                  for i in range(60)]},
              "capital:week": {"flow_list": [
                  {"time": 1758835200000 - i * 7 * _MS_DAY,
                   "in_flow": 39000000 - i * 821000, "out_flow": 31000000 - i * 660000}
                  for i in range(52)]},
              "capital:month": {"flow_list": [
                  {"time": 1758835200000 - i * 30 * _MS_DAY,
                   "in_flow": 168000000 - i * 3200000, "out_flow": 139000000 - i * 2700000}
                  for i in range(24)]},
              "distribution": {"capital_in_super": 2237140.0, "capital_in_big": 2834110.0,
                               "capital_in_mid": 1901340.0, "capital_in_small": 1430750.0,
                               "capital_out_super": 1210830.0, "capital_out_big": 2003540.0,
                               "capital_out_mid": 1613420.0, "capital_out_small": 1338410.0,
                               "update_time": 1758834900000},
              "expirations": {"expiration_list": [
                  {"strike_time": "2026-10-16", "option_expiry_date_distance": 19,
                   "expiration_cycle": "MONTHLY"},
                  {"strike_time": "2026-11-20", "option_expiry_date_distance": 54,
                   "expiration_cycle": "MONTHLY"},
                  {"strike_time": "2026-12-18", "option_expiry_date_distance": 82,
                   "expiration_cycle": "MONTHLY"},
                  {"strike_time": "2027-03-19", "option_expiry_date_distance": 173,
                   "expiration_cycle": "QUARTERLY"}]},
              "chain": {"option_chain": _chain(S)},
              "chain-quotes": _chain_quotes(S),
              "statements:1:102": [_statement("2026/Q2", 102), _statement("2026/Q1", 102),
                                   _statement("2025/Q4", 102), _statement("2025/Q3", 102),
                                   _statement("2025/Q2", 102), _statement("2025/Q1", 102),
                                   _statement("2024/Q4", 102), _statement("2024/Q3", 102)],
              "statements:1:7": [_statement("2026/Q2", 7), _statement("2025/Q2", 7)],
              "statements:2:102": [_statement("2026/Q2", 102), _statement("2026/Q1", 102),
                                   _statement("2025/Q4", 102), _statement("2025/Q3", 102)],
              "statements:3:102": [_statement("2026/Q2", 102), _statement("2026/Q1", 102)],
              "statements:4:102": [{"date_time": 1751328000000, "fiscal_year": 2026,
                  "financial_type": 102, "structure": 1, "structure_name": "NORMAL_US",
                  "period_text": period, "currency_code": "USD",
                  "accounting_standards": "US_GAAP", "auditor_report": "",
                  "item_list": [
                      {"field_id": "EPS", "display_name": "EPS", "value": v[0], "yoy": v[1],
                       "qoq": None},
                      {"field_id": "FCF", "display_name": "Free Cash Flow", "value": v[2],
                       "yoy": v[3], "qoq": None},
                      {"field_id": "CURRENT_RATIO", "display_name": "Current Ratio",
                       "value": v[4], "yoy": v[5], "qoq": None},
                      {"field_id": "QUICK_RATIO", "display_name": "Quick Ratio",
                       "value": v[6], "yoy": v[7], "qoq": None},
                      {"field_id": "ROE", "display_name": "ROE", "value": v[8], "yoy": v[9],
                       "qoq": None},
                      {"field_id": "ROA", "display_name": "ROA", "value": v[10],
                       "yoy": v[11], "qoq": None},
                      {"field_id": "GROSS_MARGIN", "display_name": "Gross Margin",
                       "value": v[12], "yoy": v[13], "qoq": None},
                      {"field_id": "NET_MARGIN", "display_name": "Net Margin",
                       "value": v[14], "yoy": v[15], "qoq": None}]}
                  for period, v in [
                      ("2026/Q2", [5.13, 43.7, 69.29e6, -43.57, 0.91, -51.1, 0.72, -56.57,
                                   8.07, 82.9, 4.35, 42.59, 32.90, 10.21, 10.06, 18.54]),
                      ("2026/Q1", [4.84, -0.41, 71.10e6, 265.31, 0.85, -50.69, 0.72, -54.32,
                                   7.26, 16.33, 4.31, 2.05, 32.82, -1.9, 10.08, -9.09]),
                      ("2025/Q4", [5.48, -8.97, 117.19e6, -22.98, 1.05, -23.72, 0.90, -26.81,
                                   7.47, -2.68, 4.85, -7.6, 35.22, -3.72, 12.00, -14.94]),
                      ("2025/Q3", [4.46, -10.8, 66.03e6, -14.14, 1.35, -26.93, 1.18, -28.01,
                                   5.65, -8.97, 3.84, -11.09, 31.51, -9.04, 10.28, -17.77])]],
              "statements:4:7": [{"date_time": 1751328000000, "fiscal_year": 2026,
                  "financial_type": 7, "structure": 1, "structure_name": "NORMAL_US",
                  "period_text": "2026/Q2", "currency_code": "USD",
                  "accounting_standards": "US_GAAP", "auditor_report": "",
                  "item_list": [{"field_id": "EPS", "display_name": "EPS", "value": 20.29,
                                 "yoy": 30.1, "qoq": None}]}],
              "revenue": {"period": "2025/FY", "currency_code": "USD",
                          "breakdown_list": [
                              {"type": 8, "item_list": [
                                  {"name": "VITAS", "main_oper_income": 1654900000.0,
                                   "ratio": 65.4},
                                  {"name": "Roto-Rooter", "main_oper_income": 875080000.0,
                                   "ratio": 34.6}]},
                              {"type": 4, "item_list": [
                                  {"name": "United States",
                                   "main_oper_income": 2529978000.0, "ratio": 100.0}]}],
                          "screen_date_list": [
                              {"date": 1767110400, "financial_type": 7,
                               "period_text": "2025/FY"},
                              {"date": 1735574400, "financial_type": 7,
                               "period_text": "2024/FY"},
                              {"date": 1703952000, "financial_type": 7,
                               "period_text": "2023/FY"}]},
              "earnings-history": {"records": [
                  {"fiscal_year": 2026, "financial_type": 102, "period_text": "2026/Q2",
                   "is_current": True, "pub_trading_day": 1753651200000,
                   "pub_trading_day_str": "2026-07-28", "pub_time": 1753704000,
                   "pub_type": 1, "open_price": 551.541, "close_price": 551.551,
                   "highest_price": 558.542, "lowest_price": 524.31,
                   "last_close_price": 552.18, "predict_vola_v": 6.1},
                  {"fiscal_year": 2026, "financial_type": 102, "period_text": "2026/Q1",
                   "is_current": False, "pub_trading_day": 1745452800000,
                   "pub_trading_day_str": "2026-04-23", "pub_time": 1745505600,
                   "pub_type": 1, "open_price": 530.1, "close_price": 542.77,
                   "highest_price": 546.0, "lowest_price": 525.2,
                   "last_close_price": 528.4, "predict_vola_v": 5.4},
                  {"fiscal_year": 2025, "financial_type": 102, "period_text": "2025/Q4",
                   "is_current": False, "pub_trading_day": 1740435200000,
                   "pub_trading_day_str": "2026-02-25", "pub_time": 1740488000,
                   "pub_type": 1, "open_price": 512.0, "close_price": 507.9,
                   "highest_price": 517.3, "lowest_price": 502.1,
                   "last_close_price": 513.6, "predict_vola_v": 5.0}]},
              "research": {"consensus": {"rating": 4, "total": 4, "strong_buy": 0.0,
                                         "buy": 50.0, "hold": 50.0, "underperform": 0.0,
                                         "sell": 0.0, "average": 584.5, "highest": 650.0,
                                         "lowest": 548.0, "num_of_target_analysts": 4,
                                         "update_time": 1758888000,
                                         "update_time_str": "2026-09-26"},
                           "detail": {"pagination": {"has_more": False, "next_key": "-1",
                                                     "total": 4},
                                      "inst_rating_summary_list": [
                  {"institution_info": {"institution_uid": 1,
                                        "institution_name": "UBS", "num_of_stars": 4,
                                        "success_rate": 60.6},
                   "rating_item_list": [{"rating": 3, "target_price": 650.0,
                                         "recommendation_date_str": "2026-09-25"}]},
                  {"institution_info": {"institution_uid": 2,
                                        "institution_name": "BofA Securities",
                                        "num_of_stars": 3, "success_rate": 51.9},
                   "rating_item_list": [{"rating": 2, "target_price": 550.0,
                                         "recommendation_date_str": "2026-09-18"}]},
                  {"institution_info": {"institution_uid": 3,
                                        "institution_name": "Oppenheimer",
                                        "num_of_stars": 4, "success_rate": 58.0},
                   "rating_item_list": [{"rating": 3, "target_price": 590.0,
                                         "recommendation_date_str": "2026-08-01"}]},
                  {"institution_info": {"institution_uid": 4,
                                        "institution_name": "RBC Capital",
                                        "num_of_stars": 3, "success_rate": 54.2},
                   "rating_item_list": [{"rating": 2, "target_price": 548.0,
                                         "recommendation_date_str": "2026-07-30"}]}]}},
              "news:1": {"news_list": [
                  {"news_id": "post:1000217104", "news_type": "POST",
                   "title": "UBS Initiates Chemed(CHE.US) With Buy Rating, Announces Target Price $650",
                   "publish_time": 1758826380, "url": "https://www.moomoo.com/news/post/1000217104",
                   "img_url": ""},
                  {"news_id": "post:76545401", "news_type": "POST",
                   "title": "Chemed Insider Sold Shares Worth $1,002,800, According to a Recent SEC Filing",
                   "publish_time": 1758521280, "url": "https://www.moomoo.com/news/post/76545401",
                   "img_url": ""},
                  {"news_id": "post:76360946", "news_type": "POST",
                   "title": "Press Release: Roto-Rooter Buys Largest Franchisee Territory",
                   "publish_time": 1758093000, "url": "https://www.moomoo.com/news/post/76360946",
                   "img_url": ""}]},
              "news:2": {"news_list": [
                  {"news_id": "notice:1000190933", "news_type": "NOTICE",
                   "title": "Chemed | 144: Notice of proposed sale of securities pursuant to Rule 144",
                   "publish_time": 1758779160, "url": "https://www.moomoo.com/news/notice/1000190933",
                   "img_url": ""},
                  {"news_id": "notice:308166859", "news_type": "NOTICE",
                   "title": "Chemed | 4: Statement of changes in beneficial ownership of securities-Officer MCNAMARA KEVIN J",
                   "publish_time": 1758519900, "url": "https://www.moomoo.com/news/notice/308166859",
                   "img_url": ""},
                  {"news_id": "notice:307811902", "news_type": "NOTICE",
                   "title": "10-Q: Chemed | 10-Q: Q2 2026 Earnings Report",
                   "publish_time": 1754006700, "url": "https://www.moomoo.com/news/notice/307811902",
                   "img_url": ""},
                  {"news_id": "notice:307886863", "news_type": "NOTICE",
                   "title": "Chemed | SCHEDULE 13G: Others",
                   "publish_time": 1755056160, "url": "https://www.moomoo.com/news/notice/307886863",
                   "img_url": ""},
                  {"news_id": "notice:307786188", "news_type": "NOTICE",
                   "title": "Chemed | 8-K: Current report",
                   "publish_time": 1753801860, "url": "https://www.moomoo.com/news/notice/307786188",
                   "img_url": ""}]},
              "news:3": {"news_list": [
                  {"news_id": "post:1000217104", "news_type": "REPORT",
                   "title": "UBS Initiates Chemed(CHE.US) With Buy Rating, Announces Target Price $650",
                   "publish_time": 1758826380, "url": "https://www.moomoo.com/news/post/1000217104",
                   "img_url": ""},
                  {"news_id": "post:73909886", "news_type": "REPORT",
                   "title": "Oppenheimer Maintains Chemed(CHE.US) With Buy Rating, Raises Target Price to $590",
                   "publish_time": 1754009460, "url": "https://www.moomoo.com/news/post/73909886",
                   "img_url": ""}]},
              "company": {"profile": {"items": [
                  {"name": "Symbol", "value": S, "field_type": 0},
                  {"name": "Company Name", "value": "Chemed", "field_type": 0},
                  {"name": "Listing Date", "value": "Jun 29, 1982", "field_type": 0},
                  {"name": "ISIN", "value": "US16359R1032", "field_type": 0},
                  {"name": "Founded", "value": "1970", "field_type": 0},
                  {"name": "CEO", "value": "Mr. Kevin J. Mcnamara", "field_type": 0},
                  {"name": "Market", "value": "NYSE", "field_type": 0},
                  {"name": "Employees", "value": "15811", "field_type": 0},
                  {"name": "Fiscal Year Ends", "value": "12-31", "field_type": 0},
                  {"name": "Address", "value": "255 East 5th Street,Suite 2600", "field_type": 0},
                  {"name": "City", "value": "Cincinnati", "field_type": 0},
                  {"name": "Province", "value": "Ohio", "field_type": 0},
                  {"name": "Country", "value": "United States of America", "field_type": 0},
                  {"name": "Zip Code", "value": "45202-4726", "field_type": 0},
                  {"name": "Phone", "value": "1-513-762-6690", "field_type": 0},
                  {"name": "Website", "value": "http://www.chemed.com", "field_type": 1},
                  {"name": "Introduction", "field_type": 2, "value":
                   "Chemed Corp. engages in the provision of healthcare and maintenance "
                   "services. It operates through the VITAS and Roto-Rooter segments."}]},
                  "executives": [
                  {"name": "Kevin J. Mcnamara", "position": "President, Chief Executive Officer and Director", "salary": 12900000.0},
                  {"name": "Spencer S. Lee", "position": "EVP; Chairman of the Board and CEO of Roto-Rooter Services Company", "salary": 3210000.0},
                  {"name": "Joel L. Wherley", "position": "President and Chief Executive Officer of VITAS", "salary": 3050000.0},
                  {"name": "Michael D. Witzeman", "position": "CFO, Vice President, Controller", "salary": 3710000.0},
                  {"name": "Brian C. Judkins", "position": "Vice President and Chief Legal Officer", "salary": 2660000.0}]},
              "community": {"community_list": [
                  {"id": "117150573330838", "community_type": "FEED",
                   "title": "$620 soon.", "publish_time": 1756085460,
                   "url": "https://www.moomoo.com/community/feed/620-soon-117150573330838",
                   "img_url": ""},
                  {"id": "114774232858637", "community_type": "FEED",
                   "title": "Wall Street Today: S&P 500 and Nasdaq Push Further Into Record Territory",
                   "publish_time": 1751357760,
                   "url": "https://www.moomoo.com/community/feed/wall-street-today-114774232858637",
                   "img_url": ""}]},
              }
    if key in quotes:
        return quotes[key]
    return None


def estimates(symbol: str) -> dict:
    """S&P Global Market Intelligence street estimates (Yahoo/yfinance shape),
    recorded from the live CHE pull on 2026-09-27."""
    return {"available": True, "symbol": symbol.upper().removesuffix("-US"),
            "revenue_estimate": [
                {"period": "0q", "avg": 685036720, "low": 680067000, "high": 687931890,
                 "numberOfAnalysts": 5, "yearAgoRevenue": 624900000, "growth": 0.0962},
                {"period": "+1q", "avg": 705337110, "low": 701964000, "high": 708595000,
                 "numberOfAnalysts": 5, "yearAgoRevenue": 639337000, "growth": 0.1032},
                {"period": "0y", "avg": 2721137830, "low": 2716550000, "high": 2723926910,
                 "numberOfAnalysts": 5, "yearAgoRevenue": 2529978000, "growth": 0.0756},
                {"period": "+1y", "avg": 2885673940, "low": 2859680000, "high": 2898016400,
                 "numberOfAnalysts": 5, "yearAgoRevenue": 2721137830, "growth": 0.0605}],
            "earnings_estimate": [
                {"period": "0q", "avg": 6.43556, "low": 6.31, "high": 6.53779,
                 "numberOfAnalysts": 5, "yearAgoEps": 5.27, "growth": 0.2212},
                {"period": "+1q", "avg": 7.37478, "low": 7.12, "high": 7.55,
                 "numberOfAnalysts": 5, "yearAgoEps": 6.42, "growth": 0.1487},
                {"period": "0y", "avg": 25.49376, "low": 25.31, "high": 25.68882,
                 "numberOfAnalysts": 5, "yearAgoEps": 21.55, "growth": 0.1830},
                {"period": "+1y", "avg": 27.51786, "low": 26.61, "high": 28.41931,
                 "numberOfAnalysts": 5, "yearAgoEps": 25.49, "growth": 0.0794}],
            "eps_trend": [
                {"period": "0q", "current": 6.43556, "7daysAgo": 6.41, "30daysAgo": 6.4775,
                 "60daysAgo": 6.0225, "90daysAgo": 6.0225},
                {"period": "+1q", "current": 7.37478, "7daysAgo": 7.335, "30daysAgo": 7.345,
                 "60daysAgo": 7.0725, "90daysAgo": 7.0725}],
            "earnings_history": [
                {"quarter": "2025-09-30", "eps_estimate": 5.365, "eps_actual": 5.27,
                 "surprise_pct": -1.77},
                {"quarter": "2025-12-31", "eps_estimate": 7.03, "eps_actual": 6.42,
                 "surprise_pct": -8.68},
                {"quarter": "2026-03-31", "eps_estimate": 5.3025, "eps_actual": 5.65,
                 "surprise_pct": 6.55},
                {"quarter": "2026-06-30", "eps_estimate": 5.6, "eps_actual": 6.06,
                 "surprise_pct": 8.21}],
            "calendar": {"Earnings Date": ["2026-10-28"], "Earnings Average": 6.43556,
                         "Revenue Average": 685036720, "Ex-Dividend Date": "2026-08-17"}}
