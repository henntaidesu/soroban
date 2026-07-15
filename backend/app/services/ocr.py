"""截图 OCR：从淘宝/支付宝订单详情图里抽取快递公司、快递号、订单号、成交价。

用 RapidOCR（onnxruntime，离线中文模型，pip 装、无系统二进制依赖）。引擎首次加载
模型较慢，故做进程内单例懒加载。解析靠「标签 + 几何同行关联」：先在同一文字框里
找「标签 + 值」，找不到再在同一行（y 接近）里找最近的数字/金额框。
"""

from __future__ import annotations

import io
import re
import threading
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ..models import TaobaoStatus   # 状态枚举值的唯一真相，避免与后端漂移

# 常见快递公司：关键词 → 规范全称。按「越具体越靠前」不重要（子串命中即可），
# 但保证能覆盖淘宝寄件常见家；命中后统一输出规范名，便于「快递公司」列做标签归组。
COMPANY_MAP = {
    "顺丰": "顺丰速运",
    "申通": "申通快递",
    "圆通": "圆通速递",
    "中通": "中通快递",
    "韵达": "韵达快递",
    "极兔": "极兔速递",
    "百世": "百世快递",
    "汇通": "百世快递",
    "天天": "天天快递",
    "德邦": "德邦快递",
    "京东": "京东物流",
    "宅急送": "宅急送",
    "丰网": "丰网速运",
    "菜鸟": "菜鸟裹裹",
    "邮政": "邮政快递",
    "EMS": "EMS",
    "ems": "EMS",
}

# OCR 只用于闲鱼——淘宝/京东走爬虫抓取。故 OCR 产出的来源恒为「闲鱼」；
# 仅当截图出现明确的淘宝/京东强标记且无任何闲鱼信号时，判为「拿错截图」并拒识、提示改用爬虫。
_XIANYU_CUES = ("蚂蚁森林能量", "开箱视频", "担保账户", "担保交易", "闲鱼", "收货前拍摄", "芝麻信用")
# 强平台标记：出现且无闲鱼信号才判为该平台。刻意不含「淘宝/花呗」等宽泛词——闲鱼隶属淘宝，
# 其页面也可能出现「淘宝」字样，用宽泛词会误伤闲鱼截图。
_JD_MARKERS = ("京东", "京东物流", "京豆", "白条", "自营", "PLUS会员")
_TAOBAO_MARKERS = ("天猫", "旺旺", "官方旗舰店")

# 闲鱼物流卡通卡车模板：作为文案兜不住时的补充信号（有卡车 → 闲鱼）。多尺度模板匹配，
# 相关分 ≥ 阈值即判定命中。参考图存在 services/xianyu_truck.png。
_TRUCK_REF_PATH = Path(__file__).with_name("xianyu_truck.png")
_TRUCK_MATCH_THRESHOLD = 0.60
_TRUCK_SCALES = (0.25, 0.32, 0.4, 0.5, 0.6, 0.72, 0.85, 1.0)
_truck_ref = None            # 缓存的灰度模板
_truck_ref_loaded = False

_engine = None
_engine_lock = threading.Lock()
# 识别在线程池里跑（见路由），多请求可并发到达；RapidOCR 引擎非保证可重入，
# 故用锁串行化实际推理——事件循环不被阻塞、前端可持续上传，推理逐张完成。
_infer_lock = threading.Lock()


class OcrUnavailable(RuntimeError):
    """RapidOCR 未安装/加载失败——供路由转成友好的 503。"""


def _get_engine():
    """懒加载并缓存 RapidOCR 引擎（首次约数百 ms 加载模型）。"""
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as e:  # 依赖未装
                raise OcrUnavailable(
                    "OCR 依赖未安装，请在 backend 下执行：pip install rapidocr_onnxruntime"
                ) from e
            _engine = RapidOCR()
    return _engine


def _longest_digit_run(text: str, min_len: int = 1) -> Optional[str]:
    """取文本里最长的一段连续数字（长度 ≥ min_len），否则 None。"""
    runs = re.findall(r"\d+", text or "")
    if not runs:
        return None
    best = max(runs, key=len)
    return best if len(best) >= min_len else None


