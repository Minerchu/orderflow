from __future__ import annotations

import hashlib
import hmac
import json
import logging
import time
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import (
    ACTOR_TELEGRAM,
    FAIL_ACCOUNT_NOT_ELIGIBLE,
    FAIL_INVALID_ACCOUNT,
    FAIL_OTHER,
    FAIL_RECHARGE_FAILED,
    FIN_STATUS_RESERVED,
    FIN_STATUS_SETTLED,
    LOGIN_ACCOUNT_ONLY,
    LOGIN_CODE_SEND,
    LOGIN_QR_SCAN,
    ORDER_STATUS_CLOSED,
    ORDER_STATUS_DRAFT,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ROLE_ADMIN,
)
from app.db.models.order import Order, OrderEvent
from app.db.models.telegram import TelegramOutbox, TelegramUpdate
from app.db.models.user import User
from app.services.system_config import get_telegram_runtime_config

logger = logging.getLogger(__name__)

# ---------------- Messages ----------------

LABELS = {
    "en": {
        "order": "Order",
        "product": "Product",
        "email": "Email",
        "login_method": "Login Method",
        "code_send": "Code Send",
        "password_login": "Password Login",
        "account_only": "Account only",
        "qr_scan": "QR Scan",
        "account": "Account",
        "note": "Note",
        "amount": "Amount",
        "accept": "✅ Accept Order",
        "completed": "✅ Completed",
        "failed": "❌ Failed",
        "reopen": "🔄 Reopen",
        "close": "🔒 Close",
        "cancel": "✖️ Cancel",
        # Lets whoever handled a finished order correct a mistake. A completed
        # order with no way back would trap typos permanently.
        "markFailed": "↩️ Mark as Failed",
        # One-tap copy buttons so group members don't have to select & copy by
        # hand. Only offered for fields actually shown in the group message.
        "copyEmail": "📋 Copy Email",
        "copyAccount": "📋 Copy Account",
        "copyPassword": "📋 Copy Password",
        "access_denied": "Access Denied",
        "already_taken": "Sorry, this order was just taken by someone else.",
        "not_pending": "This order is no longer available.",
        # Shown when the order is not in the state this button expects (e.g.
        # Completed tapped on an order that is still waiting to be accepted).
        # Deliberately worded differently from not_pending, which only covers
        # the accept race.
        "invalidState": "⚠️ Order state changed — check the status line above.",
        # ---- Callback feedback (answerCallbackQuery toasts) ----
        "callbackDone": "✅ Done",
        "alreadyProcessed": "ℹ️ Already handled",
        "cancelled": "✖️ Cancelled",
        "selectFailReason": "Please pick a failure reason",
        "failReasonUnavailable": "⚠️ Could not show the reason picker - the group message may be deleted or too old to edit. Ask an admin to mark it failed in the dashboard.",
        "accessDenied": "⛔️ You are not allowed to do that",
        "orderNotFound": "❓ Order not found",
        "forbidden": "⛔️ You are not allowed to do that",
        # ---- Status banner shown at the top of the group message ----
        "status_pending": "🟡 Waiting for someone to accept",
        "status_processing": "🔵 In progress",
        "status_completed": "🟢 Completed",
        "status_failed": "🔴 Failed",
        "status_closed": "⚫️ Closed",
        "status_draft": "⚪️ Draft",
        "field_status": "Status",
        "field_sequence": "Sequence",
        "sequenceValue": "No. {seq}",
        "field_acceptedBy": "Accepted by",
        "field_completedBy": "Completed by",
        "field_failedBy": "Failed by",
        "field_failureReason": "Reason",
        "not_specified": "—",
        "reason_account_not_eligible": "Account not eligible",
        "reason_invalid_account": "Invalid account",
        "reason_recharge_failed": "Recharge failed",
        "reason_other": "Other",
    },
    "zh-CN": {
        "order": "订单",
        "product": "商品",
        "email": "邮箱",
        "login_method": "登录方式",
        "code_send": "验证码发送",
        "password_login": "密码登录",
        "account_only": "仅账号",
        "qr_scan": "直接扫码",
        "account": "账号",
        "note": "备注",
        "amount": "金额",
        "accept": "✅ 接单",
        "completed": "✅ 完成",
        "failed": "❌ 失败",
        "reopen": "🔄 重开",
        "close": "🔒 关闭",
        "cancel": "✖️ 取消",
        "markFailed": "↩️ 改为失败",
        "copyEmail": "📋 复制邮箱",
        "copyAccount": "📋 复制账号",
        "copyPassword": "📋 复制密码",
        "access_denied": "拒绝访问",
        "already_taken": "抱歉，该订单已被其他人接走。",
        "not_pending": "该订单已不可接。",
        # 订单状态与按钮不匹配时提示（例如对还在「等待接单」的订单点「已完成」）。
        # 与 not_pending 区分开：后者只用于接单被抢走的竞态。
        "invalidState": "⚠️ 订单状态已变化，请以上方状态条为准。",
        # ---- 按钮点击反馈 ----
        "callbackDone": "✅ 操作成功",
        "alreadyProcessed": "ℹ️ 该操作已处理过了",
        "cancelled": "✖️ 已取消",
        "selectFailReason": "请选择失败原因",
        "failReasonUnavailable": "⚠️ 无法显示失败原因选项：群消息可能已被删除或无法编辑。请让管理员在后台把这单标记为失败。",
        "accessDenied": "⛔️ 你没有权限执行此操作",
        "orderNotFound": "❓ 订单不存在",
        "forbidden": "⛔️ 你没有权限执行此操作",
        # ---- 群消息顶部状态条 ----
        "status_pending": "🟡 等待接单",
        "status_processing": "🔵 进行中",
        "status_completed": "🟢 已完成",
        "status_failed": "🔴 已失败",
        "status_closed": "⚫️ 已关闭",
        "status_draft": "⚪️ 草稿",
        "field_status": "状态",
        "field_sequence": "序号",
        "sequenceValue": "第 {seq} 单",
        "field_acceptedBy": "接单人",
        "field_completedBy": "完成人",
        "field_failedBy": "操作人",
        "field_failureReason": "失败原因",
        "not_specified": "—",
        "reason_account_not_eligible": "账号不符合条件",
        "reason_invalid_account": "账号无效",
        "reason_recharge_failed": "充值失败",
        "reason_other": "其他",
    },
}


def _lang() -> str:
    return settings.TELEGRAM_MESSAGE_LANGUAGE or "en"


def _t(key: str, lang: str) -> str:
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"].get(key, key))


def _esc(value) -> str:
    """Escape user text for Telegram's HTML parse mode.

    Account info, notes and product names are free-form: a password containing
    ``<`` or an ``&`` in a URL would otherwise make Telegram reject the whole
    message with "can't parse entities".
    """
    from html import escape

    return escape(str(value), quote=False)


