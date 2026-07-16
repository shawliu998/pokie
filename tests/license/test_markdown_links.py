from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[2]
MARKDOWN_FILES = (
    ROOT / "README.md",
    ROOT / "THIRD_PARTY_NOTICES.md",
    *sorted((ROOT / "docs").rglob("*.md")),
)
INLINE_LINK = re.compile(r"!?\[[^\]]+\]\((?P<target><[^>]+>|[^)\s]+)(?:\s+['\"][^'\"]+['\"])?\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(?P<target><[^>]+>|\S+)", re.MULTILINE)


def _local_target(markdown: Path, raw_target: str) -> Path | None:
    target = raw_target.strip("<>")
    if target.startswith(("#", "http://", "https://", "mailto:", "tel:")):
        return None
    path_text = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if not path_text:
        return None
    return (markdown.parent / path_text).resolve()


def test_all_repository_markdown_local_links_resolve() -> None:
    missing: list[str] = []
    assert MARKDOWN_FILES, "Markdown link gate must inspect repository documentation"
    for markdown in MARKDOWN_FILES:
        assert markdown.is_file(), f"required Markdown document is missing: {markdown}"
        text = markdown.read_text(encoding="utf-8")
        matches = (*INLINE_LINK.finditer(text), *REFERENCE_LINK.finditer(text))
        for match in matches:
            target = _local_target(markdown, match.group("target"))
            if target is not None and not target.exists():
                missing.append(f"{markdown.relative_to(ROOT)} -> {match.group('target')}")

    assert not missing, "broken local Markdown links:\n" + "\n".join(sorted(missing))
