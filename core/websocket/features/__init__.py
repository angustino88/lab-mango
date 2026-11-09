"""Import all WS handler modules to trigger route registration."""
from core.websocket.features.broadcast_notifications import handler as _bn  # noqa: F401
from core.websocket.features.computing_activity import handler as _ca  # noqa: F401
from core.websocket.features.equipment_status import handler as _es  # noqa: F401
from core.websocket.features.monitoring_dashboard import handler as _md  # noqa: F401
from core.websocket.features.task_progress import handler as _tp  # noqa: F401
from core.websocket.features.user_notifications import handler as _un  # noqa: F401
