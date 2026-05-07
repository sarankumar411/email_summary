"""Initial schema.

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-07
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    role_enum = sa.Enum("accountant", "admin", "superuser", name="accountant_role")
    email_direction_enum = sa.Enum("inbound", "outbound", name="email_direction")
    refresh_status_enum = sa.Enum(
        "success",
        "skipped_no_new_emails",
        "failed",
        name="refresh_audit_status",
    )
    job_type_enum = sa.Enum("refresh_summary", name="job_type")
    job_status_enum = sa.Enum("queued", "running", "completed", "failed", "skipped", name="job_status")

    op.create_table(
        "firms",
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_firms"),
    )

    op.create_table(
        "accountants",
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", role_enum, server_default="accountant", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name="fk_accountants_firm_id_firms"),
        sa.PrimaryKeyConstraint("id", name="pk_accountants"),
        sa.UniqueConstraint("email", name="uq_accountants_email"),
    )
    op.create_index("ix_accountants_email", "accountants", ["email"])
    op.create_index("ix_accountants_firm_id", "accountants", ["firm_id"])
    op.create_index("ix_accountants_firm_role", "accountants", ["firm_id", "role"])

    op.create_table(
        "clients",
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name="fk_clients_firm_id_firms"),
        sa.PrimaryKeyConstraint("id", name="pk_clients"),
    )
    op.create_index("ix_clients_firm_id", "clients", ["firm_id"])

    op.create_table(
        "accountant_client_assignments",
        sa.Column("accountant_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["accountant_id"],
            ["accountants.id"],
            name="fk_accountant_client_assignments_accountant_id_accountants",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_accountant_client_assignments_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("accountant_id", "client_id", name="pk_accountant_client_assignments"),
    )
    op.create_index(
        "ix_accountant_client_assignments_accountant_id",
        "accountant_client_assignments",
        ["accountant_id"],
    )
    op.create_index(
        "ix_accountant_client_assignments_client_id",
        "accountant_client_assignments",
        ["client_id"],
    )

    op.create_table(
        "client_emails",
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("email_address", sa.String(length=255), nullable=False),
        sa.Column("is_primary", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_client_emails_client_id_clients",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name="fk_client_emails_firm_id_firms"),
        sa.PrimaryKeyConstraint("id", name="pk_client_emails"),
        sa.UniqueConstraint("client_id", "email_address", name="uq_client_emails_client_email"),
        sa.UniqueConstraint("firm_id", "email_address", name="uq_client_emails_firm_email"),
    )
    op.create_index("ix_client_emails_client_id", "client_emails", ["client_id"])
    op.create_index("ix_client_emails_email_address", "client_emails", ["email_address"])
    op.create_index("ix_client_emails_firm_id", "client_emails", ["firm_id"])

    op.create_table(
        "emails",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("sender_accountant_id", sa.Uuid(), nullable=True),
        sa.Column("sender_email", sa.String(length=255), nullable=False),
        sa.Column("recipients", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("cc", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction", email_direction_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_emails_client_id_clients"),
        sa.ForeignKeyConstraint(
            ["sender_accountant_id"],
            ["accountants.id"],
            name="fk_emails_sender_accountant_id_accountants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_emails"),
    )
    op.create_index("ix_emails_client_id", "emails", ["client_id"])
    op.create_index("ix_emails_client_sent_at", "emails", ["client_id", "sent_at"])
    op.create_index("ix_emails_sent_at", "emails", ["sent_at"])
    op.create_index("ix_emails_thread_id", "emails", ["thread_id"])

    op.create_table(
        "email_summaries",
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("firm_id", sa.Uuid(), nullable=False),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_nonce", sa.LargeBinary(), nullable=False),
        sa.Column("encryption_key_version", sa.Integer(), nullable=False),
        sa.Column("emails_analyzed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_refreshed_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("gemini_model_version", sa.String(length=64), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_email_summaries_client_id_clients"),
        sa.ForeignKeyConstraint(["firm_id"], ["firms.id"], name="fk_email_summaries_firm_id_firms"),
        sa.PrimaryKeyConstraint("id", name="pk_email_summaries"),
        sa.UniqueConstraint("client_id", name="uq_email_summaries_client_id"),
    )
    op.create_index("ix_email_summaries_client_id", "email_summaries", ["client_id"])
    op.create_index("ix_email_summaries_firm_id", "email_summaries", ["firm_id"])

    op.create_table(
        "jobs",
        sa.Column("job_type", job_type_enum, nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=True),
        sa.Column("triggered_by_accountant_id", sa.Uuid(), nullable=False),
        sa.Column("status", job_status_enum, server_default="queued", nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"], name="fk_jobs_client_id_clients"),
        sa.ForeignKeyConstraint(
            ["triggered_by_accountant_id"],
            ["accountants.id"],
            name="fk_jobs_triggered_by_accountant_id_accountants",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index("ix_jobs_client_id", "jobs", ["client_id"])
    op.create_index("ix_jobs_created_at", "jobs", ["created_at"])
    op.create_index("ix_jobs_expires_at", "jobs", ["expires_at"])

    op.create_table(
        "refresh_audit_log",
        sa.Column("summary_id", sa.Uuid(), nullable=True),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_by_accountant_id", sa.Uuid(), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("emails_processed", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", refresh_status_enum, nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_refresh_audit_log_client_id_clients",
        ),
        sa.ForeignKeyConstraint(
            ["summary_id"],
            ["email_summaries.id"],
            name="fk_refresh_audit_log_summary_id_email_summaries",
        ),
        sa.ForeignKeyConstraint(
            ["triggered_by_accountant_id"],
            ["accountants.id"],
            name="fk_refresh_audit_log_triggered_by_accountant_id_accountants",
        ),
        sa.CheckConstraint(
            "summary_id IS NOT NULL OR status = 'failed'",
            name="ck_refresh_audit_log_summary_required_unless_failed",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_refresh_audit_log"),
    )
    op.create_index("ix_refresh_audit_log_client_id", "refresh_audit_log", ["client_id"])
    op.create_index("ix_refresh_audit_log_summary_id", "refresh_audit_log", ["summary_id"])
    op.create_index("ix_refresh_audit_log_triggered_at", "refresh_audit_log", ["triggered_at"])


def downgrade() -> None:
    op.drop_index("ix_refresh_audit_log_triggered_at", table_name="refresh_audit_log")
    op.drop_index("ix_refresh_audit_log_summary_id", table_name="refresh_audit_log")
    op.drop_index("ix_refresh_audit_log_client_id", table_name="refresh_audit_log")
    op.drop_table("refresh_audit_log")
    op.drop_index("ix_jobs_expires_at", table_name="jobs")
    op.drop_index("ix_jobs_created_at", table_name="jobs")
    op.drop_index("ix_jobs_client_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_email_summaries_firm_id", table_name="email_summaries")
    op.drop_index("ix_email_summaries_client_id", table_name="email_summaries")
    op.drop_table("email_summaries")
    op.drop_index("ix_emails_thread_id", table_name="emails")
    op.drop_index("ix_emails_sent_at", table_name="emails")
    op.drop_index("ix_emails_client_sent_at", table_name="emails")
    op.drop_index("ix_emails_client_id", table_name="emails")
    op.drop_table("emails")
    op.drop_index("ix_client_emails_email_address", table_name="client_emails")
    op.drop_index("ix_client_emails_firm_id", table_name="client_emails")
    op.drop_index("ix_client_emails_client_id", table_name="client_emails")
    op.drop_table("client_emails")
    op.drop_index(
        "ix_accountant_client_assignments_client_id",
        table_name="accountant_client_assignments",
    )
    op.drop_index(
        "ix_accountant_client_assignments_accountant_id",
        table_name="accountant_client_assignments",
    )
    op.drop_table("accountant_client_assignments")
    op.drop_index("ix_clients_firm_id", table_name="clients")
    op.drop_table("clients")
    op.drop_index("ix_accountants_firm_role", table_name="accountants")
    op.drop_index("ix_accountants_firm_id", table_name="accountants")
    op.drop_index("ix_accountants_email", table_name="accountants")
    op.drop_table("accountants")
    op.drop_table("firms")

    sa.Enum(name="job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="job_type").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="refresh_audit_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="email_direction").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="accountant_role").drop(op.get_bind(), checkfirst=True)