def build_telegram_order_message(order: Order, lang: Optional[str] = None) -> str:
    """ONLY render fields the user actually filled. No N/A placeholders.

    The human-readable system order number is always included so the group can
    match its per-amount sequence to the order in the management panel.
    """
    lang = lang or _lang()
    lines: List[str] = []

    # The amount is the number the group acts on, so it leads the card and is
    # rendered bold. It used to sit at the bottom in the same weight as every
    # other line, which made it easy to misread.
    if order.amount is not None:
        lines.append(
            f"<b>💰 {_t('amount', lang)}: {order.amount:.2f} {order.currency}</b>"
        )
        lines.append("")

    # Always include the human-readable order number so a TG sequence/count can
    # be matched to the corresponding order in the web panel.
    lines.append(f"{_t('order', lang)}: {_esc(order.order_number)}")

    if order.product_name_snapshot and order.product_name_snapshot.strip():
        lines.append(f"{_t('product', lang)}: {_esc(order.product_name_snapshot)}")

    if order.email and order.email.strip():
        lines.append(f"{_t('email', lang)}: {_esc(order.email)}")

    if order.login_method == LOGIN_CODE_SEND:
        lines.append(f"{_t('login_method', lang)}: {_t('code_send', lang)}")
    elif order.login_method == "password":
        lines.append(f"{_t('login_method', lang)}: {_t('password_login', lang)}")
    elif order.login_method == LOGIN_ACCOUNT_ONLY:
        lines.append(f"{_t('login_method', lang)}: {_t('account_only', lang)}")
    elif order.login_method == LOGIN_QR_SCAN:
        lines.append(f"{_t('login_method', lang)}: {_t('qr_scan', lang)}")

    # Account info is stored verbatim: one input line -> one displayed line.
    # Each line gets its own one-tap copy button (see _copy_rows), so we render
    # it exactly as typed and never hide the password -- the admin wants every
    # line copyable in the group.
    if order.account_info and order.account_info.strip():
        for raw_line in order.account_info.split("\n"):
            line = raw_line.strip()
            if line:
                lines.append(_esc(line))
    else:
        # Legacy fallback for orders created before account_info existed.
        # (email is already rendered above, so only account/password remain.)
        if settings.SHOW_CREDENTIALS_IN_GROUP and order.account and order.account.strip():
            lines.append(f"{_t('account', lang)}: {_esc(order.account)}")
        if settings.SHOW_PASSWORD_IN_GROUP and order.password_encrypted:
            from app.core.security import decrypt_secret

            try:
                pw = decrypt_secret(order.password_encrypted)
                lines.append(f"Password: {_esc(pw)}")
            except Exception:
                raise TelegramSendError("telegram_credentials_unavailable") from None

    if order.note and order.note.strip():
        lines.append(f"{_t('note', lang)}: {_esc(order.note)}")

    return "\n".join(lines)


# Telegram caps the payload of an inline ``copy_text`` button at 256
# characters. Going over does not fail the button alone -- Telegram rejects
# the *entire* message with 400 BUTTON_COPY_TEXT_INVALID, which surfaces to
# the admin as a generic gateway error. Lines above the cap therefore get no
# one-tap button; they are still rendered verbatim in the message body.
TELEGRAM_COPY_TEXT_MAX = 256


def _copy_fits(value: Optional[str]) -> bool:
    """True when ``value`` can be used as a copy_text payload."""
    if not value:
        return False
    text = str(value).strip()
    return bool(text) and len(text) <= TELEGRAM_COPY_TEXT_MAX


def _copy_rows(order: Order, lang: str) -> List[List[dict]]:
    """One-tap copy buttons for the group message.

    Telegram 7.0+ supports ``copy_text`` on inline buttons, which writes the
    value straight to the member's clipboard.

    New orders carry ``account_info`` -- a verbatim multi-line block. We give
    every non-empty line its own button so the group can copy "email line",
    "password line", etc. individually, exactly as typed. No hiding: the admin
    wants each line copyable, password included.
    """
    if order.account_info and order.account_info.strip():
        rows: List[List[dict]] = []
        for raw_line in order.account_info.split("\n"):
            line = raw_line.strip()
            # Over-long lines get no button. Telegram rejects the *whole*
            # message (400 BUTTON_COPY_TEXT_INVALID) when a copy_text value
            # exceeds its cap, so one long line -- a Stripe checkout URL, for
            # instance -- would otherwise break the send entirely. The line is
            # still rendered verbatim in the message body, so the group can
            # always copy it by hand.
            if not line or len(line) > TELEGRAM_COPY_TEXT_MAX:
                continue
            # Button text is clipped for display only; the clipboard copy is the
            # full, untruncated line.
            display = line if len(line) <= 48 else line[:45] + "…"
            rows.append([{"text": f"📋 {display}", "copy_text": {"text": line}}])
        return rows

    # Legacy fallback for orders created before account_info existed: one button
    # per legacy field, gated by the existing security switches.
    rows = []
    row: List[dict] = []
    if _copy_fits(order.email):
        row.append({"text": _t("copyEmail", lang), "copy_text": {"text": order.email}})
    if settings.SHOW_CREDENTIALS_IN_GROUP and _copy_fits(order.account):
        row.append({"text": _t("copyAccount", lang), "copy_text": {"text": order.account}})
    if row:
        rows.append(row)
    if settings.SHOW_PASSWORD_IN_GROUP and order.password_encrypted:
        try:
            from app.core.security import decrypt_secret

            pw = decrypt_secret(order.password_encrypted)
            if pw and len(pw) <= TELEGRAM_COPY_TEXT_MAX:
                rows.append([{"text": _t("copyPassword", lang), "copy_text": {"text": pw}}])
        except Exception:
            pass
    return rows


def build_keyboard(order: Order, lang: Optional[str] = None):
    """Return inline keyboard (list of rows) based on status, or None."""
    lang = lang or _lang()
    if order.order_status in (ORDER_STATUS_DRAFT, ORDER_STATUS_PENDING):
        kb = [[{"text": _t("accept", lang), "callback_data": f"accept:{order.order_number}"}]]
    elif order.order_status == ORDER_STATUS_PROCESSING:
        kb = [
            [
                {"text": _t("completed", lang), "callback_data": f"complete:{order.order_number}"},
                {"text": _t("failed", lang), "callback_data": f"fail:{order.order_number}"},
            ]
        ]
    elif order.order_status == ORDER_STATUS_FAILED:
        kb = []
        if settings.ALLOW_ANY_GROUP_MEMBER_TO_REOPEN:
            kb.append([{"text": _t("reopen", lang), "callback_data": f"reopen:{order.order_number}"}])
        if settings.ALLOW_ANY_GROUP_MEMBER_TO_CLOSE:
            kb.append([{"text": _t("close", lang), "callback_data": f"close:{order.order_number}"}])
    elif order.order_status == ORDER_STATUS_COMPLETED:
        # A completed order can still be voided by mistake. Permission is
        # enforced server-side in _can_act_on_order, so showing the button to
        # the whole group is safe.
        kb = [[{
            "text": _t("markFailed", lang),
            "callback_data": f"void:{order.order_number}",
        }]]
    else:
        # Closed orders carry no actions.
        return None

    # Credentials are only useful while the order is still being worked on.
    # Once it is settled (completed / failed / closed) the copy rows are pure
    # clutter -- a multi-line account block produces one button per line, which
    # on a phone pushes the order itself off the screen. So they are only
    # attached while the order is waiting or in progress.
    if order.order_status in (
        ORDER_STATUS_DRAFT,
        ORDER_STATUS_PENDING,
        ORDER_STATUS_PROCESSING,
    ):
        copy_rows = _copy_rows(order, lang)
        if copy_rows:
            kb = kb + copy_rows
    return kb if kb else None


