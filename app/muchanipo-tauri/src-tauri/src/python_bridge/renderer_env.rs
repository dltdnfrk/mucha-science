use std::collections::HashMap;

pub(super) fn sanitize_renderer_envs(
    envs: HashMap<String, String>,
) -> Result<Vec<(String, String)>, String> {
    let mut sanitized = Vec::new();
    for (key, value) in envs {
        let key = key.trim().to_string();
        let value = value.trim().to_string();
        if key.is_empty() || value.is_empty() {
            continue;
        }
        if !is_allowed_renderer_env(&key) {
            return Err(format!("unsupported pipeline env from renderer: {key}"));
        }
        if is_boolean_renderer_env(&key) && !is_boolean_env_value(&value) {
            return Err(format!("{key} must be a boolean-like value"));
        }
        if is_url_renderer_env(&key) && !is_http_url_env_value(&value) {
            return Err(format!("{key} must be an http(s) URL"));
        }
        if key == "MUCHANIPO_ACADEMIC_SOURCES" && !is_academic_source_selection(&value) {
            return Err(format!(
                "{key} must be a supported academic source selection"
            ));
        }
        sanitized.push((key, value));
    }
    Ok(sanitized)
}

fn is_allowed_renderer_env(key: &str) -> bool {
    matches!(
        key,
        "MUCHANIPO_USE_CLI"
            | "OPENCODE_USE_CLI"
            | "MUCHANIPO_OFFLINE"
            | "MUCHANIPO_SOURCE_RESEARCH"
            | "MUCHANIPO_ONLINE"
            | "MUCHANIPO_REQUIRE_LIVE"
            | "MUCHANIPO_VERIFICATION_ROUTING"
            | "MUCHANIPO_API_ROUTING"
            | "MUCHANIPO_MODEL_ROUTING"
            | "MUCHANIPO_PROVIDER_CHAIN"
            | "MUCHANIPO_OPENCODE_MODEL"
            | "MUCHANIPO_INTERVIEW_COUNSELLING"
            | "MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK"
            | "MUCHANIPO_COUNCIL_CHAIRMAN_TIMEOUT_FALLBACK"
            | "MUCHANIPO_PREFER_CLI"
            | "MUCHANIPO_ACADEMIC_SOURCES"
            | "ANTHROPIC_API_KEY"
            | "GEMINI_API_KEY"
            | "KIMI_API_KEY"
            | "OPENAI_API_KEY"
            | "SEMANTIC_SCHOLAR_API_KEY"
            | "OPENCODE_API_KEY"
            | "OPENCODE_GO_API_KEY"
            | "XIAOMI_MIMO_API_KEY"
            | "MIMO_API_KEY"
            | "MIMO_BASE_URL"
            | "XIAOMI_MIMO_BASE_URL"
            | "MIMO_MODEL"
            | "MUCHANIPO_MIMO_MODEL"
            | "OPENALEX_EMAIL"
            | "MUCHANIPO_CONTACT_EMAIL"
            | "UNPAYWALL_EMAIL"
            | "PLANNOTATOR_API_KEY"
            | "MUCHANIPO_VAULT_ROOT"
            | "MUCHANIPO_COUNCIL_VISUALIZER"
            | "MUCHANIPO_COUNCIL_VISUALIZER_MODEL"
    )
}

fn is_boolean_renderer_env(key: &str) -> bool {
    matches!(
        key,
        "MUCHANIPO_USE_CLI"
            | "OPENCODE_USE_CLI"
            | "MUCHANIPO_OFFLINE"
            | "MUCHANIPO_ONLINE"
            | "MUCHANIPO_REQUIRE_LIVE"
            | "MUCHANIPO_SOURCE_RESEARCH"
            | "MUCHANIPO_INTERVIEW_COUNSELLING"
            | "MUCHANIPO_CHAIRMAN_TIMEOUT_FALLBACK"
            | "MUCHANIPO_COUNCIL_CHAIRMAN_TIMEOUT_FALLBACK"
            | "MUCHANIPO_PREFER_CLI"
    )
}

fn is_boolean_env_value(value: &str) -> bool {
    matches!(value, "1" | "0" | "true" | "false" | "yes" | "no")
}

fn is_url_renderer_env(key: &str) -> bool {
    matches!(key, "MIMO_BASE_URL" | "XIAOMI_MIMO_BASE_URL")
}

fn is_http_url_env_value(value: &str) -> bool {
    let lower = value.to_ascii_lowercase();
    (lower.starts_with("https://") || lower.starts_with("http://"))
        && !value.contains('\n')
        && !value.contains('\r')
}

fn is_academic_source_selection(value: &str) -> bool {
    let mut selected_sources = 0_u8;
    for source in value.split(',') {
        let source_bit = match source {
            "openalex" => 1,
            "crossref" => 2,
            "semantic_scholar" => 4,
            "core" => 8,
            "arxiv" => 16,
            "unpaywall" => 32,
            _ => return false,
        };
        if selected_sources & source_bit != 0 {
            return false;
        }
        selected_sources |= source_bit;
    }
    selected_sources != 0
}

#[cfg(test)]
#[path = "renderer_env_tests.rs"]
mod tests;
