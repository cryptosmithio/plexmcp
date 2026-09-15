use zed_extension_api as zed;

struct PlexMcpExtension;

impl PlexMcpExtension {
    fn new() -> Self {
        Self
    }
}

impl zed::Extension for PlexMcpExtension {
    fn new() -> Self {
        Self::new()
    }

    fn context_server_command(
        &mut self,
        _id: &zed::ContextServerId,
        _project: &zed::Project,
    ) -> zed::Result<zed::Command> {
        // NOTE: "." assumes Zed launches this command with cwd = the plex-mcp
        // repo itself (i.e. this extension is only useful when plex-mcp is the
        // open project) rather than resolving to it from an arbitrary project.
        // Not verified against real Zed context-server semantics — flagging
        // rather than guessing further. The concrete, verified fix here is the
        // CLI flag: plex_mcp's argparse has --stdio/--http/--sse, never --mcp.
        Ok(zed::Command {
            command: "uv".to_string(),
            args: vec![
                "run".to_string(),
                "--project".to_string(),
                ".".to_string(),
                "plex-mcp".to_string(),
                "--stdio".to_string(),
            ],
            env: Default::default(),
        })
    }
}

zed::register_extension!(PlexMcpExtension);
