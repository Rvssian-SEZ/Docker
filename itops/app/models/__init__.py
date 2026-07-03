# Import all models here so SQLAlchemy's metadata and Alembic autogenerate
# can discover every table in one place.
from models.user import User  # noqa: F401
from models.asset import ITAsset, AssetStatus, AssetCategory  # noqa: F401
from models.equipment import Equipment, EquipmentStatus, LendingRecord  # noqa: F401
