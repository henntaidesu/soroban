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

# 来源平台识别：靠各平台订单详情页特有的文案线索。闲鱼截图（成交价在支付宝担保账户中、
# 蚂蚁森林能量、开箱视频、我要退款等）优先级最高；再看京东、淘宝/天猫。命中即判定来源。
PLATFORM_CUES = [
    ("闲鱼", ("蚂蚁森林能量", "开箱视频", "担保账户", "担保交易", "闲鱼", "收货前拍摄", "芝麻信用")),
    ("京东", ("京东", "京东物流", "京豆", "白条", "自营", "PLUS会员")),
    ("淘宝", ("淘宝", "天猫", "旺旺", "花呗", "官方旗舰店")),
]

# 闲鱼物流卡通卡车模板：作为文案兜不住时的补充信号（有卡车 → 闲鱼）。多尺度模板匹配，
# 相关分 ≥ 阈值即判定命中。参考图存在 services/xianyu_truck.png。
_TRUCK_REF_PATH = Path(__file__).with_name("xianyu_truck.png")
_TRUCK_MATCH_THRESHOLD = 0.60
_TRUCK_SCALES = (0.25, 0.32, 0.4, 0.5, 0.6, 0.72, 0.85, 1.0)
_truck_ref = None            # 缓存的灰度模板
_truck_ref_loaded = False

_engine = None
_engine_lock = threading.Lock()


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
            "digits": _longest_digit_run(text or ""),
        })
    return tokens


def _match_company(text: str) -> Optional[str]:
    for kw, canonical in COMPANY_MAP.items():
        if kw in text:
            return canonical
    return None


def _same_row_value(anchor: dict, tokens: list[dict], row_tol: float,
                    min_digits: int) -> Optional[str]:
    """在与 anchor 同一行（y 接近）里找数字最长的值，优先取在 anchor 右侧的。
    找不到同行则退回到 anchor 下方最近的数字框。"""
    cands = [t for t in tokens if t is not anchor and t["digits"]
             and len(t["digits"]) >= min_digits]
    same_row = [t for t in cands if abs(t["cy"] - anchor["cy"]) <= row_tol]
    if same_row:
        right = [t for t in same_row if t["x0"] >= anchor["x0"]]
        pick = min(right or same_row, key=lambda t: abs(t["cy"] - anchor["cy"]))
        return pick["digits"]
    below = [t for t in cands if t["cy"] > anchor["cy"]]
    if below:
        return min(below, key=lambda t: t["cy"] - anchor["cy"])["digits"]
    return None


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


def _detect_platform(full_text: str) -> Optional[str]:
    """按平台特有文案判定来源（闲鱼 > 京东 > 淘宝），都没命中返回 None。"""
    for platform, cues in PLATFORM_CUES:
        if any(cue in full_text for cue in cues):
            return platform
    return None


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
    out = {"platform": None, "express_company": None, "express_no": None,
           "order_no": None, "price_cny": None}
    if not tokens:
        return out

    out["platform"] = _detect_platform("\n".join(t["text"] for t in tokens))

    heights = [t["h"] for t in tokens if t["h"] > 0]
    row_tol = (sum(heights) / len(heights) * 0.8) if heights else 12.0

    # 快递公司 + 快递号：快递名所在框即锚点；快递号取本框或同行数字（10~15 位居多，min=8 容错）
    for t in tokens:
        canonical = _match_company(t["text"])
        if canonical:
            out["express_company"] = canonical
            run = _longest_digit_run(t["text"], 8)
            out["express_no"] = run or _same_row_value(t, tokens, row_tol, 8)
            break

    # 订单号：锚点为含「订单编号/订单号」的框；值为本框或同行最长数字（多为 15~20 位）
    for t in tokens:
        if "订单编号" in t["text"] or "订单号" in t["text"]:
            run = _longest_digit_run(t["text"], 10)
            out["order_no"] = run or _same_row_value(t, tokens, row_tol, 10)
            break

    # 成交价：锚点为含「成交价」的框；同行取 ¥ 金额
    for t in tokens:
        if "成交价" in t["text"]:
            price = _parse_price(t, tokens, row_tol)
            if price is not None:
                try:
                    out["price_cny"] = str(Decimal(price))
                except Exception:
                    out["price_cny"] = price
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

    result, _ = engine(arr)
    fields = parse_order_fields(result)
    # 文案没判出来源时，用卡通卡车模板兜底：有卡车 → 闲鱼
    if not fields.get("platform") and _truck_present(arr):
        fields["platform"] = "闲鱼"
    # 附带完整识别文本，便于前端在缺字段时给用户核对/手动补
    fields["raw_text"] = "\n".join(item[1] for item in (result or []))
    return fields
