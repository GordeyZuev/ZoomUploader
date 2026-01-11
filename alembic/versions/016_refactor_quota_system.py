"""Refactor quota system with subscription plans

Revision ID: 016
Revises: 015
Create Date: 2026-01-09 12:00:00.000000

This migration refactors the quota system to support:
- Subscription plans (Free, Plus, Pro, Enterprise)
- Custom quotas per user
- Pay-as-you-go support (for future)
- Quota usage history by period
- Audit trail for quota changes
"""
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision = '016'
down_revision = '015'
branch_labels = None
depends_on = None


def upgrade():
    """Upgrade to new quota system with subscription plans."""

    # ========================================
    # 1. CREATE NEW TABLES
    # ========================================

    # 1.1 Create subscription_plans table
    op.create_table(
        'subscription_plans',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('display_name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),

        # Included quotas (NULL = unlimited)
        sa.Column('included_recordings_per_month', sa.Integer(), nullable=True),
        sa.Column('included_storage_gb', sa.Integer(), nullable=True),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=True),
        sa.Column('max_automation_jobs', sa.Integer(), nullable=True),
        sa.Column('min_automation_interval_hours', sa.Integer(), nullable=True),

        # Subscription pricing
        sa.Column('price_monthly', sa.Numeric(10, 2), nullable=False, server_default='0'),
        sa.Column('price_yearly', sa.Numeric(10, 2), nullable=False, server_default='0'),

        # Pay-as-you-go pricing (for future)
        sa.Column('overage_price_per_unit', sa.Numeric(10, 4), nullable=True),
        sa.Column('overage_unit_type', sa.String(length=50), nullable=True),

        # Metadata
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sort_order', sa.Integer(), nullable=False, server_default='0'),

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name', name='uq_subscription_plans_name'),
    )
    op.create_index('ix_subscription_plans_name', 'subscription_plans', ['name'])
    op.create_index('ix_subscription_plans_active', 'subscription_plans', ['is_active'])

    # 1.2 Create user_subscriptions table
    op.create_table(
        'user_subscriptions',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('plan_id', sa.Integer(), nullable=False),

        # Custom quotas (override plan defaults, NULL = use from plan)
        sa.Column('custom_max_recordings_per_month', sa.Integer(), nullable=True),
        sa.Column('custom_max_storage_gb', sa.Integer(), nullable=True),
        sa.Column('custom_max_concurrent_tasks', sa.Integer(), nullable=True),
        sa.Column('custom_max_automation_jobs', sa.Integer(), nullable=True),
        sa.Column('custom_min_automation_interval_hours', sa.Integer(), nullable=True),

        # Pay-as-you-go control (for future)
        sa.Column('pay_as_you_go_enabled', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('pay_as_you_go_monthly_limit', sa.Numeric(10, 2), nullable=True),

        # Subscription period
        sa.Column('starts_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('expires_at', sa.DateTime(), nullable=True),

        # Audit
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('modified_by', sa.Integer(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['subscription_plans.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['modified_by'], ['users.id'], ondelete='SET NULL'),
        sa.UniqueConstraint('user_id', name='uq_user_subscriptions_user_id'),
    )
    op.create_index('ix_user_subscriptions_user_id', 'user_subscriptions', ['user_id'])
    op.create_index('ix_user_subscriptions_plan_id', 'user_subscriptions', ['plan_id'])

    # 1.3 Create quota_usage table
    op.create_table(
        'quota_usage',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('period', sa.Integer(), nullable=False),  # YYYYMM format

        # Usage counters
        sa.Column('recordings_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('storage_bytes', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('concurrent_tasks_count', sa.Integer(), nullable=False, server_default='0'),

        # Overage counters (for future billing)
        sa.Column('overage_recordings_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('overage_cost', sa.Numeric(10, 2), nullable=False, server_default='0'),

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('user_id', 'period', name='uq_quota_usage_user_period'),
    )
    op.create_index('ix_quota_usage_user_period', 'quota_usage', ['user_id', 'period'], postgresql_using='btree')
    op.create_index('ix_quota_usage_period', 'quota_usage', ['period'])

    # 1.4 Create quota_change_history table
    op.create_table(
        'quota_change_history',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),

        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('change_type', sa.String(length=50), nullable=False),

        # What changed
        sa.Column('old_plan_id', sa.Integer(), nullable=True),
        sa.Column('new_plan_id', sa.Integer(), nullable=True),
        sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),

        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),

        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['old_plan_id'], ['subscription_plans.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['new_plan_id'], ['subscription_plans.id'], ondelete='SET NULL'),
    )
    op.create_index('ix_quota_change_history_user', 'quota_change_history', ['user_id', 'created_at'])
    op.create_index('ix_quota_change_history_type', 'quota_change_history', ['change_type'])

    # ========================================
    # 2. SEED SUBSCRIPTION PLANS
    # ========================================

    # Insert default subscription plans
    connection = op.get_bind()

    # Free plan
    connection.execute(sa.text("""
        INSERT INTO subscription_plans (
            name, display_name, description,
            included_recordings_per_month, included_storage_gb,
            max_concurrent_tasks, max_automation_jobs, min_automation_interval_hours,
            price_monthly, price_yearly,
            overage_price_per_unit, overage_unit_type,
            is_active, sort_order
        ) VALUES (
            'free', 'Free Plan', 'Perfect for getting started',
            10, 5, 1, 0, NULL,
            0.00, 0.00,
            0.50, 'recording',
            true, 1
        )
    """))

    # Plus plan
    connection.execute(sa.text("""
        INSERT INTO subscription_plans (
            name, display_name, description,
            included_recordings_per_month, included_storage_gb,
            max_concurrent_tasks, max_automation_jobs, min_automation_interval_hours,
            price_monthly, price_yearly,
            overage_price_per_unit, overage_unit_type,
            is_active, sort_order
        ) VALUES (
            'plus', 'Plus Plan', 'For regular users',
            50, 25, 2, 3, 6,
            10.00, 100.00,
            0.40, 'recording',
            true, 2
        )
    """))

    # Pro plan
    connection.execute(sa.text("""
        INSERT INTO subscription_plans (
            name, display_name, description,
            included_recordings_per_month, included_storage_gb,
            max_concurrent_tasks, max_automation_jobs, min_automation_interval_hours,
            price_monthly, price_yearly,
            overage_price_per_unit, overage_unit_type,
            is_active, sort_order
        ) VALUES (
            'pro', 'Pro Plan', 'For professionals',
            200, 100, 5, 10, 1,
            30.00, 300.00,
            0.30, 'recording',
            true, 3
        )
    """))

    # Enterprise plan
    connection.execute(sa.text("""
        INSERT INTO subscription_plans (
            name, display_name, description,
            included_recordings_per_month, included_storage_gb,
            max_concurrent_tasks, max_automation_jobs, min_automation_interval_hours,
            price_monthly, price_yearly,
            overage_price_per_unit, overage_unit_type,
            is_active, sort_order
        ) VALUES (
            'enterprise', 'Enterprise Plan', 'Unlimited everything',
            NULL, NULL, 10, NULL, 1,
            0.00, 0.00,
            NULL, NULL,
            true, 4
        )
    """))

    # ========================================
    # 3. MIGRATE DATA FROM OLD user_quotas
    # ========================================

    # Get free plan id
    free_plan_result = connection.execute(sa.text("SELECT id FROM subscription_plans WHERE name = 'free'"))
    free_plan_id = free_plan_result.scalar()

    # Get current period (YYYYMM)
    current_period = int(datetime.now().strftime('%Y%m'))

    # Migrate all users to Free plan with their current usage
    connection.execute(sa.text(f"""
        INSERT INTO user_subscriptions (
            user_id, plan_id,
            custom_max_recordings_per_month, custom_max_storage_gb, custom_max_concurrent_tasks,
            custom_max_automation_jobs, custom_min_automation_interval_hours,
            pay_as_you_go_enabled, starts_at, notes
        )
        SELECT
            uq.user_id,
            {free_plan_id},
            CASE WHEN uq.max_recordings_per_month != 100 THEN uq.max_recordings_per_month ELSE NULL END,
            CASE WHEN uq.max_storage_gb != 50 THEN uq.max_storage_gb ELSE NULL END,
            CASE WHEN uq.max_concurrent_tasks != 3 THEN uq.max_concurrent_tasks ELSE NULL END,
            CASE WHEN uq.max_automation_jobs != 5 THEN uq.max_automation_jobs ELSE NULL END,
            CASE WHEN uq.min_automation_interval_hours != 1 THEN uq.min_automation_interval_hours ELSE NULL END,
            false,
            uq.created_at,
            'Migrated from old quota system'
        FROM user_quotas uq
    """))

    # Migrate current usage to quota_usage
    connection.execute(sa.text(f"""
        INSERT INTO quota_usage (
            user_id, period,
            recordings_count, storage_bytes, concurrent_tasks_count
        )
        SELECT
            uq.user_id,
            {current_period},
            uq.current_recordings_count,
            uq.current_storage_gb::bigint * 1024 * 1024 * 1024,  -- Convert GB to bytes
            uq.current_tasks_count
        FROM user_quotas uq
    """))

    # ========================================
    # 4. DROP OLD user_quotas TABLE
    # ========================================

    op.drop_index('ix_user_quotas_user_id', table_name='user_quotas')
    op.drop_table('user_quotas')


def downgrade():
    """Downgrade back to old quota system (data loss warning!)."""

    # WARNING: This will lose subscription plan information and usage history!

    # Recreate old user_quotas table
    op.create_table(
        'user_quotas',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('max_recordings_per_month', sa.Integer(), nullable=False, server_default='100'),
        sa.Column('max_storage_gb', sa.Integer(), nullable=False, server_default='50'),
        sa.Column('max_concurrent_tasks', sa.Integer(), nullable=False, server_default='3'),
        sa.Column('max_automation_jobs', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('min_automation_interval_hours', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('current_recordings_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_storage_gb', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('current_tasks_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('quota_reset_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )
    op.create_index('ix_user_quotas_user_id', 'user_quotas', ['user_id'])

    # Try to restore data from user_subscriptions and quota_usage
    connection = op.get_bind()

    # Get current period
    current_period = int(datetime.now().strftime('%Y%m'))

    # Restore quotas with current usage
    connection.execute(sa.text(f"""
        INSERT INTO user_quotas (
            user_id,
            max_recordings_per_month, max_storage_gb, max_concurrent_tasks,
            max_automation_jobs, min_automation_interval_hours,
            current_recordings_count, current_storage_gb, current_tasks_count,
            quota_reset_at, created_at
        )
        SELECT
            us.user_id,
            COALESCE(us.custom_max_recordings_per_month, sp.included_recordings_per_month, 100),
            COALESCE(us.custom_max_storage_gb, sp.included_storage_gb, 50),
            COALESCE(us.custom_max_concurrent_tasks, sp.max_concurrent_tasks, 3),
            COALESCE(us.custom_max_automation_jobs, sp.max_automation_jobs, 5),
            COALESCE(us.custom_min_automation_interval_hours, sp.min_automation_interval_hours, 1),
            COALESCE(qu.recordings_count, 0),
            COALESCE(qu.storage_bytes / (1024 * 1024 * 1024), 0),
            COALESCE(qu.concurrent_tasks_count, 0),
            NOW() + INTERVAL '30 days',
            us.created_at
        FROM user_subscriptions us
        JOIN subscription_plans sp ON us.plan_id = sp.id
        LEFT JOIN quota_usage qu ON us.user_id = qu.user_id AND qu.period = {current_period}
    """))

    # Drop new tables
    op.drop_index('ix_quota_change_history_type', table_name='quota_change_history')
    op.drop_index('ix_quota_change_history_user', table_name='quota_change_history')
    op.drop_table('quota_change_history')

    op.drop_index('ix_quota_usage_period', table_name='quota_usage')
    op.drop_index('ix_quota_usage_user_period', table_name='quota_usage')
    op.drop_table('quota_usage')

    op.drop_index('ix_user_subscriptions_plan_id', table_name='user_subscriptions')
    op.drop_index('ix_user_subscriptions_user_id', table_name='user_subscriptions')
    op.drop_table('user_subscriptions')

    op.drop_index('ix_subscription_plans_active', table_name='subscription_plans')
    op.drop_index('ix_subscription_plans_name', table_name='subscription_plans')
    op.drop_table('subscription_plans')

