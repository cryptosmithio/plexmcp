# Per-repo fleet start config for plex-mcp
# Edit ports/backend target here - start.ps1 is fleet-standard.
@{
    Name         = 'plex-mcp'
    BackendPort  = 10740
    FrontendPort = 10741
    HealthPath   = '/health'
    WebRoot      = 'webapp\frontend'
    Backend = @{
        Kind          = 'uvicorn-web-app'
        UvicornTarget = 'app.main:app'
        WorkDir       = 'webapp\backend'
        PythonPath    = 'webapp\backend;src'
        SyncExtras    = @('dev')
        SyncOnStart  = $true
        Env           = @{ WEB_PORT = '10740' }
    }
    Frontend = @{
        Kind           = 'next'
        PackageManager = 'npm'
        PortEnvVar     = 'PORT'
        ApiTargetEnv   = 'API_URL'
    }
}
