import asyncio
import inspect
import re

from forge.mcp_server import PUBLIC_TOOLS, mcp


def test_public_surface_is_exactly_five_tools():
    tools = asyncio.run(mcp.list_tools())
    assert {tool.name for tool in tools} == set(PUBLIC_TOOLS)


def test_forge_start_task_field_contract():
    """Every field described as part of the forge_start_task call in the
    operating prompt must exist as a real MCP function parameter."""
    actual_params = set(inspect.signature(mcp._tool_manager._tools["start_task"].fn).parameters.keys())
    described_fields = {"task_text", "repo_root", "expected_files",
                        "host_session_id", "replace_active", "scope_mode"}
    assert described_fields <= actual_params, f"described fields not all in actual: {described_fields - actual_params}"


def test_forge_start_task_no_classification_or_mutation_expected_args():
    """Classification and mutation_expected must NOT appear as tool-call
    arguments in the Forge Native Operating Protocol's forge_start_task section."""
    operating_doc = __import__("pathlib").Path("docs/Forge Native Operating.md").read_text()
    lifecycle_section = operating_doc.split("# Lifecycle\n", 1)[1].split("\n# ", 1)[0]
    assert "classification path" not in lifecycle_section
    assert "mutation_expected" not in lifecycle_section


def test_classification_guidance_remains_in_prompt():
    """Classification paths remain as mental workflow guidance in the prompt."""
    operating_doc = __import__("pathlib").Path("docs/Forge Native Operating.md").read_text()
    assert "PREFLIGHT_INSPECTION" in operating_doc
    assert "REVIEW_ONLY" in operating_doc
    assert "HEAVY_REVIEW" in operating_doc
    assert "FAST_PATH" in operating_doc
    assert "CONTROLLED_IMPLEMENTATION" in operating_doc

