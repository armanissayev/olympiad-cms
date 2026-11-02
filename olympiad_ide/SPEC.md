# OLYMPIAD IDE
## Software Requirements Specification (SRS)
**Version:** 1.0

**Status:** Approved for development

**Project type:** Web-based competitive programming IDE

**Primary audience:** Competitive programming students and olympiad participants

---

# 1. Project Overview

## 1.1 Objective

Develop a production-oriented, web-based Integrated Development Environment (IDE) specifically designed for competitive programming competitions.

The IDE must closely resemble Visual Studio Code in appearance and interaction patterns while introducing several modifications for competitive programming.

The system must support:

1. VS Code-inspired code editor using Monaco.
2. Multi-file and multi-folder workspace management.
3. Multiple editor tabs.
4. Customizable themes, settings and keyboard shortcuts.
5. Remote compilation and execution of C++, Python and Java programs.
6. Integrated terminal-style output panel.
7. Multiple custom test cases.
8. Automatic saving and recovery after page reloads.
9. Detailed keyboard and text-editing telemetry.
10. Offline event buffering and reliable synchronization.
11. Playback of the complete recorded editing history.
12. Split Editor with two simultaneously visible files.
13. Interactive debugging with breakpoints and step-by-step execution.

**Important:** All functionality above is mandatory for the completed v1.0 release. It may be implemented across several development phases.

The initial version will be independent of CMS, but its architecture must accommodate future integration with Contest Management System (CMS).

The system must not rely on fake or simulated backend behavior in the final release.

---

# 2. General Engineering Principles

Follow these principles throughout development:

- Prefer maintainable, modular code over unnecessarily complex abstractions.
- Implement functional features, not just visual representations.
- Preserve user work under common failure conditions.
- Keep the IDE responsive during all background operations.
- Separate editor logic, telemetry, persistence, execution and debugging.
- Never execute untrusted code directly inside the API server.
- Treat browser-generated telemetry as observable information, not tamper-proof evidence.
- Use strict TypeScript types and validated backend schemas.
- Ensure frontend and backend have automated tests.
- Design interfaces for future CMS integration without implementing CMS itself.

Avoid monolithic components, direct database access from frontend code, unnecessary microservices and premature ML functionality.

---

# 3. Technology Stack

## 3.1 Frontend

Use:

- React
- TypeScript with strict mode
- Vite
- Monaco Editor
- Tailwind CSS
- Zustand for state management
- TanStack Query for server state where appropriate
- IndexedDB through Dexie
- xterm.js for terminal rendering
- Lucide Icons
- A suitable resizable panel library

Additional libraries are permitted if they offer clear benefits.

## 3.2 Backend

Use:

- Python 3
- FastAPI
- Pydantic
- SQLAlchemy
- Alembic
- PostgreSQL
- WebSocket support
- A persistent execution-job queue

The job queue may initially be implemented using PostgreSQL, provided jobs can be claimed safely by concurrent workers and recovered after failures.

## 3.3 Execution Workers

Implement a separate worker service.

It must support:

- GCC for C++17 and C++20
- CPython 3
- OpenJDK 17
- Sandboxed compilation and execution
- Execution cancellation
- Resource limits
- Isolation between users

Evaluate isolate or another suitable Linux sandbox. The chosen technology must provide practical protection against untrusted programs.

Ordinary Docker containers without appropriate hardening must not be treated as a sufficient security boundary.

## 3.4 Deployment

Provide Docker Compose for local development.

Separate the following services logically:

- Frontend
- API backend
- PostgreSQL
- Execution worker
- Debug worker

Execution and debugging workers may share infrastructure if isolation, capacity limits and scheduling remain separate.

---

# 4. User Interface Specification

## 4.1 Design Direction

The interface must be visually inspired by VS Code Dark Modern.

Use:

- Dark charcoal backgrounds
- Slightly lighter secondary panels
- Subtle borders and separators
- Compact toolbars
- Monospace code typography
- Familiar file icons
- Minimal animations
- Professional, restrained visual design

Avoid oversized buttons, excessive rounded corners, colorful gradients and unnecessary decorative components.

The primary development experience targets desktop browsers.

Suggested minimum supported viewport: 1024 × 768.

The layout must remain usable at smaller sizes, although full mobile editing is not a v1.0 requirement.

## 4.2 Main Layout

