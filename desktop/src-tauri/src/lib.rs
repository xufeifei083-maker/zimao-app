use std::fs;
use std::io::{BufReader, Read};
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;

use tauri::Manager;

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const AGENT_VERSION: &str = "0.1.0";

fn agent_is_running() -> bool {
    let address: SocketAddr = "127.0.0.1:17980".parse().expect("static Agent address");
    TcpStream::connect_timeout(&address, Duration::from_millis(250)).is_ok()
}

fn bundled_agent(resource_dir: &Path) -> Option<PathBuf> {
    [
        resource_dir.join("resources/agent/flynotes-local-agent.exe"),
        resource_dir.join("agent/flynotes-local-agent.exe"),
        resource_dir.join("flynotes-local-agent.exe"),
    ]
    .into_iter()
    .find(|candidate| candidate.is_file())
}

fn files_match(source: &Path, installed: &Path) -> bool {
    let (Ok(source_file), Ok(installed_file)) = (fs::File::open(source), fs::File::open(installed))
    else {
        return false;
    };
    let (Ok(source_metadata), Ok(installed_metadata)) =
        (source_file.metadata(), installed_file.metadata())
    else {
        return false;
    };
    if source_metadata.len() != installed_metadata.len() {
        return false;
    }
    let mut source_reader = BufReader::new(source_file);
    let mut installed_reader = BufReader::new(installed_file);
    let mut source_buffer = [0_u8; 64 * 1024];
    let mut installed_buffer = [0_u8; 64 * 1024];
    loop {
        let Ok(source_read) = source_reader.read(&mut source_buffer) else {
            return false;
        };
        let Ok(installed_read) = installed_reader.read(&mut installed_buffer) else {
            return false;
        };
        if source_read != installed_read
            || source_buffer[..source_read] != installed_buffer[..installed_read]
        {
            return false;
        }
        if source_read == 0 {
            return true;
        }
    }
}

fn ensure_agent(app: &tauri::AppHandle) -> Result<(), String> {
    if agent_is_running() {
        return Ok(());
    }
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|error| error.to_string())?;
    let bundled = bundled_agent(&resource_dir)
        .ok_or_else(|| format!("未找到本地服务程序：{}", resource_dir.display()))?;
    let local_app_data = std::env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .ok_or_else(|| "未找到 LOCALAPPDATA".to_string())?;
    let install_dir = local_app_data
        .join("FlynotesAI")
        .join("bin")
        .join(AGENT_VERSION);
    fs::create_dir_all(&install_dir).map_err(|error| error.to_string())?;
    let installed = install_dir.join("flynotes-local-agent.exe");
    if !files_match(&bundled, &installed) {
        fs::copy(&bundled, &installed).map_err(|error| error.to_string())?;
    }

    let mut command = Command::new(installed);
    command
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null());
    #[cfg(windows)]
    command.creation_flags(0x0000_0008 | 0x0000_0200 | 0x0800_0000);
    command.spawn().map_err(|error| error.to_string())?;
    Ok(())
}

/// Make the bundled Local Agent available on demand as well as at app startup.
///
/// The service page uses this command for its single "start all" action.  It
/// is intentionally idempotent: when the Agent is already listening, nothing
/// is restarted and the existing process is left alone.
#[tauri::command]
fn start_agent(app: tauri::AppHandle) -> Result<(), String> {
    ensure_agent(&app)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![start_agent])
        .setup(|app| {
            if let Err(error) = ensure_agent(app.handle()) {
                eprintln!("Local Agent startup warning: {error}");
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Flynotes AI Control Center");
}