# ---------------- Group message rendering (status + history) ----------------

_STATUS_KEYS = {
    ORDER_STATUS_DRAFT: "status_draft",
    ORDER_STATUS_PENDING: "status_pending",
    ORDER_STATUS_PROCESSING: "status_processing",
    ORDER_STATUS_COMPLETED: "status_completed",
    ORDER_STATUS_FAILED: "status_failed",
    ORDER_STATUS_CLOSED: "status_closed",
}

_FAILURE_REASON_KEYS = {
    "account_not_eligible": "reason_account_not_eligible",
    "invalid_account": "reason_invalid_account",
    "recharge_failed": "reason_recharge_failed",
    "other": "reason_other",
}


def _display_name(order: Order, user_id, db: Session = None) -> str:
    """Resolve a user reference to something a group member recognises.

    Priority: real admin/partner name -> @telegram handle -> plain id.
    Auto-created accounts are named after the Telegram handle now, but older
    rows still carry the "tg_<id>" placeholder, which is meaningless to the
    group -- so the handle is used whenever the name looks auto-generated.
    """
    if not user_id:
        return ""
    if db is not None:
        try:
            from app.db.models.user import User

            user = db.get(User, user_id)
            if user is not None:
                name = (user.username or "").strip()
                is_placeholder = not name or (name.startswith("tg_") and name[3:].isdigit())
                handle = (user.telegram_username or "").strip().lstrip("@")
                if handle:
                    # Show @handle for auto accounts, the real name otherwise.
                    return f"@{handle}" if is_placeholder else name
                if name:
                    return name
        except Exception:
            pass
    return str(user_id)


# Statuses that still occupy a slot in the per-amount sequence number.
# Failed / closed orders are excluded so numbering stays gap-free.
_SEQ_COUNTED_STATUSES = (
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ORDER_STATUS_COMPLETED,
)


def build_sequence_map(db: Session, currency: str, amount, cycle_id=None) -> dict:
    """Map order_id -> per-amount sequence number for live orders.

    The admin creates one order per customer, all with the same amount, and
    wants the group to show "第 1 单 / 第 2 单 ...". Sequence is derived at
    render time rather than stored, so marking an order failed automatically
    closes the gap without a background job.

    Failed / closed orders are excluded: the admin asked for numbers to be
    recalculated when an order is voided.

    ``cycle_id`` scopes the numbering to a settlement cycle so that, after a
    batch is settled, counting restarts from No.1 for the next batch.
    """
    if amount is None:
        return {}

    q = (
        select(Order.id)
        .where(
            Order.currency == currency,
            Order.amount == amount,
            Order.order_status.in_(_SEQ_COUNTED_STATUSES),
        )
        .order_by(Order.created_at, Order.id)
    )
    if cycle_id is not None:
        q = q.where(Order.cycle_id == cycle_id)

    # Settled orders belong to a closed batch and must not occupy a number in
    # the next one -- otherwise counting would continue across settlements.
    # This is what makes "No.1" restart after each batch.
    q = q.where(
        ~Order.financial_status.in_((FIN_STATUS_SETTLED, FIN_STATUS_RESERVED))
    )

    rows = db.execute(q).scalars().all()
    return {order_id: index for index, order_id in enumerate(rows, start=1)}


def sequence_for(db: Session, order: Order) -> int | None:
    """This order's 1-based position among same-amount live orders."""
    if order.amount is None:
        return None
    try:
        return build_sequence_map(
            db, order.currency, order.amount, getattr(order, "cycle_id", None)
        ).get(order.id)
    except Exception:
        return None


def build_status_lines(order: Order, db: Session = None, lang: Optional[str] = None) -> List[str]:
    """The always-visible state block at the top of the group message.

    Previously the message text was never rewritten after send, so a finished
    order looked identical to a fresh one once its buttons vanished -- the group
    had no record of what happened.
    """
    lang = lang or _lang()
    lines = [f"<b>{_esc(_t(_STATUS_KEYS.get(order.order_status, 'status_draft'), lang))}</b>"]

    seq = sequence_for(db, order) if db is not None else None
    if seq:
        lines.append(f"{_t('field_sequence', lang)}: {_t('sequenceValue', lang).format(seq=seq)}")

    accepted = _display_name(order, order.accepted_by_user_id, db)
    if accepted:
        lines.append(f"{_t('field_acceptedBy', lang)}: {_esc(accepted)}")

    completed = _display_name(order, order.completed_by_user_id, db)
    if completed:
        lines.append(f"{_t('field_completedBy', lang)}: {_esc(completed)}")

    failed = _display_name(order, order.failed_by_user_id, db)
    if failed and not completed:
        lines.append(f"{_t('field_failedBy', lang)}: {_esc(failed)}")

    if order.order_status == ORDER_STATUS_FAILED and order.failure_reason:
        key = _FAILURE_REASON_KEYS.get(order.failure_reason)
        reason = _t(key, lang) if key else order.failure_reason
        if order.failure_note:
            reason = f"{reason} — {order.failure_note}"
        lines.append(f"{_t('field_failureReason', lang)}: {_esc(reason)}")

    return lines


def render_order_message(order: Order, db: Session = None, lang: Optional[str] = None) -> str:
    """Full group message: status block first, then the business fields."""
    lang = lang or _lang()
    parts = build_status_lines(order, db, lang)
    detail = build_telegram_order_message(order, lang)
    if detail.strip():
        parts.append("")
        parts.append(detail)
    return "\n".join(parts)


# ---------------- Telegram client (pluggable) ----------------

# Maps Telegram Bot API error_code -> stable, user-facing error code.
# Keeping this explicit means the UI can explain the failure instead of
# showing an opaque "telegram_send_failed".
_TG_ERROR_CODE_MAP = {
    400: "telegram_bad_request",
    401: "telegram_unauthorized",
    403: "telegram_forbidden",
    404: "telegram_chat_not_found",
    409: "telegram_conflict",
    429: "telegram_rate_limited",
}


