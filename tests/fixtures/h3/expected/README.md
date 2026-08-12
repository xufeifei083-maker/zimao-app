# H3 E2E expected results

This directory intentionally contains no generated video. The release test
creates its evidence under `test-results/<version>/blender-h3/` and validates
the generated media with `ffprobe`. The immutable input hashes are recorded in
the parent `manifest.json`.
