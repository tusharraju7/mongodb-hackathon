# MongoDB MCP setup for Codex on Windows

## Server registration

Install Node.js and use the MongoDB MCP server from the official npm package.
The configuration prepared for this project uses a direct Node launcher to avoid
Windows command-wrapper issues. The package range matches the MongoDB plugin:
`mongodb-mcp-server@<4`.

The server is registered under `mongodb` in the local Codex user configuration:
`%USERPROFILE%\.codex\config.toml`.

The server package startup dry run has passed. Database authentication must be
configured separately; this startup check does not establish a database connection.

## Connect your cluster

1. In MongoDB Atlas, obtain a connection URI for your cluster using a database
   user and its current password. Reset any password that has been exposed.
2. Open `%USERPROFILE%\.codex\config.toml` locally.
3. Under the existing `[mcp_servers.mongodb.env]` section, add the connection URI:

   ```toml
   MDB_MCP_CONNECTION_STRING = "<paste your current MongoDB connection URI here>"
   ```

   Keep `MDB_MCP_READ_ONLY = "true"` for database inspection. Do not duplicate the
   section. Percent-encode reserved characters in the URI username or password.
4. In Atlas Network Access, allow your computer's current IP address.
5. Fully quit and reopen Codex to load the connection settings.
6. Ask Codex to list the databases and collections in your cluster. A successful
   response verifies database access; a startup check alone does not.

## Verification and troubleshooting

- `codex mcp get mongodb` verifies that Codex has registered the server.
- Authentication errors: check the database username and password, password
  encoding, and the database user's roles.
- Connection timeouts: confirm the cluster is available and your current IP is
  permitted in Atlas Network Access.
- Missing tools: fully restart Codex after changing the MCP configuration.

Store credentials only in the local user configuration. Do not commit that file,
connection URIs, environment files, or private database exports to this repository.

## References

- https://www.mongodb.com/docs/mcp-server/local-mcp/configuration/options/
- https://www.mongodb.com/docs/mcp-server/local-mcp/security-best-practices/
