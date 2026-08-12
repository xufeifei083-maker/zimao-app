// Release builds are native Windows GUI applications.  Keeping the console
// subsystem enabled creates an unnecessary black terminal window; it is not
// required for either the Local Agent or ComfyUI background processes.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    flynotes_ai_control_center_lib::run();
}
