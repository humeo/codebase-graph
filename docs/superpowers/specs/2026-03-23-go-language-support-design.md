# Codebase Graph Go Language Support Design

## Goal

Add first-pass Go support to `codebase-graph` so the indexer can parse Go source files, persist Go symbols and relationships, and resolve repository-local package imports in multi-module repositories.

The first pass is intentionally MVP-scoped:

- parse Go with tree-sitter
- extract core symbols: `package`, `function`, `method`, `type`
- extract core relationships: `imports`, `calls`
- resolve imports across repository-local packages
- support repositories with multiple `go.mod` files
- prefer `go` toolchain metadata when available, but succeed without it

## Current State

- The indexer currently supports Python, JavaScript, and TypeScript through a suffix registry in [languages.py](/Users/koltenluca/code-github/codebase-graph/.worktrees/multi-language/src/codebase_graph/indexer/languages.py).
- The indexer engine in [engine.py](/Users/koltenluca/code-github/codebase-graph/.worktrees/multi-language/src/codebase_graph/indexer/engine.py) is language-agnostic after it obtains a `Language` and extractor instance.
- Extractors currently return `symbols` and `edges` from a single file AST via the protocol in [base.py](/Users/koltenluca/code-github/codebase-graph/.worktrees/multi-language/src/codebase_graph/indexer/extractors/base.py).
- Edge resolution in [db.py](/Users/koltenluca/code-github/codebase-graph/.worktrees/multi-language/src/codebase_graph/storage/db.py) currently resolves by `target_name` only, and only when the target symbol name is globally unique.
- The SQLite schema already has a `qualified_name` column and index in [schema.py](/Users/koltenluca/code-github/codebase-graph/.worktrees/multi-language/src/codebase_graph/storage/schema.py), so the first Go version does not need a schema change.

## Chosen Approach

Use tree-sitter for all Go file parsing, then add a thin repository-level Go project context to supply module and package identity that is not present in the single-file AST.

This is preferred over a Go-only hardcoded implementation because the repository-level layer is the minimum reusable abstraction needed for later Rust and Zig support. It is also preferred over a schema redesign because the current schema can already represent stable package and symbol identities through `qualified_name`.

## Scope

### In Scope

- register `.go` files as a supported language
- add tree-sitter-based Go symbol extraction
- add repository-level Go module and package resolution
- create one synthetic package symbol per package
- resolve repository-local import edges to package symbols
- resolve simple imported selector calls such as `alias.Func()` when the import alias maps to a repository-local package
- support multi-module repositories by using the nearest ancestor `go.mod`
- use `go list` or similar toolchain metadata when available, with static fallback

### Out of Scope

- full Go type inference
- resolving method calls by receiver type
- deep handling of `.` imports
- full build tag awareness
- modeling external modules, standard library symbols, or module cache contents as first-class graph nodes
- schema changes for language-specific metadata
- Rust or Zig implementation work

## Design

## Architecture

The Go implementation will add one new repository-level component and one new extractor:

- `src/codebase_graph/indexer/go/project.py`
  - builds `GoProjectContext` for a repository root
  - discovers all `go.mod` files
  - parses module paths from `go.mod`
  - maps each Go file to its nearest enclosing module root
  - computes each directory package's full import path
  - picks a stable owner file for each package so the package symbol is inserted once
  - optionally consults the local `go` toolchain for validation or enrichment
- `src/codebase_graph/indexer/extractors/go.py`
  - uses tree-sitter Go ASTs
  - extracts file-local symbol and edge data
  - uses the provided Go project context to produce stable `qualified_name` values and imported-selector call targets

The existing engine remains the central orchestration point:

- `index_directory()` builds a shared `GoProjectContext` once per indexing run
- `index_file()` passes file-specific context into the Go extractor
- `index_file()` inserts the synthetic package symbol exactly once for the package owner file

The existing schema and query layer remain in place. The main persistence change is in resolution behavior, not storage shape.

