# Code intelligence architecture

## Goal

Apsara should understand definitions and diagnostics without requiring a
language server for every project or slowing down every edit. The internal API
therefore returns stable `Symbol`, `Reference`, and `Diagnostic` records while
the parser/checker behind those records can vary.

## Resolution tiers

1. Python uses the standard-library AST. It provides exact definition spans,
   syntax errors, and safe whole-symbol replacement with no extra install.
2. Other supported languages use `tree-sitter-language-pack` when users install
   `apsara-agentic[intelligence]`. Parsers are loaded on demand.
3. Without that extra, repository maps and symbol search retain a conservative
   regex fallback. A pattern match is never treated as precise enough for a
   whole-symbol replacement.

This keeps the default `pipx install apsara-agentic` small and functional while
making richer parsing an explicit choice.

## Agent tools

- `list_symbols(path)` returns definitions and their parser provider.
- `go_to_definition(name, path_hint)` prefers exact names and can narrow paths.
- `find_references(name, path)` returns source locations and labels definitions.
- `replace_symbol(path, symbol, replacement)` requires one exact parser span,
  shows the normal diff approval, and creates the normal rollback checkpoint.
- `code_diagnostics(path)` performs a quick, side-effect-free syntax check.
- `code_diagnostics(project=true)` explicitly invokes Pyright, TypeScript,
  Go, or Rust tooling when the matching manifest and executable exist.

## Edit feedback

Built-in writes, exact-text edits, line replacements, and symbol replacements
run only the cheap single-file parser after writing. The result is appended to
the tool response, so the model sees a syntax failure before it continues.
Project checks stay explicit because they can compile dependencies, execute Go
test initialization, or take minutes in a large repository.

## Safety and future LSP support

All paths still pass through the workspace boundary, semantic writes use the
same confirmation and checkpoint system as other mutations, and compiler
commands use argument arrays rather than a shell. An LSP adapter can later emit
the same record types, so adding type-aware references or rename does not
change the agent-facing tool contract.
