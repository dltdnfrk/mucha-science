#[derive(Clone, Copy)]
pub(super) enum PipelineMode {
    Full,
    Stub,
}

impl PipelineMode {
    pub(super) fn from_option(value: Option<&str>) -> Self {
        match value {
            Some("stub") => Self::Stub,
            _ => Self::Full,
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Full => "full",
            Self::Stub => "stub",
        }
    }
}

#[derive(Debug, Clone, Copy)]
pub(super) enum ResearchDepth {
    Shallow,
    Deep,
    Max,
    Superdeep,
}

impl ResearchDepth {
    pub(super) fn parse(value: Option<&str>) -> Result<Self, String> {
        match value.map(str::trim).filter(|value| !value.is_empty()) {
            None | Some("deep") => Ok(Self::Deep),
            Some("shallow") => Ok(Self::Shallow),
            Some("max") => Ok(Self::Max),
            Some("superdeep") => Ok(Self::Superdeep),
            Some(other) => Err(format!(
                "unsupported research depth: {other}; expected shallow, deep, max, or superdeep"
            )),
        }
    }

    const fn as_str(self) -> &'static str {
        match self {
            Self::Shallow => "shallow",
            Self::Deep => "deep",
            Self::Max => "max",
            Self::Superdeep => "superdeep",
        }
    }
}

pub(super) fn pipeline_command_args(
    topic: &str,
    pipeline_mode: PipelineMode,
    research_depth: ResearchDepth,
) -> Vec<String> {
    [
        "-u",
        "-m",
        "muchanipo",
        "serve",
        "--topic",
        topic,
        "--pipeline",
        pipeline_mode.as_str(),
        "--depth",
        research_depth.as_str(),
    ]
    .iter()
    .map(|value| (*value).to_string())
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn research_depth_defaults_to_deep_and_accepts_valid_depths() {
        for (input, expected) in [
            (None, "deep"),
            (Some(""), "deep"),
            (Some("shallow"), "shallow"),
            (Some("deep"), "deep"),
            (Some("max"), "max"),
            (Some("superdeep"), "superdeep"),
        ] {
            assert_eq!(
                ResearchDepth::parse(input).expect("valid depth").as_str(),
                expected
            );
        }
    }

    #[test]
    fn research_depth_rejects_unknown_depth() {
        let error = ResearchDepth::parse(Some("quick")).expect_err("invalid depth");
        assert!(error.contains("unsupported research depth"));
        for expected in ["shallow", "deep", "max", "superdeep"] {
            assert!(error.contains(expected));
        }
    }

    #[test]
    fn pipeline_command_args_include_selected_depth() {
        assert_eq!(
            pipeline_command_args("topic", PipelineMode::Full, ResearchDepth::Max),
            vec![
                "-u",
                "-m",
                "muchanipo",
                "serve",
                "--topic",
                "topic",
                "--pipeline",
                "full",
                "--depth",
                "max",
            ]
        );
    }
}