def _extract_tracking(text: str, min_len: int = 8) -> Optional[str]:
    """快递单号：可能带字母前缀（顺丰 SF、京东 JD 等），取「字母数字混合、含≥6 位数字」的
    最长串并统一大写；纯数字单号照常命中。要求含足够数字 → 排除纯字母串（如地址 ATPTSTKH）。"""
    runs = re.findall(r"[A-Za-z0-9]+", text or "")
    cands = [r for r in runs if len(r) >= min_len and sum(c.isdigit() for c in r) >= 6]
    return max(cands, key=len).upper() if cands else None


def _to_tokens(ocr_result) -> list[dict]:
    """把 RapidOCR 结果 [[box, text, score], ...] 归一成带几何信息的 token 列表。"""
    tokens = []
    for item in ocr_result or []:
        box, text = item[0], item[1]
        xs = [float(p[0]) for p in box]
        ys = [float(p[1]) for p in box]
        tokens.append({
            "text": text or "",
            "cx": sum(xs) / len(xs),
            "cy": sum(ys) / len(ys),
            "x0": min(xs),
            "y0": min(ys),
            "y1": max(ys),
            "h": max(ys) - min(ys),
            "digits": _longest_digit_run(text or ""),      # 订单号等纯数字用
            "tracking": _extract_tracking(text or ""),     # 快递单号用（保留字母前缀）
        })
    return tokens


def _match_company(text: str) -> Optional[str]:
    for kw, canonical in COMPANY_MAP.items():
        if kw in text:
            return canonical
    return None


def _same_row_value(anchor: dict, tokens: list[dict], row_tol: float,
                    min_len: int, key: str = "digits") -> Optional[str]:
    """在与 anchor 同一行（y 接近）里找 key 值（digits/tracking）最长的框，优先取右侧的。
    找不到同行则退回到 anchor 下方最近的框。"""
    cands = [t for t in tokens if t is not anchor and t[key]
             and len(t[key]) >= min_len]
    same_row = [t for t in cands if abs(t["cy"] - anchor["cy"]) <= row_tol]
    if same_row:
        right = [t for t in same_row if t["x0"] >= anchor["x0"]]
        pick = min(right or same_row, key=lambda t: abs(t["cy"] - anchor["cy"]))
        return pick[key]
    below = [t for t in cands if t["cy"] > anchor["cy"]]
    if below:
        return min(below, key=lambda t: t["cy"] - anchor["cy"])[key]
    return None


def _extract_date(text: str) -> Optional[str]:
    """从文本里抽出 YYYY-MM-DD（兼容 - / . 及全角连字符 – —），无则 None。"""
    m = re.search(r"(\d{4})\s*[-/.–—]\s*(\d{1,2})\s*[-/.–—]\s*(\d{1,2})", text or "")
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def _parse_order_date(anchor: dict, tokens: list[dict], row_tol: float) -> Optional[str]:
    """下单时间：锚点框自身或同一行里取日期（避开付款/发货时间——它们各自有独立标签行）。"""
    if (d := _extract_date(anchor["text"])):
        return d
    same_row = [t for t in tokens if t is not anchor and abs(t["cy"] - anchor["cy"]) <= row_tol]
    same_row.sort(key=lambda t: t["x0"])
    for t in same_row:
        if (d := _extract_date(t["text"])):
            return d
    return None


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in (text or ""))


def _parse_product(tokens: list[dict], row_tol: float, price_anchor: Optional[dict]) -> Optional[str]:
    """商品名称：成交价上方最近的「挂牌价」所在行的中文文本即商品标题。
    （闲鱼订单页：商品图右侧一行 = 标题 + 单件挂牌价，位于「成交价」上方。）"""
    if price_anchor is None:
        return None

    def amount(text: str):
        return re.search(r"[¥￥]\s*[0-9]", text or "")

    above = [t for t in tokens if amount(t["text"]) and t["cy"] < price_anchor["cy"] - row_tol]
    if not above:
        return None
    listing = max(above, key=lambda t: t["cy"])   # 最靠近成交价的上方价 = 挂牌价行
    same_row = [t for t in tokens if t is not listing
                and abs(t["cy"] - listing["cy"]) <= row_tol and _has_cjk(t["text"])]
    if same_row:
        title = max(same_row, key=lambda t: len(t["text"]))["text"]
    else:   # 标题可能与价格合并在同一框：去掉价格片段后取剩余文本
        title = re.sub(r"[¥￥]\s*[0-9][0-9.,]*", "", listing["text"])
    title = title.strip()
    return title or None