The application must have the following structure:

    ┌───────────────────────────────────────────────────────┐
    │ Top Toolbar                                           │
    ├────┬────────────┬─────────────────────────────────────┤
    │    │            │ Editor Tabs                         │
    │ A  │ Explorer   ├──────────────────┬──────────────────┤
    │ c  │            │                  │                  │
    │ t  │ Files      │ Monaco Editor 1  │ Monaco Editor 2  │
    │ i  │ Folders    │                  │                  │
    │ v  │            │                  │                  │
    │ i  │            ├──────────────────┴──────────────────┤
    │ t  │            │ Terminal / Problems / Test Cases    │
    │ y  │            │                                     │
    ├────┴────────────┴─────────────────────────────────────┤
    │ Status Bar                                            │
    └───────────────────────────────────────────────────────┘

The second editor pane is visible only when Split Editor is enabled.

Required layout capabilities:

- Resize Explorer width.
- Resize terminal height.
- Hide and show Explorer.
- Hide and show terminal.
- Enter a distraction-free editor mode.
- Restore panel sizes after reload.
- Support keyboard and mouse navigation.

## 4.3 Top Toolbar

Include:

- Olympiad IDE logo and application name.
- Current workspace name.
- Current programming language.
- Run button.
- Debug button.
- Stop button.
- Save/synchronization indicator.
- Settings button.

Suggested primary shortcuts:

- Ctrl/Cmd + Enter: Run
- F5: Start debugging
- Shift + F5: Stop debugging
- F10: Step Over
- F11: Step Into
- Shift + F11: Step Out
- Ctrl/Cmd + S: Save checkpoint
- Ctrl/Cmd + P: Quick Open
- Ctrl/Cmd + F: Find
- Ctrl/Cmd + H: Replace

Use platform-appropriate keyboard conventions.

All commands must be available through the UI, not only keyboard shortcuts.

## 4.4 Activity Bar

Include:

- Explorer
- Search
- Run and Debug
- History
- Settings

Icons must have tooltips and active-state styling.

Do not add placeholder navigation elements without functioning destinations.

## 4.5 Status Bar

Display:

- Active file language
- Current cursor line and column
- Indentation configuration
- Encoding: UTF-8
- Workspace synchronization status
- Connection status
- Current execution/debugging state

Examples:

    Ln 42, Col 17 | C++20 | Spaces: 4 | Synced

    Ln 18, Col 5  | Python 3 | Offline — locally saved

---

# 5. Workspace and File Management

## 5.1 Workspace Model

A workspace represents an independent collection of files, folders, editor settings and execution configurations.

Every workspace must have:

- Unique workspace ID
- Owner or session ID
- Display name
- Creation timestamp
- Last modification timestamp
- Workspace revision number

Design for authentication, but initially provide a working development-session identity mechanism.

Do not rely on a shared global workspace for all users.

## 5.2 File Explorer

Required features:

- Create files.
- Create folders.
- Create nested folders.
- Rename files and folders.
- Delete files and folders.
- Duplicate files.
- Move files between folders.
- Expand and collapse folder nodes.
- Open files using mouse or keyboard.
- Context menus.
- File-type icons.
- Clear indication of the active file.

Support:

- .cpp
- .cc
- .cxx
- .h
- .hpp
- .py
- .java
- .txt
- .in
- .out

Files must have stable UUID identifiers independent of their paths.

Renaming a file must not destroy its editing history.

Deletion must preserve an auditable event. Deleted content should remain recoverable from history during the configured retention period.

## 5.3 Multiple Tabs

Users must be able to open multiple files.

Required behavior:

- Switch tabs without losing content.
- Close tabs without deleting files.
- Reopen existing files.
- Display modified/unsynchronized state.
- Restore open tabs after reload.
- Preserve file-specific cursor position and scroll state.
- Move tabs between split editor groups.

Each file must have a persistent Monaco model.

Avoid creating duplicate text models for the same file.

## 5.4 Split Editor

Support two editor groups displayed side by side.

Requirements:

- Both groups may show different files.
- Both groups may show the same file.
- If the same file is shown twice, edits must synchronize immediately.
- Each editor pane must maintain independent cursor and scroll positions.
- Divider must be draggable.
- Tabs may move between groups.
- Closing the second group must not delete files.
- Split configuration must survive reload.

Minimum v1.0 requirement: horizontal split into two columns.

Additional nested splits are not required.

---

# 6. Monaco Editor

## 6.1 Basic Editing

Enable:

- Syntax highlighting
- Automatic indentation
- Auto-closing brackets and quotes
- Bracket matching
- Line numbers
- Code folding
- Minimap
- Word wrap
- Find and replace
- Multi-cursor editing
- Multiple selections
- Undo/redo
- Comment/uncomment shortcuts
- Configurable indentation
- Configurable font size
- Whitespace visualization
- Line highlighting
- Basic autocomplete

Autocomplete must use code already available within the workspace or permitted static language functionality.

Do not implement external AI code generation or AI autocomplete.

## 6.2 Themes

Provide at least:

- Dark Modern — default
- Light
- High Contrast