## Extractor Interface

The extractor protocol should accept an optional context parameter:

```python
def extract(
    self,
    tree: Tree,
    source: bytes,
    file_path: str,
    context: object | None = None,
) -> tuple[list[SymbolInfo], list[EdgeInfo]]:
```

Design intent:

- Python, JavaScript, and TypeScript extractors ignore the new parameter
- Go uses it for module path, package path, package owner, and import alias lookup
- the protocol stays small and does not force non-Go extractors to understand project-level semantics

## Go Project Context

`GoProjectContext` should provide enough information for deterministic repository-local resolution without becoming a second parser.

Required responsibilities:

- discover every `go.mod` under the indexed root
- parse `module <path>` from each `go.mod`
- for each `.go` file, determine the nearest ancestor module root
- compute package import path as `module_path + relative_directory_from_module_root`
- group files by package import path
- choose a stable owner file per package using:
  - the lexicographically smallest non-test file path when one exists
  - otherwise the lexicographically smallest file path in the package, including `*_test.go`
- expose package metadata for a file:
  - module root
  - module path
  - package name
  - package import path
  - whether the file is the package owner

Optional enhancement:

- if the local `go` command is available, use it to validate static module or package metadata and fill gaps only when static discovery cannot determine a package identity
- if that command fails, log the failure at debug level and continue with static results

## Symbol Model

### Package Symbol

Each Go package gets one synthetic symbol:

- `kind = "package"`
- `name = <package_name>`
- `qualified_name = <full_import_path>`
- inserted only for the package owner file

This symbol is the target for repository-local import edges.

### Type Symbol

Go `struct`, `interface`, and type alias declarations are all indexed as:

- `kind = "type"`

This keeps the first pass aligned with the current query model and avoids premature type taxonomy.

### Function and Method Symbols

Functions:

- `name = "Parse"`
- `qualified_name = "<package_import_path>.Parse"`
- `kind = "function"`

Methods:

- `name = "Run"`
- `qualified_name = "<package_import_path>.<Receiver>.Run"`
- `kind = "method"`

Receiver normalization should strip pointer syntax such as `*Service` to `Service`.

## Edge Model

### Import Edges

For repository-local Go imports, the extractor should emit:

- `relation = "imports"`
- `target_name = <full_import_path>`

Example:

```go
import alias "example.com/repo/internal/util"
```

produces:

- `imports` edge to `example.com/repo/internal/util`

This allows import resolution to match the synthetic package symbol by `qualified_name`.

External or standard library imports should still be stored as unresolved `imports` edges with their import path as `target_name`.

### Call Edges

The first pass supports three call categories:

1. Bare calls in the current package
2. Imported selector calls where the selector root is a known import alias
3. Simple calls that can safely fall back to name-based resolution

Rules:

- `Parse()` emits `target_name = "Parse"`
- `alias.Parse()` where `alias -> example.com/repo/internal/util` emits `target_name = "example.com/repo/internal/util.Parse"`
- `svc.Run()` emits `target_name = "Run"` because receiver type inference is out of scope
- chained or computed expressions may fall back to the terminal identifier or be skipped if no reliable target can be extracted

`.` imports remain partially supported in the MVP:

- preserve the `imports` edge
- do not attempt special call resolution

## Resolution Strategy

`resolve_edges()` should change from name-only resolution to two-stage resolution:

1. Try to resolve by `qualified_name` when `edges.target_name` matches exactly one symbol `qualified_name`
2. If that fails, fall back to the current unique `name` resolution

This preserves current behavior for Python, JavaScript, and TypeScript while enabling Go package and imported-selector resolution without changing the schema.

Expected results:

- `imports` edges can resolve to Go package symbols by full import path
- imported selector calls can resolve to uniquely named Go symbols by full qualified name
- unresolved calls still remain queryable through `target_name`

## Indexing Flow

The indexing flow for Go files becomes:

