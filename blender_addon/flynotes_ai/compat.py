"""Small compatibility helpers shared by Blender 4.x and 5.x."""


def sequence_collection(sequence_editor):
    """Return the active VSE collection across Blender's renamed APIs."""
    if sequence_editor is None:
        return None
    for name in ("strips", "sequences"):
        collection = getattr(sequence_editor, name, None)
        if collection is not None:
            return collection
    return None


def ensure_sequence_collection(scene):
    scene.sequence_editor_create()
    collection = sequence_collection(scene.sequence_editor)
    if collection is None:
        raise RuntimeError("当前 Blender 没有可用的视频序列编辑器")
    return collection


def set_image_media_type(image_settings, media_type):
    """Set media_type where supported; Blender 4.x may omit this property."""
    if hasattr(image_settings, "media_type"):
        image_settings.media_type = media_type
