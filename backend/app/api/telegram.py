from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from sqlalchemy import select

from app.config import settings
from app.db.models.order import Order
from app.db.session import SessionLocal
from app.services.telegram_bot import (
    LABELS,
    build_fail_reason_keyboard,
    get_telegram_client,
    handle_callback,
    is_chat_allowed,
    parse_callback_data,
    verify_webhook_secret,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/telegram", tags=["telegram"])


def _lang() -> str:
    return settings.TELEGRAM_MESSAGE_LANGUAGE or "en"


def _t(key: str) -> str:
    lang = _lang()
    return LABELS.get(lang, LABELS["en"]).get(key, LABELS["en"].get(key, key))


# Result detail -> (label key, show as blocking alert).
# Without answering, the button spins forever and users think it is broken.
_CALLBACK_FEEDBACK = {
    "already_processed": ("alreadyProcessed", False),
    "already_taken": ("alreadyTaken", True),
    "not_pending": ("notPending", True),
    # "the order moved on" is NOT the same as "you can no longer take it" --
    # reusing the accept-failure text here made Completed look broken.
    "invalid_state": ("invalidState", True),
    "access_denied": ("accessDenied", True),
    "order_not_found": ("orderNotFound", True),
    "forbidden": ("forbidden", True),
    "unknown_action": ("invalidState", True),
    # Backing out of the reason picker is a success, not a failure.
    "cancel_fail": ("cancelled", False),
}


# ---------------------------------------------------------------------------
# Update handling
#
# Every step below blocks: SQLAlchemy queries run synchronously and each
# Telegram API call is a synchronous HTTPS round-trip (up to its 15s timeout).
# Doing them inside the request handler froze the single uvicorn worker for the
# whole fan-out (N sibling orders = N more round-trips), so the 200 OK arrived
# AFTER Telegram had given up and Cloudflare had closed the connection -- which
# is exactly what surfaced as "the origin web server returned an invalid or
# incomplete response".
#
# BackgroundTasks run in FastAPI's threadpool: nothing here can stall the event
# loop, and Telegram always gets its 200 within a few milliseconds.
# ---------------------------------------------------------------------------


def handle_update(body: dict) -> None:
    """Process one Telegram update using its own DB session.

    The request-lifetime session is already closed by the time this runs, so a
    new one is opened here. Nothing may escape: every failure is logged so a
    lost update is visible in ``docker compose logs backend`` instead of being
    silently dropped.
    """
    db = SessionLocal()
    try:
        _dispatch(db, body)
    except Exception:
        logger.exception("telegram_update_failed")
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        try:
            db.close()
        except Exception:
            pass


def _show_fail_reason_picker(db, client, order, chat_id: str, message_id: str) -> tuple[bool, str]:
    """Attach the failure-reason keyboard to the order card.

    Editing the message the button belongs to is the best UX, but it is not
    always possible: the card may have been deleted, or the tap may come from
    an older duplicate whose message id is no longer the order's anchor. In
    that case we try the order's recorded message id, and finally post a fresh
    picker message. Only when all three paths fail does the caller show the
    "could not show reasons" alert.

    Returns (ok, error_text).
    """
    from app.services.telegram_bot import build_fail_reason_keyboard

    kb = build_fail_reason_keyboard(order.order_number)
    targets: list[str] = [str(message_id)]
    if order.telegram_message_id and str(order.telegram_message_id) != str(message_id):
        targets.append(str(order.telegram_message_id))

    last_error = ""
    for target in targets:
        try:
            client.edit_message_reply_markup(chat_id, target, kb)
            return True, ""
        except Exception as e:  # Telegram rejected the edit / message gone
            last_error = str(e) or type(e).__name__
            logger.warning(
                "fail_reason_keyboard_edit_failed order=%s message=%s err=%s",
                order.order_number, target, last_error,
            )

    # Last resort: a standalone message. Its callback message id differs from
    # the order anchor, so the success path can delete it afterwards.
    try:
        resp = client.send_message(chat_id, _t("selectFailReason"), reply_markup=kb)
        if isinstance(resp, dict) and resp.get("ok") is True:
            return True, ""
        last_error = str(resp)
    except Exception as e:
        last_error = str(e) or type(e).__name__
        logger.warning(
            "fail_reason_keyboard_send_failed order=%s err=%s",
            order.order_number, last_error,
        )
    return False, last_error


def _dispatch(db, body: dict) -> None:
    client = get_telegram_client(db, dry_run=True)

    if "callback_query" not in body:
        _dispatch_message(db, body, client)
        return

    cq = body["callback_query"]
    data = cq.get("data")
    from_user = cq.get("from", {})
    msg = cq.get("message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id", ""))
    message_id = str(msg.get("id", ""))
    callback_id = cq.get("id")

    ctx = parse_callback_data(data)
    if ctx is None:
        return
    ctx.chat_id = chat_id
    ctx.user_id = str(from_user.get("id", ""))
    ctx.username = from_user.get("username")

    def _answer(text: str = "", alert: bool = False) -> None:
        # Acknowledge promptly: this is what removes the loading spinner.
        if not callback_id:
            return
        try:
            client.answer_callback(callback_id, text, show_alert=alert)
        except Exception:
            pass

    # Two-step failure: show reason selection first.
    if ctx.action == "fail" and not ctx.failure_reason:
        order = db.execute(
            select(Order).where(Order.order_number == ctx.order_number)
        ).scalar_one_or_none()
        if (
            order is None
            or (order.telegram_chat_id and order.telegram_chat_id != chat_id)
            or not is_chat_allowed(db, chat_id)
        ):
            _answer(_t("accessDenied"), alert=True)
            return
        ok, err = _show_fail_reason_picker(db, client, order, chat_id, message_id)
        if ok:
            _answer(_t("selectFailReason"))
        else:
            # Say what actually happened instead of pretending the order moved
            # on. The admin can still mark it failed from the dashboard.
            logger.warning("fail_reason_picker_unavailable order=%s err=%s",
                           ctx.order_number, err)
            _answer(_t("failReasonUnavailable"), alert=True)
        return

    result = handle_callback(db, ctx, client)
    # Log the outcome with the order number: a wrong-state tap and a real
    # failure look identical to the user ("the button did nothing"), so the
    # detail has to be recoverable from `docker compose logs backend`.
    logger.info(
        "callback_result order=%s action=%s chat=%s user=%s ok=%s detail=%s",
        ctx.order_number, ctx.action, chat_id, ctx.user_id,
        result.get("ok"), result.get("detail"),
    )

    # A standalone picker message (fallback path) is no longer useful once
    # the choice is recorded. The order anchor is untouched and gets refreshed
    # in place by handle_callback, so only delete when the tapped message is
    # not the order card itself.
    if ctx.action in ("fail", "cancelfail") and result.get("ok"):
        order = db.execute(
            select(Order).where(Order.order_number == ctx.order_number)
        ).scalar_one_or_none()
        if order is not None and str(message_id) != str(order.telegram_message_id or ""):
            try:
                client.delete_message(chat_id, message_id)
            except Exception as e:
                logger.warning("picker_message_delete_failed order=%s err=%s",
                               ctx.order_number, e)

    # Always tell the user what happened, otherwise the button appears dead.
    if result.get("ok"):
        _answer(_t("callbackDone"))
    else:
        key, alert = _CALLBACK_FEEDBACK.get(result.get("detail", ""), ("notPending", True))
        _answer(_t(key), alert=alert)


