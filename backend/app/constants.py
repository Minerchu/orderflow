# ============================================================
# Business constants & enums (single source of truth)
# ============================================================

# Roles
ROLE_ADMIN = "admin"
ROLE_PARTNER = "partner"
ROLE_WORKER = "worker"
# A dispatcher is the admin's delegate: same "send an order" action, but
# limited to the groups and products the admin granted. Kept separate from
# partner/worker so existing accounts and permissions never change.
ROLE_DISPATCHER = "dispatcher"
ROLES = (ROLE_ADMIN, ROLE_PARTNER, ROLE_WORKER, ROLE_DISPATCHER)

# Order statuses
ORDER_STATUS_DRAFT = "draft"
ORDER_STATUS_PENDING = "pending"
ORDER_STATUS_PROCESSING = "processing"
ORDER_STATUS_COMPLETED = "completed"
ORDER_STATUS_FAILED = "failed"
ORDER_STATUS_CLOSED = "closed"
ORDER_STATUSES = (
    ORDER_STATUS_DRAFT,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_PROCESSING,
    ORDER_STATUS_COMPLETED,
    ORDER_STATUS_FAILED,
    ORDER_STATUS_CLOSED,
)

# Financial statuses
FIN_STATUS_UNSETTLED = "unsettled"
FIN_STATUS_RESERVED = "reserved"
FIN_STATUS_SETTLED = "settled"
FIN_STATUS_EXCLUDED = "excluded"
FIN_STATUSES = (
    FIN_STATUS_UNSETTLED,
    FIN_STATUS_RESERVED,
    FIN_STATUS_SETTLED,
    FIN_STATUS_EXCLUDED,
)

# Login methods
LOGIN_PASSWORD = "password"
LOGIN_CODE_SEND = "code_send"
LOGIN_ACCOUNT_ONLY = "account_only"
LOGIN_QR_SCAN = "qr_scan"
LOGIN_METHODS = (LOGIN_PASSWORD, LOGIN_CODE_SEND, LOGIN_ACCOUNT_ONLY, LOGIN_QR_SCAN)

# Failure reasons
FAIL_ACCOUNT_NOT_ELIGIBLE = "account_not_eligible"
FAIL_INVALID_ACCOUNT = "invalid_account"
FAIL_RECHARGE_FAILED = "recharge_failed"
FAIL_OTHER = "other"
FAILURE_REASONS = (
    FAIL_ACCOUNT_NOT_ELIGIBLE,
    FAIL_INVALID_ACCOUNT,
    FAIL_RECHARGE_FAILED,
    FAIL_OTHER,
)

# Settlement batch statuses
SETTLEMENT_DRAFT = "draft"
SETTLEMENT_CONFIRMED = "confirmed"
SETTLEMENT_CANCELLED = "cancelled"
SETTLEMENT_STATUSES = (SETTLEMENT_DRAFT, SETTLEMENT_CONFIRMED, SETTLEMENT_CANCELLED)

# Settlement ledger type. A group batch settles the chat's whole ledger; a
# dispatcher batch settles one dispatcher's private ledger. They never touch
# each other's status column.
SETTLEMENT_TYPE_GROUP = "group"
SETTLEMENT_TYPE_DISPATCHER = "dispatcher"
SETTLEMENT_TYPES = (SETTLEMENT_TYPE_GROUP, SETTLEMENT_TYPE_DISPATCHER)

# Currencies
CURRENCY_INR = "INR"
CURRENCY_USD = "USD"
SUPPORTED_CURRENCIES = (CURRENCY_INR, CURRENCY_USD)

# Actor types for audit logs
ACTOR_ADMIN = "admin"
ACTOR_PARTNER = "partner"
ACTOR_TELEGRAM = "telegram"
ACTOR_SYSTEM = "system"
ACTOR_DISPATCHER = "dispatcher"

# Telegram send status
TG_SEND_PENDING = "pending"
TG_SEND_SENT = "sent"
TG_SEND_FAILED = "failed"

# Outbox statuses
OUTBOX_PENDING = "pending"
OUTBOX_SENT = "sent"
OUTBOX_FAILED = "failed"
