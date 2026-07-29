#[path = "scientific_bridge/commands.rs"]
mod commands;
#[path = "scientific_bridge/io.rs"]
mod io;
#[path = "scientific_bridge/monitor.rs"]
mod monitor;
#[path = "scientific_bridge/process.rs"]
mod process;
#[path = "scientific_bridge/protocol.rs"]
mod protocol;
#[path = "scientific_bridge/sha256.rs"]
mod sha256;
#[path = "scientific_bridge/sidecar.rs"]
mod sidecar;
#[path = "scientific_bridge/state.rs"]
mod state;

pub use commands::{start_scientific_sidecar, stop_scientific_sidecar, write_envelope};
pub use state::ScientificBridge;

pub(crate) use process::shutdown_bridge_for_exit;
pub(crate) use sidecar::{
    establish_muchanipo_home, resolve_packaged_sidecar_path, scientific_sidecar_name,
    SCIENTIFIC_SIDECAR_BASE,
};
pub(crate) use state::BridgePhase;

#[cfg(test)]
pub(crate) use io::bounded_line_for_test;
#[cfg(test)]
pub(crate) use protocol::{
    accept_welcome_for_test, action_is_authorized_for_test, parse_backend_line_for_test,
};

use super::scientific_events::{BackendEvent, BackendMessage, BackendMode, ScientificEnvelope};