def _reply(client, chat_id: str, text: str) -> None:
    try:
        client.send_message(chat_id, text)
    except Exception as e:  # a private reply must never break the webhook
        logger.warning("private_reply_failed err=%s", e)


def _bind_telegram(db, client, chat_id: str, from_user: dict, raw_token: str) -> None:
    """Complete a dispatcher's Telegram binding from a one-time token.

    Tokens are stored hashed, single-use and short-lived. If the Telegram ID was
    previously auto-created as an inactive worker account (someone pressed the
    Telegram login button before binding), that empty account is taken over;
    a real account with history is never stolen.
    """
    import hashlib
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.constants import ROLE_DISPATCHER, ROLE_WORKER
    from app.db.models.order import Order
    from app.db.models.user import TelegramBindToken, User

    token = (raw_token or "").strip()
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    row = db.execute(
        select(TelegramBindToken).where(TelegramBindToken.token_hash == digest)
    ).scalar_one_or_none()

    def fail(msg_zh: str, msg_en: str) -> None:
        _reply(client, chat_id, f"{msg_zh}\n{msg_en}")

    if row is None or row.used_at is not None:
        return fail("?????????????????????",
                    "Invalid or already used code. Generate a new one in the app.")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if expires < datetime.now(timezone.utc):
        return fail("?????????????????",
                    "This code has expired. Generate a new one in the app.")

    user = db.get(User, row.user_id)
    if user is None or user.role != ROLE_DISPATCHER or not user.is_active:
        return fail("???????????????",
                    "This account cannot be bound. Contact the administrator.")

    telegram_id = str(from_user.get("id", ""))
    other = db.execute(
        select(User).where(User.telegram_user_id == telegram_id)
    ).scalar_one_or_none()
    if other is not None and other.id != user.id:
        has_orders = db.execute(
            select(Order.id).where(
                (Order.order_owner_id == other.id)
                | (Order.created_by_user_id == other.id)
                | (Order.accepted_by_user_id == other.id)
                | (Order.completed_by_user_id == other.id)
            ).limit(1)
        ).scalar()
        takeable = (
            other.role == ROLE_WORKER
            and not other.is_active
            and has_orders is None
            and not other.chat_accesses
        )
        if not takeable:
            return fail("? Telegram ??????????????????",
                        "This Telegram is already bound to another account. Ask an admin to unbind it.")
        # Nothing was ever done with the auto-created account: drop it.
        db.delete(other)
        db.flush()

    user.telegram_user_id = telegram_id
    tg_username = (from_user.get("username") or "").strip()
    if tg_username:
        user.telegram_username = tg_username[:64]
    display = " ".join(
        part for part in (from_user.get("first_name"), from_user.get("last_name")) if part
    ).strip()
    if display:
        user.display_name = display[:128]
    row.used_at = datetime.now(timezone.utc)
    db.commit()

    if user.preferred_language == "zh-CN":
        _reply(client, chat_id, "? ?????????????? Telegram ????")
    else:
        _reply(client, chat_id, "? Bound successfully. You can now sign in with Telegram.")