Persist the selected theme per user/session.

## 6.3 Settings

Implement a functional settings interface.

Settings must include:

- Theme
- Font size
- Font family
- Tab size
- Tabs versus spaces
- Word wrap
- Minimap enabled/disabled
- Auto-closing brackets
- Line numbers
- Cursor style
- Auto-save behavior
- Keyboard shortcut reference

Settings must persist across reloads.

---

# 7. Languages and Compilation

## 7.1 Supported Languages

### C++

Support C++17 and C++20.

Provide corresponding compiler configurations using GCC.

Use predefined compiler options.

Initial proposed configuration:

    g++ -std=c++17 -O2 -pipe
    g++ -std=c++20 -O2 -pipe

Debug builds must use debug symbols and appropriate optimization settings, for example -O0 -g.

Compiler versions must be visible in the UI or documentation.

### Python

Use CPython 3.

Python programs execute without a separate native compilation phase.

Provide a syntax/initialization error state where appropriate.

### Java

Use OpenJDK 17.

Compile using javac and execute using java.

The system must handle Java source filenames and main class resolution correctly.

## 7.2 Entry Point Selection

The user must explicitly select an execution entry point.

C++:
- Select a main source file.
- Include additional project source files according to a deterministic build configuration.
- Do not automatically compile every .cpp file if doing so would create duplicate main functions.

Python:
- Select the entry-point .py file.
- Allow imports from workspace files.

Java:
- Select the main class.
- Respect standard Java source/package constraints supported by the build configuration.

Allow separate Run Configurations if a workspace has multiple independent solutions.

## 7.3 Multiple Files

Workers must receive a consistent snapshot of the necessary workspace files for a specific execution.

Implement an explicit compilation manifest.

Prevent:

- Path traversal
- Symlink escape
- Access to host files
- Arbitrary external filesystem mounts
- Injection of unapproved build arguments

Do not grant participants unrestricted shell access.

---

# 8. Remote Code Execution

## 8.1 Execution Flow

    Monaco Editor
         |
         v
    Frontend API Client
         |
         v
    FastAPI Backend
         |
         v
    Persistent Execution Queue
         |
         v
    Isolated Worker
         |
         v
    Compilation + Execution
         |
         v
    Result Stream
         |
         v
    Integrated Terminal

## 8.2 Run Action

When the participant clicks Run:

1. Capture the exact current workspace revision.
2. Create an immutable execution snapshot.
3. Send a Run request to the backend.
4. Validate language, entry point and input size.
5. Enqueue an execution job.
6. Assign the job to an available worker.
7. Compile the program if necessary.
8. Execute it within resource limits.
9. Stream or return results.
10. Store execution metadata.
11. Display results in the terminal.

Editing must remain available while execution is in progress.

Changes made after Run must not alter that execution's source snapshot.

## 8.3 Resource Limits

Make limits configurable on the server.

Provide safe development defaults such as:

- Execution CPU limit: 2 seconds
- Execution wall-clock limit: 5 seconds
- Execution memory limit: 256 MiB
- Output limit: 1 MiB
- Compilation wall-clock limit: 30 seconds
- Compilation memory limit: configured separately
- Maximum source/workspace size: configurable
- Maximum simultaneous executions per session: 1

These are initial example limits, not universal competition limits.

The worker must enforce limits, not merely trust frontend settings.

## 8.4 Execution Results

Support these result types:

- Success
- Compilation Error
- Runtime Error
- Time Limit Exceeded
- Memory Limit Exceeded
- Output Limit Exceeded
- Cancelled
- Worker/Infrastructure Error

Return:

- Job ID
- Source snapshot ID
- Language
- Compiler/toolchain version
- Exit code
- stdout
- stderr
- Compilation diagnostics
- Wall-clock execution time
- CPU time when supported
- Memory usage when supported
- Final status

Do not fabricate unsupported resource metrics.

## 8.5 Stop Action

The user must be able to stop execution.

The backend must:

- Mark cancellation requested.
- Terminate the correct isolated process group.
- Reclaim temporary resources.
- Publish a terminal cancellation state.

Closing the browser must not leave unlimited orphan jobs.

---

# 9. Integrated Terminal

## 9.1 Interface

Use xterm.js to render terminal-style output.

The panel must support:

- Terminal
- Problems
- Test Cases

Users must be able to resize or collapse the bottom panel.

## 9.2 Terminal Functionality

Display:

- Build progress
- Compiler messages
- Program stdout
- Program stderr
- Runtime errors
- Execution statistics

Support:

- Clear output
- Copy output
- Scrollback
- Automatic scrolling, with pause when manually scrolled
- Run/Stop controls

The terminal must not provide a general Linux shell.

