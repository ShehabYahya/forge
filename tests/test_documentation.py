from pathlib import Path
import re
import zipfile

from forge.mcp_server import PUBLIC_TOOLS


def test_documented_public_tools_match_contract():
    contract = Path("docs/FORGE_ALPHA_CONTRACT.md").read_text()
    documented = set(re.findall(r"`(forge_[a-z_]+)`", contract.split("Every response", 1)[0]))
    removed_name = "forge_" + "prepare_" + "context"
    documented.discard(removed_name)
    assert documented == set(PUBLIC_TOOLS)


def test_relative_markdown_links_resolve():
    for markdown in [Path("README.md"), Path("INSTALL.md"), *Path("docs").glob("*.md")]:
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", markdown.read_text()):
            if "://" not in target and not target.startswith("#"):
                assert (markdown.parent / target.split("#", 1)[0]).resolve().exists(), (markdown, target)


def test_built_wheel_contains_distribution_assets():
    wheels = list(Path("dist").glob("*.whl"))
    if not wheels:
        return
    with zipfile.ZipFile(wheels[-1]) as archive:
        names = set(archive.namelist())
    assert "forge/skills/anvil/SKILL.md" in names
    assert "forge/skills/review-memory/SKILL.md" in names
    assert "forge/plugin/opencode/src/index.ts" in names
    assert "forge/plugin/opencode/src/maintenance.ts" in names
    assert "forge/plugin/opencode/src/transport.ts" in names
    assert "forge/plugin/opencode/dist/index.js" in names
    assert "forge/plugin/opencode/commands/review-memory.md" in names
