import queue
import threading
import traceback


_completed = queue.Queue()
_active = set()
_lock = threading.Lock()
_redraw_requested = threading.Event()


def is_active(key):
    with _lock:
        return key in _active


def request_redraw():
    """Ask Blender's main thread to redraw on the next throttled timer tick."""
    _redraw_requested.set()


def start(key, work, on_success=None, on_error=None):
    """Run non-Blender work outside the UI thread and return results on a Blender timer."""
    with _lock:
        if key in _active:
            return False
        _active.add(key)

    def runner():
        try:
            _completed.put((key, True, work(), on_success, on_error))
        except Exception as error:
            _completed.put((key, False, error, on_success, on_error))

    threading.Thread(target=runner, name=f"Flynotes-{key}", daemon=True).start()
    return True


def pump():
    changed = False
    while True:
        try:
            key, ok, value, on_success, on_error = _completed.get_nowait()
        except queue.Empty:
            break
        with _lock:
            _active.discard(key)
        changed = True
        try:
            if ok and on_success:
                on_success(value)
            elif not ok and on_error:
                on_error(value)
        except Exception as error:
            # Timer callbacks run on Blender's main thread. Never hide an
            # add-on state-update failure: it would leave the UI permanently
            # showing a stale task even though the HTTP request succeeded.
            traceback.print_exc()
            if on_error:
                try:
                    on_error(error)
                except Exception:
                    traceback.print_exc()
    should_redraw = changed or _redraw_requested.is_set()
    if should_redraw:
        _redraw_requested.clear()
        try:
            import bpy
            for window in bpy.context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except Exception:
            pass
    return 0.25


def clear():
    with _lock:
        _active.clear()
    _redraw_requested.clear()
    while True:
        try:
            _completed.get_nowait()
        except queue.Empty:
            return
