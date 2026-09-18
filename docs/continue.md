# Continue

<p align="center">
  <img src="../img/continue.jpg" alt="Continue artwork for the Continue MCP guide." width="960">  <!-- markdownlint-disable-line MD013 -->
</p>

> **MCP tools only work in Continue's Agent Mode.** Switch the mode selector in
> the chat sidebar from the default chat mode to **Agent** before expecting any
> `openproject` tool to be available.

Continue supports two configuration mechanisms: a top-level `mcpServers` array
inside `config.yaml` (YAML only), or a standalone file under
`.continue/mcpServers/`. The standalone file accepts either YAML (an array,
matching `config.yaml`'s own shape) or JSON — and the JSON variant uses a
**dict keyed by server name**, the same shape as every other client this
project documents, not an array. This guide uses that JSON file: no extra
dependency, and no shape translation needed from the rest of this project's
examples.

## Recommended setup

Create `.continue/mcpServers/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "openproject": {
      "command": "openproject-ce-mcp",
      "env": {
        "OPENPROJECT_BASE_URL": "https://op.example.com",
        "OPENPROJECT_API_TOKEN": "replace-with-your-token",
        "OPENPROJECT_READ_PROJECTS": "my-project,other-project",
        "OPENPROJECT_WRITE_PROJECTS": "my-project"
      }
    }
  }
}
```

Verified live against Continue's Agent Mode: a `mcpServers` array (matching
`config.yaml`'s own array-of-objects-with-`name` shape) is rejected here with
"doesn't match a supported MCP JSON configuration format" — this file's root
must be the dict-keyed form above, even though `config.yaml` itself uses an
array for the same server list. Continue also documents a `${{ secrets.NAME }}`
interpolation syntax for the `env` block; whether that resolves purely from a
local secret store or requires a Continue Hub cloud account isn't clear from
Continue's own documentation, so this example uses a plain literal value like
every other client's example in this project, rather than recommending an
unverified mechanism.

With a PyPI install the command is simply `openproject-ce-mcp`; source installs
can use the `.venv` binary path. The full set of `env` keys is the same as
every other client — see [`.mcp.json.example`](../.mcp.json.example) or
[Configuration](configuration.md).

## Automatic setup provided by this package

`openproject-ce-mcp configure` does not currently write a Continue
configuration. Continue's standalone file is a whole self-contained document
with no existing file to patch into, unlike this package's existing per-client
write logic (which patches a dict-keyed root inside an already-existing file).
Use the manual setup below; it's a single small file, not a multi-step
process.

## Manual setup

Use the JSON example under "Recommended setup" above. It's the primary,
verified path for this guide.

### YAML alternative

Continue also accepts YAML, either as a standalone file (an array, with extra
required top-level metadata) or merged into your existing global `config.yaml`
(also an array). Both are equally valid per Continue's own documentation; this
project doesn't automatically validate or generate either, so treat them as
manual, do-it-yourself options. Note the array shape here is specific to
YAML — the JSON standalone file above uses the dict shape instead:

**Standalone file** (`.continue/mcpServers/openproject.yaml`) — needs its own
`name`/`version`/`schema` header, separate from the array entry's `name`:

```yaml
name: OpenProject MCP
version: 1.0.0
schema: v1
mcpServers:
  - name: openproject
    command: openproject-ce-mcp
    env:
      OPENPROJECT_BASE_URL: https://op.example.com
      OPENPROJECT_API_TOKEN: replace-with-your-token
      OPENPROJECT_READ_PROJECTS: my-project,other-project
      OPENPROJECT_WRITE_PROJECTS: my-project
```

**Global `config.yaml`** — if you already use `config.yaml` for other MCP
servers, append this object to its existing `mcpServers:` array by hand (this
project provides no tooling to merge into that array):

```yaml
mcpServers:
  - name: openproject
    command: openproject-ce-mcp
    env:
      OPENPROJECT_BASE_URL: https://op.example.com
      OPENPROJECT_API_TOKEN: replace-with-your-token
      OPENPROJECT_READ_PROJECTS: "*"
      OPENPROJECT_WRITE_PROJECTS: ""
```

## Protect credentials

```bash
chmod 600 .continue/mcpServers/mcp.json
```

Add `.continue/` to your project's `.gitignore` so the file, any YAML
alternative you create alongside it, and their timestamped backups are never
committed.

## Reload and verify

Continue's own documentation states that config changes are picked up
automatically on save, with no IDE or extension restart needed. Whether the
underlying `openproject-ce-mcp` server process itself restarts on a mere file
save, or only the config is re-read while an already-running process keeps its
old environment, isn't addressed by Continue's documentation — after any
credential or URL change, don't rely on hot-reload alone:

- Switch to **Agent Mode** in the chat sidebar (required — MCP tools are not
  available in the default chat mode).
- Your selected chat model must support tool calling. Not every locally-hosted
  model does — a model that returns a "does not support tools" error is a
  model-capability limitation, not an `openproject` configuration problem;
  switch models rather than debugging the MCP config further.
- Ask it to call `list_projects` (or `get_current_user`). A successful reply
  with real data confirms the base URL and token work with the current
  process, not just the current file.
- If nothing appears, start a new chat, or reload the IDE window, to force a
  fresh process pick-up.

## User-wide setup (alternative)

Use the global `config.yaml` path instead of a project-scoped file to share one
instance across every project:

- **macOS/Linux:** `~/.continue/config.yaml`
- **Windows:** `%USERPROFILE%\.continue\config.yaml`

See the YAML alternative example above for its exact shape. Project-scoped
setup is preferred for per-project permissions; for credentials specifically,
neither path is meaningfully safer than the other here, since this guide's
recommended example uses a plain literal token either way.

## Notes

- **MCP tools only work in Continue's Agent Mode** — repeated here since it's
  the most common reason a configured server appears to do nothing.
- `config.yaml` and a standalone YAML file both use an array of server
  objects, each with its own `name` — but the standalone **JSON** file
  (`mcp.json`) uses a dict keyed by server name instead, the same shape as
  every other client this project documents. Don't copy the YAML array shape
  into `mcp.json`; Continue rejects it.
- A standalone YAML file under `.continue/mcpServers/` needs its own top-level
  `name`/`version`/`schema` fields; the JSON variant (`mcp.json`) does not.
- `OPENPROJECT_READ_PROJECTS` accepts comma-separated identifiers, names, or
  glob patterns: `project-one,team-*`. Use `*` for all visible projects.
- `OPENPROJECT_WRITE_PROJECTS` is the real write gate — the 6 core
  write-category flags (like `OPENPROJECT_ENABLE_WORK_PACKAGE_WRITE`) are on by
  default and do nothing until a project is listed here; set one to `false` to
  exclude that category instead.

## See also

- [Documentation hub](README.md) — full documentation index
- [Clients](clients.md) — global vs. project-scoped, and every client's file
  layout
- [Configuration](configuration.md) — the full environment variable reference
