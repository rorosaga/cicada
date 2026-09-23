"""The remote connector (G135): AI apps outside this Mac reach Cicada's MCP
tools through a separate, token-gated listener. Nothing here is imported by the
backend until "From anywhere" is on; the `mcp` SDK is imported only by
`api/remote/app.py` (R-R21)."""
