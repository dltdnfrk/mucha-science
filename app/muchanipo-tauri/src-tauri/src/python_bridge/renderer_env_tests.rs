use std::collections::HashMap;

use super::sanitize_renderer_envs;

fn env_map(entries: &[(&str, &str)]) -> HashMap<String, String> {
    entries
        .iter()
        .map(|(key, value)| ((*key).to_string(), (*value).to_string()))
        .collect()
}

#[test]
fn allows_only_expected_app_keys() {
    let entries = [
        ("MUCHANIPO_USE_CLI", "1"),
        ("OPENCODE_USE_CLI", "0"),
        ("MUCHANIPO_OFFLINE", "true"),
        ("MUCHANIPO_SOURCE_RESEARCH", "1"),
        ("MUCHANIPO_ONLINE", "1"),
        ("MUCHANIPO_REQUIRE_LIVE", "yes"),
        ("MUCHANIPO_VERIFICATION_ROUTING", "mimo_opencode_go_only"),
        ("MUCHANIPO_API_ROUTING", "mimo_opencode_go_only"),
        ("MUCHANIPO_MODEL_ROUTING", "mimo_opencode_go_only"),
        ("MUCHANIPO_PROVIDER_CHAIN", "opencode"),
        ("MUCHANIPO_OPENCODE_MODEL", "opencode/mimo-v2.5-pro"),
        ("MUCHANIPO_INTERVIEW_COUNSELLING", "1"),
        ("MUCHANIPO_PREFER_CLI", "0"),
        ("ANTHROPIC_API_KEY", "sk-ant"),
        ("GEMINI_API_KEY", "g-key"),
        ("KIMI_API_KEY", "k-key"),
        ("OPENAI_API_KEY", "sk-openai"),
        ("OPENCODE_API_KEY", "oc-key"),
        ("OPENCODE_GO_API_KEY", "oc-go-key"),
        ("XIAOMI_MIMO_API_KEY", "tp-key"),
        ("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"),
        (
            "XIAOMI_MIMO_BASE_URL",
            "https://token-plan-sgp.xiaomimimo.com/v1",
        ),
        ("MIMO_MODEL", "mimo-v2.5-pro"),
        ("MUCHANIPO_MIMO_MODEL", "mimo-v2.5-pro"),
        ("OPENALEX_EMAIL", "dev@example.com"),
        ("MUCHANIPO_CONTACT_EMAIL", "dev@example.com"),
        ("UNPAYWALL_EMAIL", "dev@example.com"),
        ("PLANNOTATOR_API_KEY", "p-key"),
        ("MUCHANIPO_COUNCIL_VISUALIZER", "ollama"),
        ("MUCHANIPO_COUNCIL_VISUALIZER_MODEL", "qwen3.6-a3b:latest"),
    ];
    let sanitized = sanitize_renderer_envs(env_map(&entries)).expect("allowlisted envs");
    assert_eq!(sanitized.len(), 30);
}

#[test]
fn rejects_execution_affecting_keys() {
    for key in [
        "PATH",
        "PYTHONPATH",
        "CLAUDE_BIN",
        "CODEX_BIN",
        "GEMINI_BIN",
        "OPENCODE_BIN",
        "GEMINI_ENDPOINT_TEMPLATE",
        "HTTPS_PROXY",
    ] {
        let error = sanitize_renderer_envs(env_map(&[(key, "evil")])).expect_err("unsafe key");
        assert!(error.contains("unsupported pipeline env"));
    }
}

#[test]
fn rejects_invalid_boolean_values() {
    for key in [
        "MUCHANIPO_USE_CLI",
        "OPENCODE_USE_CLI",
        "MUCHANIPO_OFFLINE",
        "MUCHANIPO_REQUIRE_LIVE",
    ] {
        let error = sanitize_renderer_envs(env_map(&[(key, "maybe")])).expect_err("invalid bool");
        assert!(error.contains(key));
    }
}

#[test]
fn rejects_non_http_mimo_base_urls() {
    for key in ["MIMO_BASE_URL", "XIAOMI_MIMO_BASE_URL"] {
        let error =
            sanitize_renderer_envs(env_map(&[(key, "file:///tmp/evil")])).expect_err("invalid URL");
        assert!(error.contains(key));
        assert!(error.contains("http(s) URL"));
    }
}

#[test]
fn allows_academic_sources_when_selection_is_supported() {
    let value = "openalex,crossref,semantic_scholar,core,arxiv,unpaywall";
    let sanitized = sanitize_renderer_envs(env_map(&[("MUCHANIPO_ACADEMIC_SOURCES", value)]))
        .expect("supported academic source selection");
    assert_eq!(
        sanitized,
        vec![("MUCHANIPO_ACADEMIC_SOURCES".to_string(), value.to_string())]
    );
}

#[test]
fn allows_semantic_scholar_credential() {
    let sanitized =
        sanitize_renderer_envs(env_map(&[("SEMANTIC_SCHOLAR_API_KEY", "test-credential")]))
            .expect("semantic scholar credential");
    assert_eq!(
        sanitized,
        vec![(
            "SEMANTIC_SCHOLAR_API_KEY".to_string(),
            "test-credential".to_string()
        )]
    );
}

#[test]
fn rejects_academic_sources_when_selection_is_invalid() {
    for selection in [
        "openalex,",
        ",openalex",
        "openalex,,arxiv",
        "openalex,openalex",
        "openalex,unknown",
        "https://untrusted.example",
    ] {
        let error = sanitize_renderer_envs(env_map(&[("MUCHANIPO_ACADEMIC_SOURCES", selection)]))
            .expect_err("invalid academic source selection");
        assert!(error.contains("MUCHANIPO_ACADEMIC_SOURCES"));
        assert!(error.contains("supported academic source selection"));
    }
}

#[test]
fn rejects_custom_academic_source_url_keys() {
    for key in [
        "MUCHANIPO_ACADEMIC_SOURCE_URL",
        "MUCHANIPO_OPENALEX_BASE_URL",
        "SEMANTIC_SCHOLAR_BASE_URL",
    ] {
        let error = sanitize_renderer_envs(env_map(&[(key, "https://untrusted.example")]))
            .expect_err("custom source URL");
        assert!(error.contains("unsupported pipeline env"));
    }
}

#[test]
fn skips_empty_entries() {
    let sanitized = sanitize_renderer_envs(env_map(&[
        ("ANTHROPIC_API_KEY", ""),
        ("", "value"),
        ("GEMINI_API_KEY", "g-key"),
    ]))
    .expect("empty entries ignored");
    assert_eq!(
        sanitized,
        vec![("GEMINI_API_KEY".to_string(), "g-key".to_string())]
    );
}
