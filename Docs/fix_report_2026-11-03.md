# Sandbox + Agents + Chat Fix Report — 2026-11-03

Scope: review all code, fix items 1–5, smoke-test the app.
Changed: `app/services/modal_sandbox_service.py`, `app/services/modal_client.py`,
`app/models.py`, `app/blueprints/tasks/routes.py`.
Pre-existing (not mine, left untouched): `app/static/css/style.css` (container 1800px),
`app/templates/base.html` (favicon link).

## 1. Old local_file `./upload/[sandboxname]` — traces

- Grep over `app/**/*.py`: zero hits for `local_file`, `sandboxname` (one word),
  `./upload`. The old per-sandbox local dir is gone.
- What remains is legitimate and per-project on the *remote* side:
  `sandbox_name` (`proj-{team}-{project}-{id}`) in `projects/routes.py:64`,
  `sandbox_routes.py:88`, `modal_sandbox_service.py:48,166-180` — this is the Modal
  sandbox name, not a local dir.
- `local_path` / `local_tmp` / `copy_from_local` hits are the upload path:
  `sandbox_routes.py:315-327` saves the browser upload to `tempfile.gettempdir()`
  then `upload_file_to_sandbox(sandbox_id, local_tmp, remote_path)` then
  `os.remove(local_tmp)`. No persistent `./uploads/<sandbox>` dir is used by code;
  the only `uploads/` writer is `voice/routes.py:195-196` (`uploads/voice/*.wav`).
- `sb-mock-*` is a fallback *sandbox id string* (`sandbox_routes.py:305,395,432,509`,
  `tasks/routes.py:963,966`), guarded by the exec reject in
  `sandbox_routes.py:445` (`sb-mock-`/`sb-error-` refused). Not a local_file trace.
- Orphan on disk (not referenced by code): `uploads/sandbox/sb-mock-proj-core-factory-codefactory-api-1-1/test_upload.py`.
  Left in place; safe to delete manually.

## 2. Async/sync sandbox creation — dedup + cleanup

- The two async functions are layered, not duplicated, and both kept:
  `create_sandbox_with_tunnel_async` (generic builder) ←
  `create_project_sandbox_with_tunnel_async` (project entrypoint, computes
  `sandbox_name`, delegates at `:176`). Neither takes `local_files` (zero matches
  in `app/`) — no stale local-file logic to remove.
- Only sync caller path in use: `create_project_sandbox_with_tunnel` (used by
  `sandbox_routes.py:75`, `projects/routes.py:87`). No caller imports/awaits the
  `_async` variants directly.
- Cleanup done:
  - Added single `_run_sync()` helper in `modal_sandbox_service.py`; all 8 sync
    wrappers (`create_project`, `check_tunnel`, `terminate`, `upload`, `write_text`,
    `list_files`, `read_file`, `clone_repo`) now delegate to it (was 8× copy-pasted
    `asyncio.run`/`new_event_loop` blocks).
  - Fixed stale docstring (`await create_project_sandbox_with_tunnel(...)` → sync call).
  - `tasks/routes.py`: deleted dead `try/except` imports of nonexistent
    `exec_in_sandbox` / `run_dev_command_in_sandbox` (3 blocks); parent dirs are
    created inside `write_text_to_sandbox_async` via `mkdir -p`. Merged duplicate
    `_strip_file_marker_line` into module-level `_strip_file_marker`.

## 3+4. Super-agent sandbox file reading (why `read_files` was invented)

- Root cause: the model gets prose, not tools. `modal_client.py:147-156` sends
  `messages/max_tokens/temperature` with no function/tool schema, so the LLM can
  only *name* helpers. Prompt verb names were inconsistent (`read_text` vs
  `read_file_from_sandbox` vs "read existing files" in `models.py:271,330` and
  `modal_client.py:113`), and `sandbox_context` was static metadata (name/tunnel/git)
  with no live file listing and no `sandbox_id` handed to the model. The model
  filled the gap by hallucinating plural `read_files`. (No literal `read_files`
  exists in the repo — confirmed runtime behavior, not a code symbol.)
- Fix (super agent = single source; clones inherit via `Agent.create_clone`):
  - `models.py` `MASTER_AGENT_TEMPLATE`: new top block "MOST IMPORTANT SKILL -
    READ FROM SANDBOX FIRST" (read-before-write, `/workspace` is the only workplace,
    testing clones read the file under test first, `NEVER invent read_files`);
    principles #6–#8 canonicalized to `list_files_in_sandbox` /
    `read_file_from_sandbox` / `write_text_to_sandbox` / `upload_file_to_sandbox`.
  - Skills reordered: `sandbox` (99) + `filesystem` (97) first with
    read-first descriptions; removed duplicate trailing entries.
  - `modal_client.py`: system prompt uses the same canonical verbs + never-invent
    rule + read-request protocol; `run_agent_via_modal_endpoint` now accepts
    `sandbox_context` and injects it into the user message; `run_agent_factory`
    appends a best-effort live `list_files /workspace` snapshot (skipped for
    `sb-mock-*`, failures only logged) and passes context to the endpoint call.
  - Dead `sandbox_info in locals()` placeholder block removed.

## 5. Chat parser: `**Briefing:**` + green code divs

- `Briefing:` is a prompt-template prefix (`modal_client.py:131`,
  `agents/routes.py:79`), stored into `TaskMessage.content`. The timeline now
  strips one leading `**Briefing:**` / `Briefing:` in `view()` via new
  `_strip_briefing_prefix()` (both the rendered path and the plain fallback).
  Full prompt behind `+` is unchanged.