def describe_telegram_failure(resp: dict | None, fallback: str = "telegram_send_failed") -> str:
    """Translate a Telegram API error response into a safe diagnostic code.

    The raw ``description`` is intentionally NOT returned to the client: it can
    echo back the chat id or other details, and the previous implementation
    leaked whatever Telegram said. We log it server-side and return a stable
    code, plus a short hint derived from well-known descriptions.
    """
    if not isinstance(resp, dict):
        return fallback

    error_code = resp.get("error_code")
    code = _TG_ERROR_CODE_MAP.get(error_code, fallback) if isinstance(error_code, int) else fallback

    # Recognisable sub-cases that the admin can actually act on.
    description = str(resp.get("description") or "").lower()
    if "chat not found" in description:
        code = "telegram_chat_not_found"
    elif "not enough rights" in description or "administrator" in description:
        code = "telegram_bot_not_admin"
    elif "bot was blocked" in description or "bot can't initiate" in description:
        code = "telegram_bot_blocked"
    elif "have no rights to send" in description or "user is deactivated" in description:
        code = "telegram_send_forbidden"
    elif "message is too long" in description:
        code = "telegram_message_too_long"
    elif "button_copy_text_invalid" in description or "copy_text" in description:
        # A copy button payload was rejected. Surface it as its own code so
        # the admin is told what actually went wrong instead of "send failed".
        code = "telegram_copy_text_too_long"
    elif "can't parse" in description:
        code = "telegram_invalid_payload"
    elif "message to edit not found" in description or "message to delete not found" in description:
        # The order card was deleted, or the stored message id belongs to an
        # older copy. Callers fall back to posting a fresh picker message.
        code = "telegram_message_not_found"
    elif "message can't be edited" in description or "message cannot be edited" in description:
        code = "telegram_message_not_editable"
    elif "message is not modified" in description:
        code = "telegram_message_not_modified"

    logger.warning("telegram_api_error code=%s mapped=%s raw_description=%s",
                   error_code, code, resp.get("description"))
    return code


class TelegramAPIClient:
    def __init__(self, token: str, api_base: str = "https://api.telegram.org",
                 proxy: str = "", timeout: float = 15.0):
        self.token = token
        self.api_base = api_base
        self.proxy = proxy
        self.timeout = timeout

    def _url(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    def _client(self):
        """Build an httpx client, honouring the optional outbound proxy."""
        import httpx

        if self.proxy:
            return httpx.Client(proxy=self.proxy, timeout=self.timeout)
        return httpx.Client(timeout=self.timeout)

    def _post(self, method: str, **kwargs) -> dict:
        import httpx

        try:
            with self._client() as client:
                r = client.post(self._url(method), **kwargs)
        except httpx.TimeoutException:
            raise TelegramSendError("telegram_network_timeout") from None
        except httpx.HTTPError as e:
            # Includes connection errors, DNS failures and proxy problems.
            logger.warning("telegram_network_error method=%s err=%s", method, type(e).__name__)
            raise TelegramSendError("telegram_network_error") from None

        try:
            return r.json()
        except ValueError:
            logger.warning("telegram_non_json_response method=%s status=%s", method, r.status_code)
            raise TelegramSendError("telegram_invalid_response") from None

    def _post_ok(self, method: str, **kwargs) -> dict:
        """Like ``_post`` but turns Telegram's JSON ``ok: false`` into an error.

        ``_post`` alone returned the error body, so callers that only inspected
        the return value treated a rejected edit as a success. That is exactly
        how the failure-reason picker reported "choose a reason" while Telegram
        had refused to attach the keyboard.
        """
        resp = self._post(method, **kwargs)
        if not isinstance(resp, dict) or resp.get("ok") is not True:
            raise TelegramSendError(describe_telegram_failure(resp, "telegram_api_error"))
        return resp

    def send_message(self, chat_id: str, text: str, reply_markup=None) -> dict:
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}
        return self._post_ok("sendMessage", json=payload)

    def send_photo(self, chat_id: str, image_bytes: bytes, filename: str,
                   caption: str = "", reply_markup=None) -> dict:
        files = {"photo": (filename, image_bytes)}
        data = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption
            data["parse_mode"] = "HTML"
        if reply_markup:
            data["reply_markup"] = json.dumps({"inline_keyboard": reply_markup})
        return self._post_ok("sendPhoto", data=data, files=files)

    def edit_message_reply_markup(self, chat_id: str, message_id: str,
                                  reply_markup=None) -> dict:
        payload = {"chat_id": chat_id, "message_id": message_id}
        if reply_markup:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}
        else:
            payload["reply_markup"] = ""
        return self._post_ok("editMessageReplyMarkup", json=payload)

    def edit_message_text(self, chat_id: str, message_id: str, text: str,
                          reply_markup=None) -> dict:
        """Rewrite the group's order message in place.

        This is what makes a finished order leave a visible trail instead of
        just losing its buttons.
        """
        payload: dict = {"chat_id": chat_id, "message_id": message_id,
                         "text": text, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}
        else:
            payload["reply_markup"] = ""
        return self._post_ok("editMessageText", json=payload)

    def edit_message_caption(self, chat_id: str, message_id: str, caption: str,
                             reply_markup=None) -> dict:
        """Rewrite the caption of a *photo* message in place.

        Telegram rejects ``editMessageText`` on messages that carry media
        ("there is no text in the message to edit"). Image orders are therefore
        edited through this method instead, otherwise their group card could
        never reflect a status change.
        """
        payload: dict = {"chat_id": chat_id, "message_id": message_id,
                         "caption": caption, "parse_mode": "HTML"}
        if reply_markup:
            payload["reply_markup"] = {"inline_keyboard": reply_markup}
        else:
            payload["reply_markup"] = ""
        return self._post_ok("editMessageCaption", json=payload)

    def edit_message_media_caption(self, chat_id: str, message_id: str, caption: str,
                                   reply_markup=None) -> dict:
        """Backwards/alias friendly wrapper used when the media must stay put."""
        return self.edit_message_caption(chat_id, message_id, caption, reply_markup)

    def delete_message(self, chat_id: str, message_id: str) -> dict:
        """Remove a message (used to clean up a standalone reason picker)."""
        return self._post_ok("deleteMessage", json={"chat_id": chat_id, "message_id": message_id})

    # ---- Diagnostics ----

    def get_me(self) -> dict:
        """Identity/permission probe used by the settings health check."""
        return self._post("getMe")

    def get_chat(self, chat_id: str) -> dict:
        """Probe whether the bot can see the target chat at all."""
        return self._post("getChat", json={"chat_id": chat_id})

    # ---- Webhook management ----

    def get_webhook_info(self) -> dict:
        return self._post("getWebhookInfo")

    def set_webhook(self, url: str, secret_token: str = "",
                    allowed_updates: Optional[list] = None) -> dict:
        """Register the callback URL with Telegram.

        Without this, tapping an inline button produces NO request at all, so
        the order never changes state. This is the step people forget.
        """
        payload: dict = {"url": url}
        if secret_token:
            payload["secret_token"] = secret_token
        if allowed_updates:
            payload["allowed_updates"] = allowed_updates
        return self._post("setWebhook", json=payload)

    def delete_webhook(self) -> dict:
        return self._post("deleteWebhook")

    def answer_callback(self, callback_query_id: str, text: str = "",
                        show_alert: bool = False) -> dict:
        """Stop the button spinner in the group and show a toast.

        Without this the button keeps spinning and users assume it is broken.
        """
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
            payload["show_alert"] = show_alert
        return self._post_ok("answerCallbackQuery", json=payload)


