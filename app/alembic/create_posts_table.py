from alembic import op
import sqlalchemy as sa
import uuid

revision = 'create_posts_table'
# Replace with the actual previous revision ID
down_revision = 'previous_revision_id'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'posts',
        sa.Column('id', sa.String(36), primary_key=True,
                  default=lambda: str(uuid.uuid4())),
        sa.Column('user_id', sa.String(36), sa.ForeignKey(
            'users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('content', sa.Text, nullable=False),
        sa.Column('image_url', sa.String(255)),
        sa.Column('created_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp()),
        sa.Column('updated_at', sa.DateTime, nullable=False,
                  server_default=sa.func.current_timestamp(), onupdate=sa.func.current_timestamp())
    )


def downgrade():
    op.drop_table('posts')
