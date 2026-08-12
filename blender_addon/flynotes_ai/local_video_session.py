import os
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass, field


ACTIVE_PHASES = {"preparing", "rendering_frames", "encoding", "cancelling"}
RETRY_PHASES = {"encode_failed", "encode_cancelled"}

PHASE_LABELS = {
    "idle": "尚未生成视图模式视频",
    "preparing": "正在准备视图模式渲染",
    "rendering_frames": "正在渲染视图模式帧",
    "encoding": "正在合成 MP4",
    "cancelling": "正在取消",
    "ready": "视图模式 MP4 已就绪",
    "frame_failed": "视图模式帧渲染失败",
    "encode_failed": "MP4 合成失败",
    "frame_cancelled": "视图模式帧渲染已取消",
    "encode_cancelled": "MP4 合成已取消",
    "submitted": "已提交 AI 渲染",
}


@dataclass
class LocalVideoSession:
    session_id: str
    work_dir: str
    frame_dir: str
    output_path: str
    source_scene_name: str
    camera_name: str
    frame_start: int
    frame_end: int
    fps: int
    fps_base: float
    phase: str = "preparing"
    progress: float = 0.0
    message: str = ""
    error: str = ""
    frame_paths: list[str] = field(default_factory=list)
    rendered_frames: int = 0
    encoded_frames: int = 0
    width: int = 0
    height: int = 0
    cancel_requested: bool = False
    created_at: float = field(default_factory=time.time)

    @property
    def frame_count(self):
        return max(0, self.frame_end - self.frame_start + 1)

    @property
    def is_active(self):
        return self.phase in ACTIVE_PHASES

    @property
    def can_reencode(self):
        return self.phase in RETRY_PHASES and self.has_complete_frames

    @property
    def has_complete_frames(self):
        return (
            len(self.frame_paths) == self.frame_count
            and self.frame_count > 0
            and all(os.path.isfile(path) for path in self.frame_paths)
        )

    @property
    def phase_label(self):
        return PHASE_LABELS.get(self.phase, self.phase)

    def set_phase(self, phase, *, progress=None, message="", error=""):
        self.phase = phase
        if progress is not None:
            self.progress = max(0.0, min(1.0, float(progress)))
        self.message = message
        self.error = error


def create_session(scene, camera, frame_start=None, frame_end=None, fps=None):
    session_id = uuid.uuid4().hex
    work_dir = tempfile.mkdtemp(prefix=f"flynotes_local_video_{session_id[:8]}_")
    frame_dir = os.path.join(work_dir, "frames")
    os.makedirs(frame_dir, exist_ok=True)
    return LocalVideoSession(
        session_id=session_id,
        work_dir=work_dir,
        frame_dir=frame_dir,
        output_path=os.path.join(work_dir, "workbench.mp4"),
        source_scene_name=scene.name,
        camera_name=camera.name,
        frame_start=int(scene.frame_start if frame_start is None else frame_start),
        frame_end=int(scene.frame_end if frame_end is None else frame_end),
        fps=int(scene.render.fps if fps is None else fps),
        fps_base=float(scene.render.fps_base or 1.0),
    )


def clear_session_files(session):
    if not session or not session.work_dir:
        return
    work_dir = os.path.abspath(session.work_dir)
    temp_root = os.path.abspath(tempfile.gettempdir())
    prefix = os.path.join(temp_root, "flynotes_local_video_")
    if work_dir.startswith(prefix) and os.path.isdir(work_dir):
        shutil.rmtree(work_dir, ignore_errors=True)


def clear_frame_files(session):
    if not session:
        return
    for path in tuple(session.frame_paths):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    try:
        os.rmdir(session.frame_dir)
    except OSError:
        pass
    session.frame_paths.clear()