class MockTelegramClient:
    """In-memory client used for tests; never touches the network."""

    def __init__(self):
        self.sent: List[dict] = []
        self.edited: List[dict] = []
        self.text_edits: List[dict] = []
        self.caption_edits: List[dict] = []
        self.answered: List[dict] = []
        self.deleted: List[dict] = []
        self.next_message_id = 1

    def send_message(self, chat_id, text, reply_markup=None):
        mid = str(self.next_message_id)
        self.next_message_id += 1
        self.sent.append({"chat_id": chat_id, "text": text, "reply_markup": reply_markup,
                          "message_id": mid, "type": "message"})
        return {"ok": True, "result": {"message_id": int(mid), "chat": {"id": chat_id}}}

    def send_photo(self, chat_id, image_bytes, filename, caption="", reply_markup=None):
        mid = str(self.next_message_id)
        self.next_message_id += 1
        self.sent.append({"chat_id": chat_id, "caption": caption, "reply_markup": reply_markup,
                          "message_id": mid, "type": "photo", "filename": filename})
        return {"ok": True, "result": {"message_id": int(mid), "chat": {"id": chat_id}}}

    def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None):
        self.edited.append({"chat_id": chat_id, "message_id": message_id, "reply_markup": reply_markup})
        return {"ok": True, "result": {}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None):
        self.text_edits.append({
            "chat_id": chat_id, "message_id": message_id,
            "text": text, "reply_markup": reply_markup,
        })
        return {"ok": True, "result": {"message_id": int(message_id)}}

    def edit_message_caption(self, chat_id, message_id, caption, reply_markup=None):
        self.caption_edits.append({
            "chat_id": chat_id, "message_id": message_id,
            "caption": caption, "reply_markup": reply_markup,
        })
        return {"ok": True, "result": {"message_id": int(message_id)}}

    def answer_callback(self, callback_query_id, text="", show_alert=False):
        self.answered.append({"id": callback_query_id, "text": text})
        return {"ok": True, "result": {}}

    def delete_message(self, chat_id, message_id):
        self.deleted.append({"chat_id": chat_id, "message_id": message_id})
        return {"ok": True, "result": True}

    def get_webhook_info(self):
        return {"ok": True, "result": {"url": "", "pending_update_count": 0}}

    def set_webhook(self, url, secret_token="", allowed_updates=None):
        return {"ok": True, "result": True}

    def delete_webhook(self):
        return {"ok": True, "result": True}

    def get_me(self):
        return {"ok": True, "result": {"id": 1, "username": "mock_bot", "first_name": "Mock"}}

    def get_chat(self, chat_id):
        return {"ok": True, "result": {"id": chat_id, "title": "Mock Group", "type": "supergroup"}}


class TelegramNotConfigured(Exception):
    """Raised when a real send is attempted but no bot token is configured.

    We must NEVER silently pretend an order was delivered: a fake success would
    leave the order stuck in `pending` while the group never saw it.
    """


def get_telegram_client(db: Session, dry_run: bool = False):
    """Return a Telegram client using database configuration first."""
    runtime_config = get_telegram_runtime_config(db)
    if runtime_config.bot_token:
        return TelegramAPIClient(
            runtime_config.bot_token,
            proxy=(settings.TELEGRAM_PROXY or "").strip(),
        )
    if dry_run or settings.TELEGRAM_DRY_RUN:
        return MockTelegramClient()
    raise TelegramNotConfigured("Telegram bot token is not configured")


def get_default_chat_id(db: Session) -> str:
    """Return the database-configured default chat with env fallback."""
    return get_telegram_runtime_config(db).default_chat_id


# ---------------- Send order to chat ----------------

class TelegramSendError(Exception):
    """安全错误码，不携带 Telegram 原始响应、Token 或订单凭据。"""


def _split_message(text: str, limit: int = 4000) -> list[str]:
    # 按 UTF-16 单位分块，兼容非 BMP 字符，完整保留原文。
    chunks = []
    current = []
    size = 0
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            chunks.append("".join(current))
            current, size = [], 0
        current.append(char)
        size += units
    if current:
        chunks.append("".join(current))
    return chunks


@dataclass
class SendResult:
    """Outcome of a group send: which message anchors the order, and whether
    that message is media (photo) -- which dictates how it may be edited."""
    message_id: str
    is_media: bool = False


def send_order_to_chat(order: Order, client, chat_id: str, db: Session = None) -> SendResult:
    """全部响应确认成功后，返回唯一携带操作按钮的消息 ID。

    图片订单的注意事项（这曾经是"有图片的订单点接单没反应"的根因）：
      * Telegram 单条消息的 caption 上限是 1024 个 UTF-16 单位。超长时不能
        硬塞进 caption，必须单独发文本消息。
      * 按钮必须挂在**某一条消息**上，并且那条消息的 message_id 要写回订单，
        否则后续 editMessage* 找不到目标、群里也永远刷不出新状态。
      * 带图消息只能用 editMessageCaption 改，不能用 editMessageText，
        所以这里要把 is_media 一并返回，由调用方持久化。
    """
    try:
        text = render_order_message(order, db)
        keyboard = build_keyboard(order)
        photos = [a for a in order.attachments
                  if a.mime_type and a.mime_type.startswith("image/")]
        business_fields = (order.product_name_snapshot, order.email, order.login_method,
                           order.account, order.password_encrypted, order.account_info, order.note)
        if not photos and (not text.strip() or not (
                any(v and str(v).strip() for v in business_fields) or order.amount is not None)):
            raise TelegramSendError("empty_order")

        # Caption budget is 1024 UTF-16 units.
        caption_fits = len(text.encode("utf-16-le")) // 2 <= 1024

        if photos:
            from app.services.storage import get_storage

            storage = get_storage()
            last_photo_id = None
            for index, photo in enumerate(photos):
                last = index == len(photos) - 1
                resp = client.send_photo(
                    chat_id, storage.get_bytes(photo.storage_key), photo.original_filename,
                    # Caption rides the first photo; buttons ride the last one so
                    # a mid-way photo failure never leaves a claimable order.
                    caption=text if index == 0 and caption_fits else "",
                    reply_markup=keyboard if last and caption_fits else None,
                )
                last_photo_id = _extract_msg_id(resp)

            if caption_fits:
                # The last photo carries the buttons -> that is the anchor, and
                # it is a media message (editMessageCaption only).
                return SendResult(message_id=last_photo_id, is_media=True)

        chunks = _split_message(text)
        msg_id = None
        for index, chunk in enumerate(chunks):
            msg_id = _extract_msg_id(client.send_message(
                chat_id, chunk, reply_markup=keyboard if index == len(chunks) - 1 else None,
            ))
        return SendResult(message_id=msg_id, is_media=False)
    except TelegramSendError:
        raise
    except Exception:
        raise TelegramSendError("telegram_send_failed") from None


