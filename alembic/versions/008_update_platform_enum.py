"""update platform enum vk to vk_video

Revision ID: 008_update_platform_enum
Revises: 007_create_user_configs
Create Date: 2026-01-05 12:15:00.000000

"""

from alembic import op

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("UPDATE user_credentials SET platform = 'vk_video' WHERE platform = 'vk'")
    op.execute("UPDATE output_presets SET platform = 'vk_video' WHERE platform = 'vk'")
    op.execute("UPDATE input_sources SET source_type = 'VK_VIDEO' WHERE source_type = 'VK'")


def downgrade() -> None:
    op.execute("UPDATE user_credentials SET platform = 'vk' WHERE platform = 'vk_video'")
    op.execute("UPDATE output_presets SET platform = 'vk' WHERE platform = 'vk_video'")
    op.execute("UPDATE input_sources SET source_type = 'VK' WHERE source_type = 'VK_VIDEO'")