1. `index_directory()` scans the repository and builds `GoProjectContext`
2. `update()` must also build a `GoProjectContext` for the repository root before reindexing specific Go files, so hook-driven incremental indexing uses the same package resolution rules as full indexing
3. for each `.go` file, the engine retrieves file-specific package metadata
4. the file is parsed with tree-sitter Go
5. `GoExtractor.extract(..., context=...)` returns symbols and edges
6. the engine inserts the file record and module symbol as it does today
7. if the file is the package owner, the engine inserts the synthetic package symbol
8. the engine inserts file-local symbols and unresolved edges
9. `resolve_edges()` performs qualified-name-first resolution, then name fallback

## Monorepo and Multi-Module Rules

The first Go version must behave deterministically in repositories with multiple modules.

Rules:

- a Go file belongs to the nearest ancestor directory containing `go.mod`
- package import path is computed relative to that module root
- files outside any module may still be parsed for symbols, but repository-local import resolution is best-effort only
- package identity is based on full import path, not package name
- duplicate package names across modules are allowed because `qualified_name` is unique

If static analysis and toolchain metadata disagree:

- prefer static analysis for deterministic indexing
- only use toolchain metadata when static analysis is missing enough information to build a package identity, or when validating a computed identity
- otherwise keep the static result and continue indexing

## Error Handling

Go support must never cause the entire indexing run to fail for recoverable project-shape issues.

Required behavior:

- if a `.go` file fails to parse, skip or partially index that file and continue
- if a `go.mod` file cannot be parsed, ignore its module metadata and continue scanning
- if the `go` toolchain is absent or returns an error, log at debug level and continue with static metadata
- if a repository-local target cannot be resolved uniquely, preserve the unresolved edge rather than guessing

## Testing Plan

Add tests at three levels.

### Extractor Unit Tests

Add `tests/test_go_extractor.py` with fixtures covering:

- package clause extraction into package metadata
- top-level function extraction
- method extraction with receiver normalization
- type extraction
- import edge extraction
- bare call extraction
- alias selector call extraction

### Project Context Unit Tests

Add tests for `GoProjectContext` using multi-module fixtures:

- nearest `go.mod` selection
- module path parsing
- package import path computation
- owner file selection stability
- toolchain fallback behavior

### Engine Integration Tests

Add `tests/test_go_engine.py` covering:

- `.go` suffix support
- indexing Go files into the existing schema
- synthetic package symbol insertion
- synthetic package symbol insertion for test-only packages
- repository-local import edge resolution to package symbols
- imported selector call resolution when the target symbol is unique
- incremental indexing behavior for Go files
- deleted Go file cleanup

Add a CLI-level acceptance test for `cg update` in a multi-package or multi-module Go fixture so the hook-driven incremental path is explicitly covered.

## Implementation Order

Implement in this order:

1. add Go tree-sitter dependency and register `.go`
2. add Go fixtures and extractor unit tests
3. implement `GoExtractor`
4. implement `GoProjectContext`
5. update engine to build and pass Go context
6. update edge resolution to prefer `qualified_name`
7. add integration tests for multi-module import resolution

This order keeps the work incremental and makes regressions easier to isolate.

## Risks

- package owner selection could produce unstable package symbol placement if not deterministic
- selector call resolution can over-resolve if import aliases are not tracked carefully
- falling back from `qualified_name` to `name` must not change existing non-Go behavior
- Go project layouts with heavy build tags or generated code may produce partial graphs in the MVP

## Future Extensions

This design intentionally creates two reusable extension seams:

- file-level syntax extraction through tree-sitter
- repository-level package or module identity resolution

That structure can later support:

- Rust with `Cargo.toml` and workspace-aware crate resolution
- Zig with package or module path resolution
- richer Go semantics such as exported flags, interface embedding, or receiver-type-aware call resolution

## Out of Scope for the First Plan

- redesigning the query API
- storing language-specific metadata tables
- crate-level or module-level modeling for Rust
- Zig implementation details