def _extract_msg_id(resp: dict) -> str:
    if not isinstance(resp, dict) or resp.get("ok") is not True:
        # Surface a specific, actionable code (chat not found / not admin /
        # blocked / rate limited ...) instead of a generic failure.
        raise TelegramSendError(describe_telegram_failure(resp))
    result = resp.get("result")
    mid = result.get("message_id") if isinstance(result, dict) else None
    if type(mid) is not int or mid <= 0:
        raise TelegramSendError("telegram_invalid_response")
    return str(mid)


# ---------------- Webhook verification ----------------

def verify_webhook_secret(header_token: Optional[str]) -> bool:
    if not settings.TELEGRAM_WEBHOOK_SECRET:
        # No secret configured -> accept (dev). Production must set it.
        return True
    if not header_token:
        return False
    return hmac.compare_digest(header_token, settings.TELEGRAM_WEBHOOK_SECRET)


def is_chat_allowed(db: Session, chat_id: str) -> bool:
    runtime_config = get_telegram_runtime_config(db)
    if not runtime_config.allowed_chat_ids:
        # No allow-list configured: only the default chat is permitted.
        return chat_id == runtime_config.default_chat_id or runtime_config.default_chat_id == ""
    return chat_id in runtime_config.allowed_chat_ids


# ---------------- Callback handling ----------------

@dataclass
class CallbackContext:
    action: str
    order_number: str
    chat_id: str
    user_id: str
    username: Optional[str] = None
    failure_reason: Optional[str] = None
    failure_note: Optional[str] = None


def parse_callback_data(callback_data: str) -> Optional[CallbackContext]:
    # Format: action:order_number  (fail uses action:order_number:reason)
    if not callback_data or ":" not in callback_data:
        return None
    parts = callback_data.split(":", 2)
    action = parts[0]
    order_number = parts[1] if len(parts) > 1 else ""
    extra = parts[2] if len(parts) > 2 else None
    return CallbackContext(
        action=action, order_number=order_number, chat_id="", user_id="",
        failure_reason=extra,
    )


def build_fail_reason_keyboard(order_number: str, lang: Optional[str] = None):
    """Reason picker shown after tapping ❌ 失败.

    A trailing 取消 row lets the operator back out: previously the only way to
    escape the picker was to actually record a failure, which people found
    confusing ("I don't know how to operate this").
    """
    lang = lang or _lang()
    reasons = [
        (_t("reason_account_not_eligible", lang), FAIL_ACCOUNT_NOT_ELIGIBLE),
        (_t("reason_invalid_account", lang), FAIL_INVALID_ACCOUNT),
        (_t("reason_recharge_failed", lang), FAIL_RECHARGE_FAILED),
        (_t("reason_other", lang), FAIL_OTHER),
    ]
    rows = [
        [{"text": label, "callback_data": f"fail:{order_number}:{val}"}]
        for label, val in reasons
    ]
    rows.append([{"text": _t("cancel", lang), "callback_data": f"cancelfail:{order_number}"}])
    return rows


def _record_event(db, order, event_type, from_s, to_s, actor_user_id=None,
                  tg_user_id=None, tg_username=None, note=None):
    ev = OrderEvent(
        order_id=order.id,
        event_type=event_type,
        from_status=from_s,
        to_status=to_s,
        actor_user_id=actor_user_id,
        telegram_user_id=tg_user_id,
        telegram_username=tg_username,
        note=note,
    )
    db.add(ev)


def handle_callback(db: Session, ctx: CallbackContext, client) -> dict:
    """Process an inline-button callback. All checks performed server-side."""
    # 1) Chat allow-list
    if not is_chat_allowed(db, ctx.chat_id):
        return {"ok": False, "detail": "access_denied"}

    order = db.execute(
        select(Order).where(Order.order_number == ctx.order_number)
    ).scalar_one_or_none()
    if order is None:
        return {"ok": False, "detail": "order_not_found"}

    # 2) Callback chat must match the chat the order was sent to
    if order.telegram_chat_id and order.telegram_chat_id != ctx.chat_id:
        return {"ok": False, "detail": "access_denied"}

    # 3) Idempotency: only one pending row per (order, action) processed
    upd_key = f"{ctx.order_number}:{ctx.action}:{ctx.user_id}"
    existing = db.execute(
        select(TelegramUpdate).where(TelegramUpdate.update_key == upd_key)
    ).scalar_one_or_none()
    if existing and existing.processed:
        return {"ok": True, "detail": "already_processed"}

    from_st = order.order_status
    result = {"ok": True}

    if ctx.action == "accept":
        result = _do_accept(db, order, ctx, from_st)
    elif ctx.action == "complete":
        result = _do_complete(db, order, ctx, from_st, client)
    elif ctx.action == "fail":
        result = _do_fail(db, order, ctx, from_st)
    elif ctx.action == "void":
        result = _do_void(db, order, ctx, from_st)
    elif ctx.action == "reopen":
        result = _do_reopen(db, order, ctx, from_st)
    elif ctx.action == "close":
        result = _do_close(db, order, ctx, from_st)
    elif ctx.action == "cancelfail":
        # Back out of the reason picker without recording a failure. The order
        # is untouched; _refresh_group_message restores the normal buttons.
        result = _do_cancel_fail(db, order, ctx)
    else:
        return {"ok": False, "detail": "unknown_action"}

    if result.get("ok"):
        # mark idempotency
        if existing is None:
            db.add(TelegramUpdate(update_key=upd_key, processed=True))
        else:
            existing.processed = True
        db.commit()
        # Rewrite the group message so the new state (and who did it) is
        # visible, not just a change in which buttons are attached.
        _refresh_group_message(db, order, client)
        # Sequence numbers are derived from live data, so any status change
        # that adds or removes a slot shifts the same-amount siblings too:
        #   void / fail -> frees a slot, later orders move down
        #   reopen      -> takes a slot back, later orders move up
        if ctx.action in ("void", "fail", "reopen") and order.amount is not None:
            _refresh_same_amount_messages(db, order, client)
    else:
        db.rollback()
    return result


def _can_act_on_order(db, order, ctx) -> bool:
    """Permission check for complete/fail/reopen/close."""
    runtime_config = get_telegram_runtime_config(db)
    if ctx.user_id in runtime_config.admin_telegram_user_ids:
        return True
    # Admin users linked in the user table are also allowed.
    admin = db.execute(
        select(User).where(
            (User.telegram_user_id == ctx.user_id) & (User.role == ROLE_ADMIN)
        )
    ).scalar_one_or_none()
    if admin is not None:
        return True
    # Accepted user allowed for complete/fail (default behavior).
    if order.accepted_by_user_id is not None:
        accepted = db.get(User, order.accepted_by_user_id)
        if accepted and accepted.telegram_user_id == ctx.user_id:
            return True
    # Group-member permission flags
    if ctx.action == "complete" and settings.ALLOW_ANY_GROUP_MEMBER_TO_COMPLETE:
        return True
    if ctx.action == "fail" and settings.ALLOW_ANY_GROUP_MEMBER_TO_FAIL:
        return True
    if ctx.action == "reopen" and settings.ALLOW_ANY_GROUP_MEMBER_TO_REOPEN:
        return True
    if ctx.action == "close" and settings.ALLOW_ANY_GROUP_MEMBER_TO_CLOSE:
        return True
    return False