- Green was applied to *every* fenced block. Now green (`#0a0f0a`/`#10b981`/`#86efac`
  + Exec) is reserved for blocks with an explicit `/workspace/` path
  (`_detect_file_path_explicit`). Path-less snippets render neutral
  (`var(--bg2)`/`var(--bg3)`, "Code snippet" header) so Agent Information and
  prose code are never green. `Agent Information` accordion keeps its dark body;
  only genuine file panels inside it stay green.

## Tests (no maintained harness in repo)

- Repo has no `tests/` dir, no Makefile/CI gate. Per project convention no new
  framework was added; probes kept outside the deliverable: `/tmp/probe_parser.py`,
  `/tmp/probe_readskill.py`.
- `python -m py_compile` on all edited files: OK.
- `/tmp/probe_parser.py`: briefing strip (md + plain + passthrough), marker strip,
  neutral snippet (no `#86efac`), green file panel (`#10b981` + Exec +
  `/workspace/app.py`) — `PROBE_OK`.
- `/tmp/probe_readskill.py`: `_extract_requested_paths` finds `/workspace/...`,
  `_fulfill_sandbox_reads` returns `''` for mock/missing ids and a readable note
  (never raises) for real ids — `READSKILL_OK`.
- Boot smoke (`app.test_client`): `GET /auth/login` → 200, `GET /` → 302. Live
  Modal paths are guarded try/except (snapshot/read-through failures only logged).
- Grep after fix: `exec_in_sandbox` / `run_dev_command_in_sandbox` gone;
  `local_file`/`sandboxname`/`./upload` still zero; `asyncio.run` only inside
  `_run_sync`; remaining `read_files` hits are the new "never invent" guardrails.

## Update — super-agent READ skill is now real (not just prompt text)

- `modal_client.py`: `run_agent_via_modal_endpoint` exposes two real tools,
  `list_files_in_sandbox` + `read_file_from_sandbox`, with a 4-round tool loop —
  when you ask "read the file /workspace/X and tell me what's in there", the model
  calls the tool, the backend runs `read_file_from_sandbox_async` equivalent, and
  the content comes back into the reply (evidence logged under `## Sandbox Reads`).
  Works with `sandbox_id` of the project's sandbox; mock ids skip tools safely.
- Backend read-through `_fulfill_sandbox_reads()`: pre-reads requested
  `/workspace` paths and injects contents into `sandbox_context`, so even the
  local-mock path answers from real file contents. Never raises.
- `models.py` template documents the exact signatures incl. the
  `await read_file_from_sandbox_async(sandbox_id, remote_path)` form.

## Update 2 — agent still couldn't read (root-caused + fixed)

- Root cause found: `run_agent_factory` called `sandbox.time_to_expiry()`, which
  exists only on `Agent`, not `ProjectSandbox` — AttributeError wiped out the
  whole `sandbox_context` (`sandbox = None`), disabling both the read-through and
  the tool loop. That is exactly the `ProjectSandbox object has no attribute
  'time_to_expiry'` error in the agent output. Removed the call.
- Second gap: the request said "read the contact.html" (bare filename, no
  `/workspace/` path), which the old extractor ignored. Added
  `_extract_requested_names()` + new `find_file_in_sandbox[_async]()` service
  (`find /workspace -name <file>`) so bare names resolve to real paths before
  `read_file_from_sandbox` runs. Also exposed as a third model tool.
- Prompt hardened: NEVER write helper scripts (e.g. `_read_contact_helper.py`) to
  locate/print files — call the find/read tool instead.
- Verified: `READSKILL2_OK` (bare-name extraction, mock/missing guards),
  `PROBE_OK`, boot 200.

## Update 3 — delete + test actions (agent always created code)

- Why it always created code: read/write were the only tools, so every request
  (delete, test, check) got answered with a code block. Added two real tools:
- `delete_file_in_sandbox[_async](sandbox_id, remote_path)` — `rm -f` under
  `/workspace` only (other paths refused). Tool `delete_file_in_sandbox`.
- `exec_command_in_sandbox[_async](sandbox_id, command)` — run `ls`/`cat`/
  `pytest` etc. and report output (capped). Tool `exec_command_in_sandbox`.
- Prompt + super-agent template now carry MATCH-THE-ACTION rules: delete ->
  delete tool + confirm, test/check/run -> exec tool + report, read -> read tool
  only; new code blocks only when new/changed code was asked for.
- Verified: compile clean, `PROBE_OK`, `READSKILL2_OK`, boot 200.

## Update 4 — project page verify-then-show sandbox gating

- `projects/view` now checks DB first, then runs the tunnel check on any DB sandbox
  with a Modal id in an active-ish state. Tabs + `Started • alive` render only when
  this request's check establishes (`sandbox_live` flag, same info the task sidebar
  shows: name/type/ID/tunnel/alive badge).
- Check `established == false` on a previously-active sandbox → DB status corrected
  to `Finished`, tunnel fields cleared, `sandbox_unreachable` activity logged, page
  shows waiting + Recreate instead of tabs. Own-network failures (`could not
  connect`) never mutate the DB. `Creating`/`Scheduled` still-starting sandboxes are
  left alone unless Modal says not-found; verified checks promote them to `Started`.
- No sandbox in DB → same create form as a new project (`+ Add Sandbox`, basic/8000,5173).
- Verified via authenticated probes (scratch rows created + cleaned): no-DB →
  create form; failed check → `Finished`, tunnels cleared, `sandbox_unreachable`
  logged, recreate shown, tabs hidden; established check → tabs + alive + Active
  badge all render.
