# Releasing Apsara Agentic

Two artifacts ship together and **must be released in this order** (the npm
package installs the PyPI package, so PyPI has to exist first):

1. `apsara-agentic` → PyPI (the Python CLI, source of truth)
2. `apsara-cli` → npm (the thin launcher in `../apsara-cli-npm`)

Keep the version in `pyproject.toml` and `../apsara-cli-npm/package.json` in sync.

## 0. Pre-flight

```bash
cd Apsara-Agentic-Cli
python -m pip install -e ".[dev,release]"
python -m pytest            # all tests green
apsara doctor               # environment sane
```

## 1. Build & validate the Python package

```bash
rm -rf dist build
python -m build             # builds sdist + wheel into dist/
twine check dist/*          # validates metadata + README render
```

Sanity-check that the wheel contains only `apsara_cli/**` and the right entry
point (`apsara = apsara_cli.cli:main`).

## 2. (Recommended) Smoke-test on TestPyPI first

```bash
twine upload --repository testpypi dist/*
pipx run --spec "apsara-agentic==<version>" --index-url https://test.pypi.org/simple/ apsara --help
```

## 3. Publish to PyPI

Requires a PyPI account with an API token (set `TWINE_USERNAME=__token__` and
`TWINE_PASSWORD=<token>`, or use `~/.pypirc`).

```bash
twine upload dist/*
```

## 4. Tag the release

```bash
git tag -a v<version> -m "Apsara Agentic v<version>"
git push origin v<version>
```

## 5. Publish the npm launcher

Only after the PyPI package is live (the npm postinstall runs
`pip install apsara-agentic==<version>`):

```bash
cd ../apsara-cli-npm
npm pack --dry-run          # confirm only bin/, scripts/, README.md, package.json ship
npm publish --access public
```

## Verify the published chain

```bash
pipx install apsara-agentic && apsara --help     # PyPI path
npm install -g apsara-cli && apsara --help        # npm path (installs from PyPI)
```

## Notes

- `dist/` and `build/` are gitignored; never commit build artifacts.
- To test the npm wrapper against a local/unpublished CLI, set `APSARA_PY_SPEC`
  (see `../apsara-cli-npm/README.md`).
