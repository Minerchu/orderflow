"""Repair group sequence scope after a dispatcher settlement.

Dispatcher settlements settle a private ledger. A bug made ``current_cycle_id``
pick ANY confirmed batch, so orders created after a dispatcher settlement were
stamped with that private batch id. ``build_sequence_map`` then scoped those
orders to a separate cycle and the group-visible numbering restarted at No.1.

The code fix is in ``app.services.orders.current_cycle_id``. This migration
repairs rows already written by the buggy version: any order whose cycle points
at a dispatcher batch is moved back to the latest group batch that had been
confirmed when the order was created (or NULL when there was none).
"""

from alembic import op
import sqlalchemy as sa

revision = "a91c7e4f2b3d"
down_revision = "c8d4f2a91b70"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    broken = conn.execute(sa.text(
        """
        SELECT o.id, o.created_at
        FROM orders o
        JOIN settlement_batches b ON b.id = o.cycle_id
        WHERE b.settlement_type = 'dispatcher'
        """
    )).fetchall()
    if not broken:
        return

    for order_id, created_at in broken:
        group_cycle = conn.execute(sa.text(
            """
            SELECT b.id
            FROM settlement_batches b
            WHERE b.settlement_type = 'group'
              AND b.status = 'confirmed'
              AND b.confirmed_at IS NOT NULL
              AND b.confirmed_at <= :created_at
            ORDER BY b.confirmed_at DESC, b.id DESC
            LIMIT 1
            """
        ), {"created_at": created_at}).scalar()
        conn.execute(
            sa.text("UPDATE orders SET cycle_id = :cycle_id WHERE id = :order_id"),
            {"cycle_id": group_cycle, "order_id": order_id},
        )


def downgrade() -> None:
    # Data repair is intentionally not reversible: restoring the dispatcher
    # cycle ids would re-introduce the numbering bug.
    pass