def _dispatch_message(db, body: dict, client) -> None:
    """Plain messages: /start, /bind, /count and /stats. Everything else
    (group chatter) is ignored."""
    message = body.get("message") or {}
    text = (message.get("text") or "").strip()
    chat = message.get("chat") or {}
    from_user = message.get("from") or {}
    # Ignore commands sent in groups; answer them in private chat only.
    is_private = chat.get("type") == "private"
    if not (text and is_private):
        return

    chat_id = str(chat.get("id", ""))
    parts = text.split(maxsplit=1)
    command = parts[0].split("@")[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""

    if command == "/start" and argument.startswith("bind_"):
        return _bind_telegram(db, client, chat_id, from_user, argument[5:])
    if command == "/bind":
        return _bind_telegram(db, client, chat_id, from_user, argument)

    if command in ("/start", "/count", "/stats"):
        try:
            from app.services.notify import build_count_reply

            client.send_message(
                chat_id,
                build_count_reply(db, str(from_user.get("id", ""))),
            )
        except Exception as e:
            logger.warning("count_reply_failed err=%s", e)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/webhook")
async def telegram_webhook(request: Request, background: BackgroundTasks):
    """Receive a Telegram update.

    Deliberately does almost nothing inline: verify the shared secret, read the
    body, queue the work, and return immediately. Telegram only needs a fast
    200 to consider the update delivered -- if we wait for the (slow, outbound)
    Telegram API calls, we lose the race against three separate timeouts:
    Telegram 60s, Cloudflare 100s, nginx proxy_read_timeout 120s.
    """
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if not verify_webhook_secret(secret):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad_secret")

    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "detail": "invalid_json"}

    if not isinstance(body, dict) or not body:
        return {"ok": True}

    background.add_task(handle_update, body)
    return {"ok": True}
