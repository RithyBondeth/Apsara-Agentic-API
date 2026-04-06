# Import all models here so that Alembic can discover them
# via Base.metadata
from app.db.base_class import Base  # noqa
from app.models.user import UserModel  # noqa