## 9.3 Standard Input

Initially, normal Run mode uses a predefined stdin buffer.

Participants must be able to enter or paste stdin before execution.

The current Run mode is non-interactive: stdin is fixed at launch.

Interactive stdin streaming may be implemented for the debugger if required by its protocol, but must not silently change the behavior of standard Run mode.

The system must clearly distinguish ordinary output from compile errors.

---

# 10. Custom Test Cases

## 10.1 Test Management

Participants must be able to:

- Create test cases.
- Rename test cases.
- Delete test cases.
- Edit stdin.
- Specify optional expected stdout.
- Save tests per workspace or Run Configuration.
- Run one test.
- Run all saved tests.
- Inspect previous results.

## 10.2 Results

For each test display:

- Test name
- Actual stdout
- Expected stdout, if provided
- stderr
- Execution status
- Execution time
- Pass/fail comparison when expected output exists

Output comparison must use a documented policy.

Default v1.0 comparison: exact output comparison after normalization of CRLF/LF line endings only.

Do not silently ignore whitespace differences.

## 10.3 Concurrent Execution

Run All should enqueue tests with controlled concurrency.

The frontend must present progress and partial results.

Backend limits must prevent one participant from monopolizing the worker pool.

---

# 11. Autosave and Workspace Recovery

This section is critical.

## 11.1 Persistence Layers

Implement two persistence layers:

**Local persistence:** IndexedDB.

**Durable remote persistence:** PostgreSQL-backed workspace storage.

Local storage protects against ordinary reloads and short connection interruptions.

Server persistence protects against loss of the local browser state, subject to successful synchronization and retention policies.

## 11.2 Autosave Requirements

After editing:

1. Apply changes immediately to Monaco.
2. Record the editing event.
3. Persist the change/event to the local queue.
4. Update the local recoverable document state.
5. Synchronize with backend asynchronously.
6. Mark acknowledged events as synchronized.

Do not block typing while waiting for network acknowledgement.

The system must not display "Synced" until the server confirms durability.

## 11.3 Refresh Recovery

After browser reload, restore:

- Workspace and file tree
- File contents
- Active file
- Open tabs
- Split editor state
- Cursor and scroll positions where available
- Settings
- Test cases
- Outstanding telemetry queue
- Synchronization state

Reloading while an execution is in progress must allow the client to query the surviving job state.

## 11.4 Offline Mode

If connectivity is lost:

- Editing continues.
- Files remain locally recoverable.
- Telemetry is queued locally.
- Run and Debug are disabled with clear explanations.
- UI shows Offline.
- Synchronization retries after reconnecting.
- User receives a warning if local storage is unavailable or close to capacity.

Offline support must not imply that the browser can guarantee storage under every condition.

## 11.5 Conflicts

Use workspace revisions and optimistic concurrency controls.

If another browser instance modifies the same workspace:

- Detect the conflict.
- Preserve both versions.
- Avoid silent overwriting.
- Provide a conflict resolution mechanism or independent recovered copy.

The default policy is no automatic last-write-wins for conflicting text changes.

---

# 12. Keyboard and Editing Telemetry

## 12.1 Importance

Detailed input telemetry is a primary system requirement.

The goal is to reconstruct the editing process and provide structured data for later behavioral analysis.

Telemetry must be collected from the code editor only.

Do not create a global keylogger.

## 12.2 Keyboard Events

Capture observable Monaco keyboard events:

- Keydown
- Keyup
- Key code
- Modifier state
- Repeat indicator where available
- Event timestamp

Capture keyboard input only while the Monaco editor has focus.

Do not record input in unrelated forms, passwords, authentication components or other websites.

Do not assume keyboard events capture every physical keystroke under all operating systems, browsers or input methods.

## 12.3 Document Editing Events

Capture every observable Monaco document modification:

- Text insertion
- Text deletion
- Replacement
- Paste
- Undo
- Redo
- Multiple simultaneous edits
- Composition-related changes
- Editor-generated modifications

For each modification, record:

- File ID
- Document revision before/after
- Offset and/or range
- Deleted length
- Inserted text
- Undo/redo metadata where available
- Event timestamp
- Event sequence number

Document changes must be sufficient to deterministically reconstruct the code.

## 12.4 Additional Editor Events

Capture:

- Cursor position changes
- Selection changes
- Active file changes
- Editor focus gained/lost
- Page visibility changes
- File creation
- File rename
- File deletion
- Tab switches
- Split Editor actions
- Run
- Debug
- Stop
- Test Case execution

To control volume, nonessential high-frequency events such as cursor movements may be compacted or sampled using a documented policy.

Do not sample, merge away or discard text-changing events needed for reconstruction.

## 12.5 Event Schema

