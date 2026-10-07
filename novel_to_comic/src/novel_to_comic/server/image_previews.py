"""Bind transient image observations to the job's existing project stream."""

from novel_to_comic.ai.image_previews import image_preview_events
from .deps import event_key
from .event_channel import EventChannel


def preview_events(app, pkey, project_dir, stage):
    channels = getattr(app.state, "event_queues", None)
    if channels is None:
        channels = app.state.event_queues = {}
    channel = channels.setdefault(event_key(pkey, project_dir), EventChannel())
    return image_preview_events(project_dir, stage, channel.put_nowait)