def _do_accept(db, order, ctx, from_st):
    # A draft order (e.g. one whose initial send failed, or that was never
    # flipped to pending) still shows the accept button, so it must be
    # claimable. Accept both draft and pending as "waiting to be worked on".
    if order.order_status not in (ORDER_STATUS_DRAFT, ORDER_STATUS_PENDING):
        return {"ok": False, "detail": "not_pending"}
    # Atomically claim the order (concurrency-safe on Postgres & SQLite):
    # the conditional UPDATE with RETURNING ensures only one concurrent
    # request can flip an unclaimed waiting order to processing.
    uid = _ensure_telegram_user(db, ctx)
    result = db.execute(
        update(Order)
        .where(
            Order.id == order.id,
            Order.order_status.in_((ORDER_STATUS_DRAFT, ORDER_STATUS_PENDING)),
            Order.accepted_by_user_id.is_(None),
        )
        .values(
            order_status=ORDER_STATUS_PROCESSING,
            accepted_by_user_id=uid,
            accepted_at=_now(),
        )
        .returning(Order.id)
    )
    # Consume the RETURNING cursor before any commit (SQLite requirement).
    claimed = result.fetchone()
    if claimed is None:
        return {"ok": False, "detail": "already_taken"}
    # Keep in-memory object consistent for downstream steps (button refresh).
    order.order_status = ORDER_STATUS_PROCESSING
    order.accepted_by_user_id = uid
    order.accepted_at = _now()
    _record_event(db, order, "accept", from_st, ORDER_STATUS_PROCESSING,
                  tg_user_id=ctx.user_id, tg_username=ctx.username)
    _audit(db, ACTOR_TELEGRAM, "order_accept", "order", str(order.id),
           f"tg_user={ctx.user_id}")
    return {"ok": True}


def _do_complete(db, order, ctx, from_st, client=None):
    if order.order_status != ORDER_STATUS_PROCESSING:
        return {"ok": False, "detail": "invalid_state"}
    if not _can_act_on_order(db, order, ctx):
        return {"ok": False, "detail": "forbidden"}
    # Prevent duplicate completion
    if order.completed_at is not None:
        return {"ok": True, "detail": "already_completed"}
    order.order_status = ORDER_STATUS_COMPLETED
    order.completed_by_user_id = _ensure_telegram_user(db, ctx)
    order.completed_at = _now()
    # Completing IS the confirmation: the admin does not want a second manual
    # step per order, so the amount is confirmed automatically here.
    if not order.amount_confirmed:
        order.amount_confirmed = True
        order.amount_confirmed_by = order.completed_by_user_id
        order.amount_confirmed_at = _now()
    _record_event(db, order, "complete", from_st, ORDER_STATUS_COMPLETED,
                  tg_user_id=ctx.user_id, tg_username=ctx.username)
    _audit(db, ACTOR_TELEGRAM, "order_complete", "order", str(order.id),
           f"tg_user={ctx.user_id}")

    # Private confirmation so the worker knows which numbered order was theirs.
    try:
        from app.services.notify import notify_completion

        notify_completion(db, order, client)
    except Exception as e:
        logger.warning("completion_notify_failed err=%s", e)

    return {"ok": True}


def _do_void(db, order, ctx, from_st):
    """Void an already-completed order (the handler tapped the wrong button).

    Voids the completion, marks it failed, and drops the confirmation so the
    order stops counting toward settlement. Its slot in the per-amount sequence
    is released, shifting later orders down.
    """
    if order.order_status != ORDER_STATUS_COMPLETED:
        return {"ok": False, "detail": "invalid_state"}
    if not _can_act_on_order(db, order, ctx):
        return {"ok": False, "detail": "forbidden"}
    # Only someone involved may undo it, so a random member cannot void
    # another person's finished work.
    actor_uid = None
    admin = db.execute(
        select(User).where(
            (User.telegram_user_id == ctx.user_id) & (User.role == ROLE_ADMIN)
        )
    ).scalar_one_or_none()
    if admin is not None:
        actor_uid = admin.id
    elif order.accepted_by_user_id is not None:
        accepted = db.get(User, order.accepted_by_user_id)
        if accepted and accepted.telegram_user_id == ctx.user_id:
            actor_uid = accepted.id
    if actor_uid is None:
        return {"ok": False, "detail": "forbidden"}

    order.order_status = ORDER_STATUS_FAILED
    order.failure_reason = ctx.failure_reason or FAIL_OTHER
    order.failed_by_user_id = actor_uid
    order.failed_at = _now()
    # Un-confirm so it is excluded from settlement.
    order.amount_confirmed = False
    order.amount_confirmed_by = None
    order.amount_confirmed_at = None
    _record_event(db, order, "void", from_st, ORDER_STATUS_FAILED,
                  tg_user_id=ctx.user_id, tg_username=ctx.username,
                  note=f"reason={order.failure_reason}")
    _audit(db, ACTOR_TELEGRAM, "order_void", "order", str(order.id),
           f"tg_user={ctx.user_id}")
    return {"ok": True}


def _do_fail(db, order, ctx, from_st):
    if order.order_status != ORDER_STATUS_PROCESSING:
        return {"ok": False, "detail": "invalid_state"}
    if not _can_act_on_order(db, order, ctx):
        return {"ok": False, "detail": "forbidden"}
    reason = ctx.failure_reason or FAIL_OTHER
    order.order_status = ORDER_STATUS_FAILED
    order.failure_reason = reason
    order.failure_note = ctx.failure_note
    order.failed_by_user_id = _ensure_telegram_user(db, ctx)
    order.failed_at = _now()
    _record_event(db, order, "fail", from_st, ORDER_STATUS_FAILED,
                  tg_user_id=ctx.user_id, tg_username=ctx.username,
                  note=f"reason={reason}")
    _audit(db, ACTOR_TELEGRAM, "order_fail", "order", str(order.id),
           f"reason={reason}; tg_user={ctx.user_id}")
    return {"ok": True}


def _do_reopen(db, order, ctx, from_st):
    if order.order_status != ORDER_STATUS_FAILED:
        return {"ok": False, "detail": "invalid_state"}
    if not _can_act_on_order(db, order, ctx):
        return {"ok": False, "detail": "forbidden"}
    order.order_status = ORDER_STATUS_PENDING
    order.accepted_by_user_id = None
    order.accepted_at = None
    _record_event(db, order, "reopen", from_st, ORDER_STATUS_PENDING,
                  tg_user_id=ctx.user_id, tg_username=ctx.username)
    _audit(db, ACTOR_TELEGRAM, "order_reopen", "order", str(order.id),
           f"tg_user={ctx.user_id}")
    return {"ok": True}