Use a versioned schema.

Example:

    {
      "schemaVersion": 1,
      "eventId": "uuid",
      "sessionId": "uuid",
      "workspaceId": "uuid",
      "fileId": "uuid",
      "sequence": 12345,
      "clientTimestamp": "ISO-8601",
      "monotonicOffsetMs": 12841.75,
      "type": "document_change",
      "payload": {
        "beforeRevision": 17,
        "afterRevision": 18,
        "changes": [
          {
            "offset": 102,
            "deletedLength": 0,
            "insertedText": "int x = 0;"
          }
        ]
      }
    }

A monotonic event sequence must exist per telemetry session.

Document revisions must be maintained independently per file.

## 12.6 Event Ordering

Requirements:

- Every event has a unique ID.
- Events have stable ordering within a session.
- Each batch identifies its sequence range.
- Backend detects missing sequences.
- Backend safely ignores duplicate event IDs.
- Retries must be idempotent.
- Client persists events before considering them locally committed.

Server timestamps must be recorded upon ingestion.

Client timestamps are useful for behavioral analysis but are not trusted as authoritative timestamps.

## 12.7 Data Durability

Use a durable local event queue.

The event pipeline must not drop required document changes when the network is slow.

If persistent storage fails, clearly report that recording/recovery is degraded rather than silently continuing.

Provide configurable storage limits and retention policies.

Telemetry recording and status must be disclosed clearly to participants.

---

# 13. Editing History Replay

## 13.1 Objective

Provide a functional replay mechanism that reconstructs the document at any recorded point in the editing timeline.

This is not a screen video.

It is a reconstruction of code and editor events.

## 13.2 Replay UI

Add a History view containing:

- Timeline slider
- Play/Pause
- Previous event
- Next event
- Playback speed selector
- Current replay timestamp
- Current file
- Event description
- Read-only code editor

Supported playback speeds:

- 0.5×
- 1×
- 2×
- 4×
- 8×

Replay must support seeking backward and forward.

## 13.3 Replay Engine

Implement replay using:

- Initial file snapshot
- Ordered document changes
- Periodic checkpoints

Do not reconstruct every seek by replaying the entire history from the beginning if checkpoints are available.

The replay engine must be independent of the React UI.

It should accept event streams and return reconstructed document states.

## 13.4 Checkpoints

Create checkpoints:

- On initial file creation
- Periodically during editing
- Before or at execution snapshot creation
- When explicitly requested by the persistence strategy

Checkpoint frequency must be configurable.

A reasonable initial default is every 60 seconds or every 500 document-changing events, whichever occurs first.

Store sufficient integrity metadata to detect inconsistent reconstruction.

## 13.5 Replay Requirements

The system must:

- Reconstruct file contents deterministically.
- Represent file creations, renames and deletions.
- Track active-file changes.
- Show large paste operations.
- Restore states after Undo/Redo.
- Handle rapid consecutive edits.
- Handle multiple-file sessions.
- Display gaps or unavailable telemetry honestly.
- Never invent missing intermediate edits.

Replay is read-only.

Normal editing must not modify historical data.

---

# 14. Interactive Debugger

## 14.1 Objective

Implement a real interactive debugger supporting:

- C++
- Python
- Java

This is mandatory for v1.0.

Do not substitute static code highlighting or fake step buttons for actual debugging.

## 14.2 Architecture

Use the Debug Adapter Protocol (DAP).

Suggested adapters:

- C++: GDB via a suitable DAP adapter
- Python: debugpy
- Java: a compatible Java debug adapter

Verify licensing, deployment suitability and standalone operation of each adapter before integration.

The browser must never connect directly to an unrestricted debugging daemon.

Architecture:

    Monaco Debug UI
          |
          v
    Debug Session API
          |
          v
    WebSocket DAP Gateway
          |
          v
    Isolated Debug Worker
          |
          v
    Language Debug Adapter
          |
          v
    Program Being Debugged

## 14.3 Required Features

Support:

- Start Debugging
- Stop Debugging
- Continue
- Pause
- Step Over
- Step Into
- Step Out
- Source-line breakpoints
- Current execution line highlighting
- Call Stack
- Variables panel
- Local variable inspection
- Execution status messages

Conditional breakpoints and Watch Expressions are desirable but not required for the initial v1.0 acceptance.

## 14.4 Breakpoints

Users must be able to:

- Add breakpoints by clicking the editor gutter.
- Remove breakpoints.
- View active breakpoints.
- Navigate to source lines.
- Preserve breakpoints across page reloads.

Breakpoints must be associated with stable file IDs and source locations.

Reconcile breakpoint positions when editing changes line numbers, using documented best-effort behavior.

## 14.5 Variables