def _parse_price(anchor: dict, tokens: list[dict], row_tol: float) -> Optional[str]:
    """成交价：同一行里找带 ¥/￥ 或形如 123.45 的金额，返回数字字符串。"""
    def amount(text: str) -> Optional[str]:
        m = re.search(r"[¥￥]\s*([0-9]+(?:\.[0-9]{1,2})?)", text)
        if not m:
            m = re.search(r"([0-9]+\.[0-9]{2})", text)   # 无货币符号时认小数金额
        return m.group(1) if m else None

    if (a := amount(anchor["text"])):        # 标签框自身就含金额
        return a
    same_row = [t for t in tokens if t is not anchor
                and abs(t["cy"] - anchor["cy"]) <= row_tol]
    same_row.sort(key=lambda t: t["x0"])
    for t in same_row:
        if (a := amount(t["text"])):
            return a
    return None


def _is_xianyu(full_text: str) -> bool:
    """文案里是否出现闲鱼特征线索。"""
    return any(c in full_text for c in _XIANYU_CUES)


def _detect_other_platform(full_text: str) -> Optional[str]:
    """是否出现明确的淘宝/京东强标记（用于拒识非闲鱼截图）；都没有返回 None。"""
    if any(m in full_text for m in _JD_MARKERS):
        return "京东"
    if any(m in full_text for m in _TAOBAO_MARKERS):
        return "淘宝"
    return None


def _detect_status(full_text: str, has_express: bool) -> str:
    """判交易状态：终态优先；发货后（头部「卖家已发货/待确认收货」或已有快递单号）→ 待收货；
    「等待卖家发货」→ 待发货；都不明确时以有无快递单号兜底（有单号必已发货）。"""
    if "交易成功" in full_text or "交易完成" in full_text:
        return TaobaoStatus.received.value       # 交易成功
    if "交易关闭" in full_text or "已关闭" in full_text:
        return TaobaoStatus.cancelled.value      # 交易关闭
    if has_express or any(k in full_text for k in ("待确认收货", "卖家已发货", "待收货", "确认收货")):
        return TaobaoStatus.shipped.value        # 待收货
    if any(k in full_text for k in ("等待卖家发货", "等待发货", "待卖家发货", "待发货")):
        return TaobaoStatus.paid.value           # 待发货
    return TaobaoStatus.paid.value               # 兜底：待发货


def _load_truck_ref():
    """懒加载并缓存灰度卡车模板；文件缺失/解码失败返回 None（该信号自动禁用）。"""
    global _truck_ref, _truck_ref_loaded
    if _truck_ref_loaded:
        return _truck_ref
    _truck_ref_loaded = True
    try:
        import cv2
        import numpy as np

        # 用 imdecode 而非 imread：避开 Windows 下 imread 对非 ASCII 路径的读取问题
        data = _TRUCK_REF_PATH.read_bytes()
        _truck_ref = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    except Exception:
        _truck_ref = None
    return _truck_ref


def _truck_score(gray) -> float:
    """多尺度模板匹配卡车，返回最高归一化相关分（0~1）；无参考图/异常返回 0。"""
    try:
        import cv2

        ref = _load_truck_ref()
        if ref is None or gray is None:
            return 0.0
        ih, iw = gray.shape[:2]
        rh, rw = ref.shape[:2]
        best = 0.0
        for s in _TRUCK_SCALES:
            w, h = int(rw * s), int(rh * s)
            if w < 24 or h < 18 or w > iw or h > ih:   # 太小无意义 / 比截图还大则跳过
                continue
            tmpl = cv2.resize(ref, (w, h), interpolation=cv2.INTER_AREA)
            res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, mx, _, _ = cv2.minMaxLoc(res)
            best = max(best, float(mx))
        return best
    except Exception:
        return 0.0


