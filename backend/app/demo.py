"""灌入演示数据。运行：python -m app.demo

会建 admin（若无）+ 一批真实感的代购/集运数据：君丰订单、淘宝订单（含一单多物、
退款、日元直付、已取消示例）、杂项、以及暂存页的待导入订单。已有淘宝数据则跳过。
"""

import datetime as dt
from decimal import Decimal

from sqlmodel import Session, select

from .auth import hash_password
from .database import create_db_and_tables, engine
from .models import (
    FxRate, JunfengOrder, MiscExpense, OrderItem, StagingItem, TaobaoOrder, TaobaoStaging, User,
)

D = lambda y, m, d: dt.date(y, m, d)  # noqa: E731


def main() -> None:
    create_db_and_tables()
    with Session(engine) as s:
        if not s.exec(select(User).where(User.username == "admin")).first():
            s.add(User(username="admin", password_hash=hash_password("admin123"), display_name="管理员"))
            s.commit()

        if s.exec(select(TaobaoOrder)).first():
            print("已有淘宝数据，跳过演示数据灌入。")
            return

        # 汇率（供导入/预填）——已有当日汇率就不重复插入
        if not s.exec(select(FxRate).where(FxRate.date == D(2026, 7, 9))).first():
            s.add(FxRate(date=D(2026, 7, 9), rate=Decimal("23.8642")))

        # —— 君丰订单 ——
        jf1 = JunfengOrder(date=D(2026, 6, 5), junfeng_no="JF-2606A", weight=Decimal("4.5"),
                           intl_tracking_no="LP00612345678", status="已签收",
                           price_cny=Decimal("180"), fx_rate=Decimal("20.5"), special_fee_jpy=1200,
                           note="含关税消费税")
        jf2 = JunfengOrder(date=D(2026, 6, 20), junfeng_no="JF-2606B", weight=Decimal("2.1"),
                           intl_tracking_no="LP00612399999", status="已发出",
                           price_cny=Decimal("95"), fx_rate=Decimal("21"))
        jf3 = JunfengOrder(date=D(2026, 7, 5), junfeng_no="JF-2607A", status="打包中")
        for j in (jf1, jf2, jf3):
            j.compute_money()
            s.add(j)
        s.commit()
        for j in (jf1, jf2, jf3):
            s.refresh(j)

        # —— 淘宝订单（date, order_no, shop, account, express, price, rate, status, jf, items, override）——
        taobao = [
            dict(date=D(2026, 5, 28), order_no="TB250528001", shop="谷子屋", taobao_account="acctA",
                 express_no="SF1001", price_cny="320", fx_rate="20.5", status="已收", jf=jf1.id,
                 items=[("初音未来 手办", 1)]),
            dict(date=D(2026, 5, 30), order_no="TB250530007", shop="万代官方旗舰店", taobao_account="acctA",
                 express_no="SF1002", price_cny="460", fx_rate="20.5", status="已收", jf=jf1.id,
                 items=[("MG 高达模型", 2)]),
            dict(date=D(2026, 6, 2), order_no="TB250602013", shop="痛包周边专营", taobao_account="acctA",
                 express_no="YT2003", price_cny="88", fx_rate="20.8", status="已收", jf=jf1.id,
                 items=[("亚克力立牌", 3), ("金属徽章", 5)]),
            dict(date=D(2026, 6, 18), order_no="TB250618022", shop="二次元周边店", taobao_account="acctB",
                 express_no="ZT3004", price_cny="55", fx_rate="21", status="已发", jf=jf2.id,
                 items=[("角色抱枕套", 1)]),
            dict(date=D(2026, 6, 19), order_no="TB250619031", shop="手办工房", taobao_account="acctB",
                 express_no="ZT3005", price_cny="130", fx_rate="21", status="已发", jf=jf2.id,
                 items=[("景品手办", 1)]),
            dict(date=D(2026, 7, 3), order_no="TB250703044", shop="谷子屋", taobao_account="acctA",
                 express_no="SF1006", price_cny="60", fx_rate="23.86", status="已付", jf=jf3.id,
                 items=[("吧唧/徽章", 10)]),
            # 退款（负数照常计入）
            dict(date=D(2026, 7, 4), order_no="TB250704050", shop="挂件小铺", taobao_account="acctA",
                 price_cny="-25", fx_rate="23.86", status="退款", items=[("亚克力挂件(退款)", 1)]),
            # 日元直付（只填覆盖日元）
            dict(date=D(2026, 7, 6), order_no="TB250706061", shop="日亚代付", taobao_account="acctB",
                 override=3500, status="已付", items=[("日亚补款", 1)]),
            # 已取消（不计入看板）
            dict(date=D(2026, 7, 7), order_no="TB250707070", shop="测试店", taobao_account="acctA",
                 price_cny="200", fx_rate="23", status="已取消", items=[("取消的订单", 1)]),
        ]
        for t in taobao:
            o = TaobaoOrder(
                date=t["date"], order_no=t["order_no"], shop=t["shop"], taobao_account=t["taobao_account"],
                express_no=t.get("express_no"), status=t["status"], junfeng_order_id=t.get("jf"),
                price_cny=Decimal(t["price_cny"]) if "price_cny" in t else None,
                fx_rate=Decimal(t["fx_rate"]) if "fx_rate" in t else None,
                jpy_override=t.get("override"),
            )
            o.compute_money()
            o.items = [OrderItem(name=n, quantity=q) for n, q in t.get("items", [])]
            s.add(o)

        # —— 杂项 ——
        misc = [
            dict(date=D(2026, 6, 5), name="国际运费差价补款", price_cny="120", fx_rate="20.5", category="运费"),
            dict(date=D(2026, 6, 21), name="打包气泡膜", price_cny="30", fx_rate="21", category="包材"),
            dict(date=D(2026, 7, 1), name="煤炉出品手续费", override=800, category="手续费"),
            dict(date=D(2026, 7, 8), name="超卖退款到账", override=-500, category="退款"),
        ]
        for m in misc:
            e = MiscExpense(
                date=m["date"], name=m["name"], category=m.get("category"),
                price_cny=Decimal(m["price_cny"]) if "price_cny" in m else None,
                fx_rate=Decimal(m["fx_rate"]) if "fx_rate" in m else None,
                jpy_override=m.get("override"),
            )
            e.compute_money()
            s.add(e)

        # —— 暂存（待处理，演示「导入 / 忽略」；含一单多物）——
        staging = [
            dict(order_no="TB250708081", taobao_account="acctA", shop="谷子屋", order_status="已付",
                 price_cny="45", order_date=D(2026, 7, 8), items=[("色纸", 2), ("明信片套装", 1)]),
            dict(order_no="TB250708090", taobao_account="acctA", shop="手办工房", order_status="已发",
                 price_cny="150", order_date=D(2026, 7, 8), items=[("景品公仔", 1)]),
            dict(order_no="TB250707100", taobao_account="acctB", shop="日用百货", order_status="已收",
                 price_cny="39", order_date=D(2026, 7, 7), items=[("洗发水(非集运)", 1)]),
            dict(order_no="TB250709110", taobao_account="acctA", shop="画集屋", order_status="已付",
                 price_cny="78", order_date=D(2026, 7, 9), items=[("设定集", 1), ("A3 海报", 2)]),
        ]
        for st in staging:
            items = st.pop("items")
            row = TaobaoStaging(
                price_cny=Decimal(st.pop("price_cny")), fx_rate=Decimal("23.86"), **st
            )
            row.items = [StagingItem(name=n, quantity=q) for n, q in items]
            s.add(row)

        s.commit()
        print("演示数据已灌入：3 君丰 / 9 淘宝 / 4 杂项 / 4 暂存待导入。")


if __name__ == "__main__":
    main()