Display:

- Variable name
- Type when available
- Current value
- Expandable child values where supported

Do not execute arbitrary user expressions in the host environment.

All debugger evaluation must occur within the isolated debug session and respect configured restrictions.

## 14.6 Debug Session Isolation

Debug sessions must have:

- Dedicated process isolation
- Session ownership checks
- Strict resource limits
- Session timeout
- Automatic cleanup
- Restricted filesystem
- No network access by default

Debugging C++, Python and Java may require language-specific sandbox permissions.

These must be configured explicitly.

Do not weaken the main API server security to enable debugging.

## 14.7 Debugging and Telemetry

Record high-level debugging actions:

- Debug started
- Breakpoint added/removed
- Step command
- Resume/pause
- Debug stopped

Associate debugging sessions with immutable source snapshots.

Do not include debugger evaluation input in keyboard telemetry unless it is explicitly a supported, disclosed part of the editor's collection scope.

---

# 15. Backend API

Implement versioned REST APIs and WebSocket endpoints.

## 15.1 Workspace APIs

    GET    /api/v1/workspaces
    POST   /api/v1/workspaces
    GET    /api/v1/workspaces/{id}
    PATCH  /api/v1/workspaces/{id}
    DELETE /api/v1/workspaces/{id}

File APIs:

    POST   /api/v1/workspaces/{id}/files
    PATCH  /api/v1/files/{id}
    DELETE /api/v1/files/{id}

Define equivalent folder operations.

## 15.2 Telemetry APIs

    POST /api/v1/telemetry/batches
    GET  /api/v1/telemetry/sessions/{id}/status

The batch endpoint must support acknowledgements and idempotent ingestion.

## 15.3 Execution APIs

    POST /api/v1/executions
    GET  /api/v1/executions/{id}
    POST /api/v1/executions/{id}/cancel
    GET  /api/v1/executions/{id}/events

Execution event streaming may use WebSocket or Server-Sent Events.

## 15.4 Debug APIs

    POST /api/v1/debug/sessions
    POST /api/v1/debug/sessions/{id}/stop
    WS   /api/v1/debug/sessions/{id}/dap

## 15.5 History APIs

    GET /api/v1/workspaces/{id}/history
    GET /api/v1/files/{id}/snapshots
    GET /api/v1/files/{id}/events

Support pagination and bounded query ranges.

Require authorization for all workspace-specific resources.

---

# 16. Database Design

Implement the following logical entities:

## 16.1 UserSession

Fields:

- id
- user_id or development identity
- created_at
- last_seen_at
- expires_at

## 16.2 Workspace

Fields:

- id
- owner_id
- name
- revision
- created_at
- updated_at

## 16.3 FileNode

Fields:

- id
- workspace_id
- parent_id
- name
- type
- path
- language
- created_at
- updated_at
- deleted_at

## 16.4 FileSnapshot

Fields:

- id
- file_id
- revision
- content
- content_hash
- created_at

## 16.5 EditorEvent

Fields:

- id
- session_id
- workspace_id
- file_id
- sequence
- schema_version
- event_type
- client_timestamp
- server_timestamp
- monotonic_offset
- payload

Create indexes for efficient retrieval by session, file, sequence and timestamp.

## 16.6 Execution

Fields:

- id
- workspace_id
- source_snapshot_id
- language
- entry_point
- status
- stdout
- stderr
- exit_code
- cpu_time
- wall_time
- memory_usage
- created_at
- completed_at

## 16.7 TestCase

Fields:

- id
- workspace_id
- name
- stdin
- expected_stdout
- created_at
- updated_at

## 16.8 DebugSession

Fields:

- id
- workspace_id
- source_snapshot_id
- status
- started_at
- completed_at
- worker_id

Add tables for workspace settings, event acknowledgements and execution jobs where necessary.

Use migrations rather than manually maintained database schemas.

---

# 17. Security Requirements

Treat all submitted source code as untrusted.

Mandatory controls:

- Server-side input validation
- Authentication/session ownership checks
- Authorization on all workspace and execution resources
- HTTPS in production
- Secure WebSocket authentication
- API rate limiting
- Request body limits
- File count and workspace size limits
- Execution quotas
- Debug-session quotas
- Sandboxed compilation and execution
- Worker filesystem cleanup
- Restricted network access
- No privileged worker processes
- No arbitrary host shell access
- Safe log handling
- Secrets stored outside source control

Avoid storing passwords, tokens or unrelated personal input in editor telemetry.

Implement retention and deletion policies for workspace histories and telemetry.

Do not claim the system can reliably identify or prevent all cheating.

---

# 18. Reliability Requirements

The application must handle:

