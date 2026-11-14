# Project instructions

## Git workflow

- After each completed task, review the working tree and staged changes, resolve any merge conflicts, and commit the task changes.
- Include relevant staged changes in the commit after reviewing them. Preserve unrelated work.
- Push completed commits to GitHub on the active task branch. Use `Chelsea-setup` for the current setup work.
- Never commit credentials, connection strings containing passwords, local environment files, or private database exports.
- Report the commit and push result, and identify any work blocked by missing input.

## MongoDB preferences

- Use `C:\Users\rulan\Desktop\MongoDB Hackathon` as the project folder.
- Keep MongoDB connection settings only in this project's ignored `.env` file.
- Do not create global Codex MongoDB configuration or extra MCP setup scaffolding.
- Use read-only operations when inspecting Cluster0.