def _truck_present(rgb_arr) -> bool:
    """截图里是否出现闲鱼卡车（相关分达阈值）。"""
    try:
        import cv2

        gray = cv2.cvtColor(rgb_arr, cv2.COLOR_RGB2GRAY)
        return _truck_score(gray) >= _TRUCK_MATCH_THRESHOLD
    except Exception:
        return False


def parse_order_fields(ocr_result) -> dict:
    """从 OCR 结果里抽取 {platform, express_company, express_no, order_no, price_cny}（缺省 None）。"""
    tokens = _to_tokens(ocr_result)
    # platform 由 recognize_order 统一判定（需结合卡车图像），这里只抽文本字段
    out = {"platform": None, "express_company": None, "express_no": None,
           "order_no": None, "price_cny": None, "order_date": None, "product": None}
    if not tokens:
        return out

    heights = [t["h"] for t in tokens if t["h"] > 0]
    row_tol = (sum(heights) / len(heights) * 0.8) if heights else 12.0

    # 快递公司 + 快递号：快递名所在框即锚点；快递号取本框或同行数字（10~15 位居多，min=8 容错）
    for t in tokens:
        canonical = _match_company(t["text"])
        if canonical:
            out["express_company"] = canonical
            run = _extract_tracking(t["text"], 8)   # 保留字母前缀（如顺丰 SF）
            out["express_no"] = run or _same_row_value(t, tokens, row_tol, 8, key="tracking")
            break

    # 订单号：锚点为含「订单编号/订单号」的框；值为本框或同行最长数字（多为 15~20 位）
    for t in tokens:
        if "订单编号" in t["text"] or "订单号" in t["text"]:
            run = _longest_digit_run(t["text"], 10)
            out["order_no"] = run or _same_row_value(t, tokens, row_tol, 10)
            break

    # 成交价：锚点为含「成交价」的框；同行取 ¥ 金额
    price_anchor = None
    for t in tokens:
        if "成交价" in t["text"]:
            price_anchor = t
            price = _parse_price(t, tokens, row_tol)
            if price is not None:
                try:
                    out["price_cny"] = str(Decimal(price))
                except Exception:
                    out["price_cny"] = price
            break

    # 商品名称：成交价上方挂牌价所在行的中文标题
    out["product"] = _parse_product(tokens, row_tol, price_anchor)

    # 下单时间：锚点为含「下单时间」的框；同行取日期（区别于付款/发货时间）
    for t in tokens:
        if "下单时间" in t["text"]:
            out["order_date"] = _parse_order_date(t, tokens, row_tol)
            break

    return out


def recognize_order(image_bytes: bytes) -> dict:
    """对上传的截图跑 OCR 并解析出订单字段。抛 OcrUnavailable 表示引擎不可用。"""
    engine = _get_engine()
    try:
        from PIL import Image
        import numpy as np

        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.array(img)
    except Exception as e:
        raise ValueError(f"图片无法解析：{e}") from e

    with _infer_lock:                 # 串行化引擎推理（RapidOCR 非保证可重入）
        result, _ = engine(arr)
    fields = parse_order_fields(result)

    # OCR 只产出闲鱼数据：来源恒为「闲鱼」。仅当截图有明确淘宝/京东强标记、且无任何闲鱼信号
    # （文案线索或卡通卡车）时，判为拿错截图 → 拒识并提示改用爬虫（reject_reason 非空）。
    full = "\n".join(item[1] for item in (result or []))
    other = _detect_other_platform(full)
    is_xianyu = _is_xianyu(full) or _truck_present(arr)
    if other and not is_xianyu:
        fields["platform"] = None
        fields["reject_reason"] = f"疑似{other}订单截图；OCR 仅支持闲鱼，淘宝/京东请用爬虫抓取"
    else:
        fields["platform"] = "闲鱼"
        fields["reject_reason"] = None
    # 交易状态：有快递单号（已发货）→ 待收货，否则待发货（另按头部状态语细分终态）
    fields["status"] = _detect_status(full, bool(fields.get("express_no")))
    # 交易成功（已完成）无需物流信息：不回填快递公司/快递号
    if fields["status"] == TaobaoStatus.received.value:
        fields["express_company"] = None
        fields["express_no"] = None
    # 附带完整识别文本，便于前端在缺字段时给用户核对/手动补
    fields["raw_text"] = full
    return fields
