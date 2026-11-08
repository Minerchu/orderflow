"""Private notifications and self-service stats for group members.

Two small features the admin asked for:

* when someone completes an order they get a DM confirming it, including which
  numbered order ("第 3 单") it was -- workers were asking "which one was mine?"
* ``/count`` lets a worker ask the bot how many orders they have completed.

Both are best-effort: a failed DM must never roll back the order action, since
the action itself already succeeded in the group.
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.constants import ORDER_STATUS_COMPLETED
from app.db.models.order import Order
from app.db.models.user import User
from app.services.telegram_bot import _esc, sequence_for

logger = logging.getLogger(__name__)


def find_user_by_telegram_id(db: Session, telegram_user_id: str):
    if not telegram_user_id:
        return None
    return db.execute(
        select(User).where(User.telegram_user_id == str(telegram_user_id))
    ).scalars().first()


def completed_count(db: Session, user: User) -> int:
    """How many orders this person has completed."""
    return db.execute(
        select(func.count(Order.id)).where(
            Order.completed_by_user_id == user.id,
            Order.order_status == ORDER_STATUS_COMPLETED,
        )
    ).scalar() or 0


def notify_completion(db: Session, order: Order, client, actor_user_id=None) -> None:
    """DM the handler: "you completed No.N (amount)".

    Failures are swallowed on purpose -- the group already reflects the action.
    """
    try:
        target_user_id = actor_user_id or order.completed_by_user_id
        if not target_user_id:
            return
        user = db.get(User, target_user_id)
        if not user or not user.telegram_user_id:
            return

        amount = f"{order.amount:.2f} {order.currency}" if order.amount is not None else "-"
        seq = sequence_for(db, order)
        lines = ["✅ <b>订单已完成</b>"]
        if seq:
            lines.append(f"序号：第 {seq} 单")
        lines.append(f"金额：{amount}")
        if order.product_name_snapshot:
            lines.append(f"商品：{_esc(order.product_name_snapshot)}")
        lines.append(f"单号：{order.order_number}")
        lines.append(f"累计完成：{completed_count(db, user)} 单")

        client.send_message(user.telegram_user_id, "\n".join(lines))
        logger.info("completion_dm_sent order=%s user=%s", order.order_number, user.username)
    except Exception as e:
        # Never let a notification failure undo a completed order.
        logger.warning("completion_dm_failed order=%s err=%s", order.order_number, e)


def build_count_reply(db: Session, telegram_user_id: str, lang: str = "zh-CN") -> str:
    """Reply text for /count, or a friendly prompt if the user is unknown."""
    user = find_user_by_telegram_id(db, telegram_user_id)
    if user is None:
        return (
            "👋 还没有把你的 Telegram 账号绑定到系统。\n"
            "请让管理员在「合作伙伴」里填写你的 Telegram ID。"
        )

    done = completed_count(db, user)

    active = db.execute(
        select(func.count(Order.id)).where(
            Order.accepted_by_user_id == user.id,
            Order.order_status == "processing",
        )
    ).scalar() or 0

    total_amount = db.execute(
        select(func.coalesce(func.sum(Order.amount), 0)).where(
            Order.completed_by_user_id == user.id,
            Order.order_status == ORDER_STATUS_COMPLETED,
        )
    ).scalar() or 0

    return (
        f"📊 <b>{_esc(user.username)}</b> 的统计\n"
        f"进行中：{active} 单\n"
        f"已完成：{done} 单\n"
        f"完成金额：{total_amount}"
    )