- Browser refresh
- Browser tab closure
- Network disconnection
- Network reconnection
- Duplicate event transmission
- Out-of-order event delivery
- Worker failure
- Compilation timeout
- Debugger crash
- Backend process restart
- Malformed event payloads
- Invalid workspace references

No failure should silently corrupt synchronized source code.

If recovery is not possible, show a clear error and preserve recoverable local data.

Use structured server logs with request/job IDs.

---

# 19. Performance Requirements

Target workload:

- 300 concurrent active editor sessions
- 500 registered participants in an event
- Five-hour competition duration
- Frequent editing events
- Bursty Run requests

These are design targets to validate through load testing, not guaranteed hardware capacity.

Performance targets on an appropriately provisioned system:

- Typing should remain visually responsive without network dependencies.
- Local autosave should not noticeably block editing.
- Editor panel interactions should remain smooth.
- Event ingestion must handle at least 300 active sessions during load tests.
- Execution job status must be observable.
- Replay must seek efficiently using checkpoints.

Measure:

- Input latency
- Event queue size
- Synchronization latency
- API response latency
- Execution queue waiting time
- Worker utilization
- Replay seek duration
- Browser memory usage

Document the test environment and observed results.

---

# 20. Automated Testing

## 20.1 Frontend Unit Tests

Cover:

- Workspace tree operations
- File tab management
- Split Editor behavior
- Settings persistence
- Telemetry serialization
- Local queue ordering
- Replay reconstruction
- Synchronization state transitions

## 20.2 Backend Tests

Cover:

- Session ownership and authorization
- Workspace CRUD
- File persistence
- Event ingestion
- Duplicate event handling
- Sequence gap detection
- Execution scheduling
- Execution cancellation
- Resource-limit reporting
- Debug session lifecycle

## 20.3 End-to-End Tests

Use Playwright or equivalent.

Required scenarios:

1. Create a workspace.
2. Create multiple source files.
3. Edit and switch tabs.
4. Reload and verify contents.
5. Enable Split Editor.
6. Edit the same file in both panes.
7. Run a C++ program.
8. Run a Python program.
9. Run a Java program.
10. Execute multiple custom tests.
11. Disconnect/reconnect the network.
12. Verify queued events synchronize.
13. Replay a previous editing session.
14. Debug a program with breakpoints.
15. Stop an executing program.
16. Recover the workspace after reopening the application.

## 20.4 Telemetry Integrity Tests

Test:

- Rapid typing
- Continuous Backspace
- Large paste
- Undo/Redo sequences
- Unicode text
- Composition/IME input
- Multiple cursors
- Simultaneous edits
- File renames
- File deletions
- Split editing
- Offline editing
- Duplicate batch upload
- Browser refresh with pending events

Compare reconstructed documents against known ground-truth contents.

---

# 21. Acceptance Criteria

The first release is accepted only when the following criteria are satisfied.

## A. Editor

- [ ] VS Code-inspired interface implemented.
- [ ] Monaco functions with C++, Python and Java.
- [ ] Multiple files and nested folders are supported.
- [ ] Tab switching preserves document state.
- [ ] Themes and editor settings work.
- [ ] Keyboard shortcuts work.
- [ ] Split Editor shows two independent panes.
- [ ] Editing the same file in both panes stays synchronized.

## B. Persistence

- [ ] Files survive browser refresh.
- [ ] Settings survive browser refresh.
- [ ] Tabs and split layout survive browser refresh.
- [ ] Local editing works offline.
- [ ] Pending events synchronize after reconnection.
- [ ] Synchronization errors are visible.
- [ ] Concurrent update conflicts do not silently overwrite data.

## C. Execution

- [ ] C++17 works.
- [ ] C++20 works.
- [ ] Python 3 works.
- [ ] Java 17 works.
- [ ] Multi-file execution rules are implemented.
- [ ] stdout and stderr are shown.
- [ ] Compilation errors are shown.
- [ ] Execution limits are enforced.
- [ ] Running jobs can be cancelled.
- [ ] Multiple test cases work.
- [ ] Source snapshots are immutable per execution.
- [ ] Execution is isolated from the API server.

## D. Telemetry

- [ ] Observable Monaco keydown/keyup events are captured.
- [ ] Every document-changing event is captured.
- [ ] File operations are recorded.
- [ ] Event IDs and sequence numbers are present.
- [ ] Offline event buffering works.
- [ ] Retries do not create duplicate events.
- [ ] Sequence gaps are detected.
- [ ] Checkpoints are generated.
- [ ] Recorded changes reconstruct documents accurately.
- [ ] Telemetry does not collect unrelated application input.

## E. Replay