def _do_cancel_fail(db, order, ctx, from_st=None):
    """Abort the failure-reason picker. No state change at all.

    We only need the caller to re-render the keyboard, so this always succeeds
    as long as the order exists and the actor may act on it.
    """
    return {"ok": True, "detail": "cancel_fail"}


def _do_close(db, order, ctx, from_st):
    if order.order_status != ORDER_STATUS_FAILED:
        return {"ok": False, "detail": "invalid_state"}
    if not _can_act_on_order(db, order, ctx):
        return {"ok": False, "detail": "forbidden"}
    order.order_status = ORDER_STATUS_CLOSED
    order.closed_by_user_id = _ensure_telegram_user(db, ctx)
    order.closed_at = _now()
    _record_event(db, order, "close", from_st, ORDER_STATUS_CLOSED,
                  tg_user_id=ctx.user_id, tg_username=ctx.username)
    _audit(db, ACTOR_TELEGRAM, "order_close", "order", str(order.id),
           f"tg_user={ctx.user_id}")
    return {"ok": True}


def _refresh_group_message(db: Session, order: Order, client) -> bool:
    """Rewrite the original group message after a state change.

    Previously only the inline keyboard was touched, so a completed order kept
    looking like a fresh one (minus its buttons) and the group had no record of
    what happened. Now the text carries a status banner, who acted, and when.

    Image orders are edited through ``editMessageCaption`` because Telegram
    refuses ``editMessageText`` on media messages. Without that branch the edit
    always failed and the group card stayed stale forever.

    Returns True when the remote message was updated.
    """
    if not order.telegram_chat_id or not order.telegram_message_id:
        return False

    # Re-read so the banner reflects committed state and resolved usernames.
    db.expire_all()
    fresh = db.execute(
        select(Order).where(Order.id == order.id)
    ).scalar_one_or_none()
    if fresh is None:
        return False

    text = render_order_message(fresh, db)
    kb = build_keyboard(fresh)
    is_media = bool(getattr(fresh, "telegram_message_is_media", False))

    try:
        if is_media:
            # A photo message can only carry a caption (1024 UTF-16 units).
            # Keep the important part (status banner) by trimming the tail.
            caption = text
            if len(caption.encode("utf-16-le")) // 2 > 1024:
                caption = caption[:1000].rstrip() + "…"
            client.edit_message_caption(
                fresh.telegram_chat_id, fresh.telegram_message_id, caption, kb
            )
        else:
            client.edit_message_text(
                fresh.telegram_chat_id, fresh.telegram_message_id, text, kb
            )
        return True
    except Exception as e:
        logger.warning("group_message_edit_failed order=%s media=%s err=%s",
                       fresh.order_number, is_media, e)
        # Fall back to a buttons-only edit so state stays actionable even if the
        # text/caption edit was rejected (e.g. message too old or deleted).
        try:
            client.edit_message_reply_markup(
                fresh.telegram_chat_id, fresh.telegram_message_id, kb
            )
        except Exception as e2:
            logger.warning("group_message_markup_edit_failed order=%s err=%s",
                           fresh.order_number, e2)
        return False


# Backwards-compatible alias (used by older imports/tests).
_refresh_message_buttons = _refresh_group_message


# --- Sibling refresh fan-out limit -----------------------------------------
# Sequence numbers are derived from live data, so one void/fail/reopen can
# renumber every order sharing that amount. The refresh used to walk ALL of
# them, and N siblings meant N synchronous HTTPS round-trips inside the request
# handler: past a couple dozen, the combined time crossed Telegram's 60s and
# Cloudflare's 100s ceilings and took the whole webhook down with it.
# Capping it keeps the cost constant no matter how many orders accumulate.
MAX_SIBLING_REFRESH = 20
SIBLING_REFRESH_BUDGET_S = 20.0


def _refresh_same_amount_messages(db: Session, order: Order, client) -> None:
    """Rewrite sibling orders that share this order's amount.

    Sequence numbers are derived from live data, so voiding an order shifts
    every later same-amount order down by one. Without this the group would
    show gaps (No.1, No.3, No.4) with no visible cause.

    Deliberately bounded: only the most recent siblings are refreshed, and the
    loop stops once the wall-clock budget is spent, so a pathological number of
    same-amount orders can never stall a webhook again.
    """
    if order.amount is None:
        return
    try:
        siblings = db.execute(
            select(Order)
            .where(
                Order.currency == order.currency,
                Order.amount == order.amount,
                Order.id != order.id,
                Order.telegram_message_id.isnot(None),
            )
            .order_by(Order.created_at.desc())
            .limit(MAX_SIBLING_REFRESH)
        ).scalars().all()
    except Exception as e:
        logger.warning("sibling_refresh_query_failed err=%s", e)
        return

    started = time.monotonic()
    refreshed = 0
    for sibling in siblings:
        if time.monotonic() - started > SIBLING_REFRESH_BUDGET_S:
            logger.warning(
                "sibling_refresh_truncated refreshed=%s budget=%.0fs",
                refreshed, SIBLING_REFRESH_BUDGET_S,
            )
            return
        _refresh_group_message(db, sibling, client)
        refreshed += 1


# ---------------- helpers ----------------

def _now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _ensure_telegram_user(db: Session, ctx: CallbackContext) -> int:
    """Ensure a User row exists for the Telegram actor (so accepted_by FK works)."""
    user = db.execute(
        select(User).where(User.telegram_user_id == ctx.user_id)
    ).scalar_one_or_none()

    # Prefer a human-readable name. Previously these auto-created accounts were
    # always named "tg_<id>", so the group message showed "接单人: tg_123456"
    # instead of the person's Telegram handle.
    display_name = (ctx.username or "").strip().lstrip("@")

    if user is None:
        user = User(
            username=display_name or f"tg_{ctx.user_id}",
            password_hash="__telegram__",
            role=ROLE_ADMIN if _is_admin_tg(db, ctx.user_id) else "partner",
            telegram_user_id=ctx.user_id,
            telegram_username=ctx.username,
            is_active=True,
        )
        db.add(user)
        db.flush()
    else:
        if ctx.username and user.telegram_username != ctx.username:
            user.telegram_username = ctx.username
        # Upgrade the ugly placeholder, but never rename a real account the
        # admin created (that would lose their login name).
        if user.username.startswith("tg_") and user.username[3:].isdigit():
            if display_name and display_name != user.username:
                user.username = display_name
            elif display_name:
                user.username = display_name
    return user.id


def _is_admin_tg(db: Session, telegram_user_id: str) -> bool:
    """Auto-created accounts follow the configured admin list."""
    try:
        return telegram_user_id in get_telegram_runtime_config(db).admin_telegram_user_ids
    except Exception:
        return False


def _audit(db, actor_type, action, entity_type, entity_id, detail=None):
    from app.db.models.audit import AuditLog

    db.add(AuditLog(actor_type=actor_type, action=action, entity_type=entity_type,
                    entity_id=entity_id, detail=detail))
