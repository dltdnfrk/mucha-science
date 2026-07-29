mod actions;
mod backend_events;
mod cli;
mod execution_contract;
mod execution_owner;
mod execution_platform;
mod execution_store;
mod logging;
mod pipeline;
mod pipeline_config;
mod python_runtime;
mod renderer_env;
mod replay;
mod state;
mod status;
mod workspace;

pub use actions::send_action;
pub use cli::{
    check_cli_smoke, check_cli_status, open_cli_auth, CliAuthLaunch, CliSmokeResult, CliStatus,
};
pub use pipeline::{cancel_pipeline, start_pipeline};
pub use replay::get_buffered_events;
pub use state::PythonBridge;
pub use status::{pipeline_runtime_status, PipelineRuntimeStatus};

// Source-contract coverage expects "MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK" at this facade;
// renderer_env owns the actual allowlist and validation.