- [ ] Replay timeline works.
- [ ] Play/Pause works.
- [ ] Playback speed can be changed.
- [ ] Seeking backward and forward works.
- [ ] File operations appear in history.
- [ ] Large inserts are visible.
- [ ] Undo/Redo history is represented.
- [ ] Replay is read-only.
- [ ] Missing data is identified rather than fabricated.

## F. Debugging

- [ ] C++ breakpoint debugging works.
- [ ] Python breakpoint debugging works.
- [ ] Java breakpoint debugging works.
- [ ] Step Over works.
- [ ] Step Into works.
- [ ] Step Out works.
- [ ] Continue works.
- [ ] Stop works.
- [ ] Variables are displayed.
- [ ] Call Stack is displayed.
- [ ] Debugging runs in a restricted worker environment.

## G. Delivery

- [ ] Frontend and backend source code included.
- [ ] Database migrations included.
- [ ] Docker Compose development environment included.
- [ ] Worker configuration documented.
- [ ] Automated tests included.
- [ ] README with exact setup instructions included.
- [ ] Known limitations documented.
- [ ] No fake execution or debugging features remain.

---

# 22. Development Phases

Implement sequentially.

## Phase 1 — Foundation and UI

- Initialize project.
- Configure frontend/backend.
- Implement VS Code-inspired layout.
- Integrate Monaco.
- Implement Explorer and tabs.
- Implement settings and themes.
- Implement Split Editor.

Deliverable: usable frontend workspace.

## Phase 2 — Persistence

- Implement workspace/file database.
- Implement local IndexedDB persistence.
- Implement autosave.
- Restore workspace after reload.
- Implement synchronization and conflict handling.

Deliverable: persistent multi-file editor.

## Phase 3 — Telemetry

- Implement keyboard event collection.
- Implement document event collection.
- Implement event schemas.
- Implement durable local queue.
- Implement batch ingestion.
- Implement acknowledgements, retries and deduplication.
- Implement checkpoints.

Deliverable: complete recorded editing sessions.

## Phase 4 — Execution

- Implement job queue.
- Implement sandbox worker.
- Add C++, Python and Java toolchains.
- Add Run/Stop.
- Add terminal output.
- Add custom test cases.
- Add source snapshots.

Deliverable: functional remote code execution.

## Phase 5 — History Replay

- Implement deterministic replay engine.
- Implement timeline UI.
- Add seeking and playback controls.
- Reconstruct multi-file workspaces.
- Test event integrity.

Deliverable: full editing-history playback.

## Phase 6 — Interactive Debugger

- Implement DAP gateway.
- Integrate C++ debugger.
- Integrate Python debugger.
- Integrate Java debugger.
- Add breakpoints, stepping and variable inspection.
- Harden debug-worker isolation.

Deliverable: functional interactive debugging for all three languages.

## Phase 7 — Quality and Release

- Integration tests
- End-to-end tests
- Security review
- Load tests
- Recovery tests
- Documentation
- Development deployment

Deliverable: v1.0 release candidate satisfying all acceptance criteria.

---

# 23. Explicitly Out of Scope

Do not implement:

- AI cheating classification
- Machine learning training
- Jury review dashboard
- CMS submission integration
- Webcam recording
- Screen recording
- Global system-wide keylogging
- Public plugin marketplace
- Multiplayer collaborative editing
- AI-generated code suggestions
- Arbitrary shell access
- Remote desktop functionality

The architecture must allow future integration with CMS and analytical services.

---

# 24. Instructions for Codex

You are the lead software engineer responsible for implementing Olympiad IDE v1.0.

Treat this document as the source of truth for scope.

Before changing source code:

1. Inspect the repository.
2. Identify existing infrastructure and reusable components.
3. Create an implementation plan mapped to the phases above.
4. Define database models and API contracts.
5. Identify security-sensitive execution and debugging boundaries.
6. Document decisions and assumptions.

Then implement in small, testable increments.

For each phase:

1. Implement required functionality.
2. Add relevant automated tests.
3. Run linting, type checking and tests.
4. Fix discovered failures.
5. Update documentation.
6. Report completed requirements and remaining limitations.

Do not claim a feature is implemented solely because a UI control exists.

Buttons must perform real operations.

When backend functionality is unavailable during development, identify it explicitly as incomplete. Do not silently substitute mock execution, fabricated output or simulated debugger states.

Prefer completing a working vertical slice over creating many partially functional features.

If the repository has existing code, preserve working functionality and avoid unnecessary rewrites.

Prioritize, in order:

1. Data integrity
2. Security of untrusted execution
3. Correctness of core functionality
4. Reliability and recovery
5. Usability
6. Visual polish

**Definition of Done:** The project is complete only when all mandatory v1.0 acceptance criteria pass and the IDE can be deployed locally with documented commands.
