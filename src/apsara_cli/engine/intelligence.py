"""Fast, dependency-free repository map and cross-language symbol search."""

import re
from collections import Counter
from pathlib import Path

IGNORED = {".git", ".apsara", ".venv", "venv", "node_modules", "dist", "build", "__pycache__"}
LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust", ".java": "Java",
    ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C",
}
SYMBOL_PATTERNS = (
    re.compile(r"^\s*(?:async\s+)?(?:def|class)\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:export\s+)?(?:async\s+)?(?:function|class|interface|type|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"^\s*(?:pub\s+)?(?:fn|struct|enum|trait)\s+([A-Za-z_]\w*)"),
    re.compile(r"^\s*(?:func|type)\s+([A-Za-z_]\w*)"),
)


def source_files(workspace: Path):
    for path in workspace.rglob("*"):
        if path.is_file() and path.suffix.lower() in LANGUAGES and not any(p in IGNORED for p in path.parts):
            yield path


def repository_map(workspace: Path, max_files: int = 200) -> str:
    files = list(source_files(workspace))[:max_files]
    languages = Counter(LANGUAGES[p.suffix.lower()] for p in files)
    manifests = [name for name in ("pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "requirements.txt") if (workspace / name).exists()]
    lines = [f"Repository: {workspace.name}", f"Languages: {', '.join(f'{k} {v}' for k, v in languages.most_common()) or 'unknown'}"]
    if manifests:
        lines.append(f"Manifests: {', '.join(manifests)}")
    for path in files:
        relative = path.relative_to(workspace)
        symbols = []
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                for pattern in SYMBOL_PATTERNS:
                    match = pattern.match(line)
                    if match:
                        symbols.append(match.group(1))
                        break
        except OSError:
            pass
        suffix = f" — {', '.join(symbols[:8])}" if symbols else ""
        lines.append(f"- {relative}{suffix}")
    if len(files) == max_files:
        lines.append(f"… limited to {max_files} source files")
    return "\n".join(lines)


def find_symbol(workspace: Path, query: str, limit: int = 100) -> str:
    needle = query.lower()
    results = []
    for path in source_files(workspace):
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            for pattern in SYMBOL_PATTERNS:
                match = pattern.match(line)
                if match and needle in match.group(1).lower():
                    results.append(f"{path.relative_to(workspace)}:{number}: {match.group(1)}")
                    break
            if len(results) >= limit:
                return "\n".join(results)
    return "\n".join(results) if results else f"No symbols matching '{query}'."
