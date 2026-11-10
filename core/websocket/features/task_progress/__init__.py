"""Celery task progress WebSocket feature (ws/tasks/{task_id}).

Package marker only. The route is registered by ``handler.py`` (imported by
``core.websocket.features``). Do not register routes here: the first registration
wins, so a second handler here would shadow the maintained one.
"""
