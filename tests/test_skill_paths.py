import re


def test_skill_docs_only_reference_existing_python_scripts(repo_root):
    for skill_file in sorted((repo_root / "skills").glob("*.md")):
        skill_text = skill_file.read_text(encoding="utf-8")
        script_paths = set(re.findall(r"python3?\s+(src/[^\s`\"']+\.py)", skill_text))
        missing = [path for path in sorted(script_paths) if not (repo_root / path).exists()]
        assert missing == [], f"{skill_file.name}: missing {missing}"