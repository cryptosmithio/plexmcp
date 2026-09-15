# Zed IDE extension for plex-mcp

A [Zed](https://zed.dev/) context-server extension that lets Zed discover and
launch `plex-mcp` the same way Claude Desktop does via stdio MCP. This is a
separate, secondary integration — the primary product is the Tauri desktop
app in `../native/` and the webapp in `../webapp/`.

This used to live at the repo root (`Cargo.toml`, `build.ps1`, `src/lib.rs`),
which collided with `native/`'s own `Cargo.toml`/`build.ps1` and was the
direct cause of `just build-native` silently building this extension instead
of the Tauri app (2026-09-11). Moved here to remove the collision.

## Build

```powershell
.\build.ps1
```

Then in Zed: `Extensions: Install Dev Extension` and select this directory.

## Known limitation

`context_server_command` in `src/lib.rs` passes `--project .` to `uv run`,
assuming Zed launches the command with the current working directory set to
this plex-mcp checkout. This has not been verified against Zed's actual
context-server execution semantics (does Zed run it with cwd = the
extension's own directory, or the user's currently-open project?) — if this
extension is installed and doesn't connect, that assumption is the first
place to check.
