# Blender MiniMax H3 release tests

`run_h3_e2e.py` is executed by Blender 5.0 itself. Each invocation enables the
release-candidate add-on from this repository, submits one H3 job through its
operators, waits for Local Agent and ComfyUI, adds the result to the VSE, saves
the `.blend` file, and writes reproducible evidence.

The suite fails if port 7860 is listening, if Flynotes authentication is
required, if the output is not registered in the Agent asset library, or if
`ffprobe` cannot validate a 480x832 video stream.
