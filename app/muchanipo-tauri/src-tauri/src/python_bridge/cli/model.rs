#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum CliName {
    Claude,
    Codex,
    Gemini,
    Kimi,
    Opencode,
}

pub(super) const ALL_CLIS: [CliName; 5] = [
    CliName::Claude,
    CliName::Codex,
    CliName::Gemini,
    CliName::Kimi,
    CliName::Opencode,
];

pub(super) struct SmokeSpec {
    pub(super) args: &'static [&'static str],
    pub(super) input: Option<&'static str>,
}

impl CliName {
    pub(super) fn parse(raw: &str) -> Result<Self, String> {
        let normalized = raw.trim().to_lowercase();
        match normalized.as_str() {
            "claude" => Ok(Self::Claude),
            "codex" => Ok(Self::Codex),
            "gemini" => Ok(Self::Gemini),
            "kimi" => Ok(Self::Kimi),
            "opencode" => Ok(Self::Opencode),
            _ => Err(format!("unsupported CLI: {normalized}")),
        }
    }

    pub(super) const fn as_str(self) -> &'static str {
        match self {
            Self::Claude => "claude",
            Self::Codex => "codex",
            Self::Gemini => "gemini",
            Self::Kimi => "kimi",
            Self::Opencode => "opencode",
        }
    }

    pub(super) const fn login_command(self) -> &'static str {
        match self {
            Self::Claude => "claude auth login",
            Self::Codex => "codex login",
            Self::Gemini => "gemini -i /auth",
            Self::Kimi => "kimi login",
            Self::Opencode => "opencode auth login",
        }
    }

    pub(super) const fn smoke_spec(self) -> SmokeSpec {
        match self {
            Self::Claude => SmokeSpec {
                args: &["-p", "--output-format", "text", "Reply with OK only."],
                input: None,
            },
            Self::Codex => SmokeSpec {
                args: &[
                    "exec",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "Reply with OK only.",
                ],
                input: None,
            },
            Self::Gemini => SmokeSpec {
                args: &["-p", "Reply with OK only.", "-m", "gemini-2.5-flash"],
                input: None,
            },
            Self::Kimi => SmokeSpec {
                args: &[
                    "--work-dir",
                    ".",
                    "--print",
                    "--final-message-only",
                    "--input-format",
                    "text",
                ],
                input: Some("Reply with OK only."),
            },
            Self::Opencode => SmokeSpec {
                args: &[
                    "run",
                    "--pure",
                    "--model",
                    "opencode-go/kimi-k2.6",
                    "--format",
                    "json",
                    "Reply with OK only.",
                ],
                input: None,
            },
        }
    }

    pub(super) const fn diagnosis(self) -> &'static str {
        match self {
            Self::Claude => {
                "Pipeline uses `claude -p`; run the smoke test to verify OAuth/auth."
            }
            Self::Codex => {
                "Pipeline uses `codex exec`; version success does not prove native module/auth health."
            }
            Self::Gemini => {
                "Pipeline uses `gemini -p`; smoke test may expose OAuth, rate-limit, or CLI flag issues."
            }
            Self::Kimi => {
                "Pipeline uses `kimi --print`; run the smoke test to verify local Kimi auth."
            }
            Self::Opencode => {
                "Pipeline uses `opencode run`; smoke test verifies OpenCode auth/model access."
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cli_names_parse_normalized_input() {
        for (raw, expected) in [
            (" claude ", CliName::Claude),
            ("CODEX", CliName::Codex),
            ("Gemini", CliName::Gemini),
            ("kimi", CliName::Kimi),
            ("opencode", CliName::Opencode),
        ] {
            assert_eq!(CliName::parse(raw), Ok(expected));
        }
    }

    #[test]
    fn unsupported_cli_preserves_normalized_error_contract() {
        assert_eq!(
            CliName::parse(" UNKNOWN "),
            Err("unsupported CLI: unknown".to_string())
        );
    }

    #[test]
    fn cli_login_commands_are_known() {
        assert_eq!(CliName::Claude.login_command(), "claude auth login");
        assert_eq!(CliName::Codex.login_command(), "codex login");
        assert_eq!(CliName::Gemini.login_command(), "gemini -i /auth");
        assert_eq!(CliName::Kimi.login_command(), "kimi login");
        assert_eq!(CliName::Opencode.login_command(), "opencode auth login");
    }
}
