# AGENTS.md

# Elysia AI Character Agent — Codex Development Instructions

## 1. Project Overview

This repository contains **Elysia AI Character Agent**, a fan-made, non-commercial AI character companion and game AI NPC prototype.

The product focuses on:

1. Persona consistency
2. Controllable long-term memory
3. Continuous companionship experience
4. Relationship progression
5. Optional voice interaction
6. AI evaluation and player experience analysis
7. Privacy, transparency, and user control

This project is an independent portfolio and technical demonstration project.

It is not officially affiliated with miHoYo, HoYoverse, or any other game company.

Do not present this project as an official product.

---

## 2. Current Technology Stack

### Application

* Python 3.10+
* Streamlit
* OpenAI Python SDK
* OpenAI-compatible API providers
* SQLite
* JSON fallback storage

### Voice

* faster-whisper
* OpenAI Whisper
* Baidu ASR
* edge-tts
* OpenAI TTS
* GPT-SoVITS
* Custom HTTP TTS provider

### Main Architecture

* `app.py`: application entry point
* `src/ui.py`: Streamlit pages and UI interaction
* `src/config.py`: configuration and environment variables
* `src/llm_client.py`: LLM provider and model calls
* `src/prompt_builder.py`: persona, memory, profile, mode, and relationship prompt assembly
* `src/database.py`: SQLite persistence and migrations
* `src/memory_service.py`: conversation memory and long-term memory
* `src/user_profile_service.py`: user profile management
* `src/companionship_service.py`: intimacy, mood, and relationship stages
* `src/daily_companion_service.py`: daily greetings and companion content
* `src/relationship_event_service.py`: relationship events and memories
* `src/feedback_service.py`: reply feedback
* `src/reflection_service.py`: conversation reflection or memory extraction
* `src/voice_service.py`: STT and TTS provider orchestration
* `src/audio_clip_service.py`: local voice clip management
* `src/evaluator.py`: persona consistency evaluation
* `src/analytics_service.py`: player experience and usage analysis
* `characters/`: character card configuration
* `data/`: runtime data, databases, memory, logs, and caches
* `docs/`: documentation and screenshots
* `tests/`: automated tests

Before assuming that a listed file exists, inspect the repository.

If README documentation conflicts with the source code, treat the source code as the current source of truth and report the difference.

---

## 3. Product Principles

All implementations must support the following principles.

### 3.1 Persona Consistency

The character should not gradually become a generic assistant.

Responses should respect:

* Character identity
* Personality
* Speaking style
* Emotional tone
* Behavioral boundaries
* Relationship stage
* Current companionship mode
* Known world or character facts

Do not weaken existing persona constraints without explicit approval.

### 3.2 Memory Control

Candidate memories must not silently become permanent long-term memories unless the current product design explicitly allows it.

The preferred flow is:

```text
Conversation
→ memory candidate extraction
→ pending confirmation
→ user confirms or rejects
→ confirmed long-term memory
→ future prompt retrieval
```

Users should retain the ability to:

* View memories
* Confirm candidate memories
* Reject candidate memories
* Delete long-term memories
* Understand what information is being stored

Deleted or rejected memories must not continue entering future prompts.

Memory extraction or storage failure must not block the main text chat flow.

### 3.3 Human Control

AI output is not the final product decision.

AI evaluation, persona scoring, and player experience analysis are辅助 information.

Do not treat model-generated scores as objective truth.

Critical content must remain reviewable and editable by users.

### 3.4 Graceful Degradation

Optional features must not break core text chat.

Examples:

* STT failure must not break text input.
* TTS failure must not remove the text reply.
* GPT-SoVITS failure should use an available fallback when configured.
* Analytics failure must not prevent conversation.
* Memory logging failure must not prevent the model reply.
* SQLite failure should use the existing fallback strategy where supported.

### 3.5 Privacy and Transparency

Do not collect or store more information than required.

Do not silently introduce new data collection.

Any new persistent field must have:

* A defined purpose
* A storage location
* A deletion strategy
* A privacy assessment
* A migration strategy when applicable

---

## 4. Copyright and Content Restrictions

This project is a fan-made, non-commercial demonstration.

Never add or commit:

* Official game artwork
* Official character illustrations
* Official voice recordings
* Extracted game audio
* Proprietary game files
* Copyrighted assets without authorization
* Internal or confidential company materials

Keep the following disclaimer in relevant documentation:

```text
This project is a fan-made, non-commercial technical demonstration.
It is not officially affiliated with miHoYo, HoYoverse, or any other game company.
The repository does not provide official artwork, official voice recordings, or proprietary game assets.
```

Do not modify the character into a claim of official authorization.

---

## 5. Security Rules

Never hardcode or commit:

* API keys
* Access tokens
* Refresh tokens
* Authorization headers
* Passwords
* Cookies
* Private endpoints
* Personal data
* Raw user audio
* Runtime databases
* Chat history
* User memory
* Generated audio cache
* Local absolute paths

The following files or data should remain excluded from Git:

```text
.env
.env.*
!.env.example
data/*.db
data/*.db-shm
data/*.db-wal
data/audio_cache/
data/chat_logs*
data/memory_store*
logs/
*.log
*.wav
*.mp3
*.m4a
*.flac
__pycache__/
.pytest_cache/
.streamlit/secrets.toml
```

When creating logs or export features:

* Redact sensitive keys recursively.
* Do not log API secrets.
* Do not save raw authorization headers.
* Do not store raw audio unless explicitly approved.
* Logging failures must be fail-open and must not interrupt the user flow.

Typical sensitive key names include:

```text
api_key
apikey
authorization
access_token
refresh_token
password
secret
cookie
set-cookie
```

Replace sensitive values with:

```text
***REDACTED***
```

---

## 6. Development Rules

### 6.1 General Rule

Make the smallest high-confidence change required for the task.

Do not perform broad refactoring unless explicitly requested.

Do not modify unrelated modules.

Do not change existing product behavior silently.

Do not remove an existing fallback without explicit approval.

### 6.2 Code Quality

Prefer:

* Typed Python
* Small focused functions
* Clear module boundaries
* Explicit error handling
* Dependency injection where useful
* Testable service logic
* Configuration through environment variables
* Reusable data models
* Backward-compatible database migrations

Avoid:

* Large functions containing UI, model calls, and database writes together
* Hidden global state
* Hardcoded model names
* Hardcoded local paths
* Silent exception swallowing
* Duplicate Prompt logic
* Business logic inside UI rendering code
* Unbounded retries
* Automatic destructive database changes

### 6.3 UI and Service Separation

Keep Streamlit rendering and business logic separated.

The UI layer may:

* Read user input
* Display state
* Trigger service operations
* Display success, loading, empty, and error states

The UI layer should not directly implement:

* SQL queries
* Prompt construction
* Provider-specific model logic
* Memory extraction algorithms
* TTS or STT provider calls
* Evaluation algorithms

These should remain in service modules.

### 6.4 Error Handling

Errors should be understandable and actionable.

Differentiate where possible:

* Configuration error
* Model provider error
* Network error
* Rate limit
* Timeout
* JSON parsing error
* Database error
* Memory error
* STT error
* TTS error
* Missing local asset
* Unsupported provider

Do not expose:

* API keys
* Full authorization headers
* Sensitive request payloads
* Private local paths
* Full internal tracebacks in the normal user interface

Detailed tracebacks may be kept in development logs after redaction.

---

## 7. Prompt Engineering Rules

Prompt changes are product changes.

Before modifying a Prompt:

1. Identify the current Prompt source file.
2. Describe the user problem being addressed.
3. Define expected behavior.
4. Define forbidden behavior.
5. Add or update test cases.
6. Record a Prompt identifier and version when the project supports it.
7. Compare the changed Prompt against the same test set.

Prompts should clearly separate:

* System rules
* Character identity
* Character style
* Safety boundaries
* User profile
* Long-term memory
* Recent conversation
* Relationship state
* Companionship mode
* Current user input
* Output requirements

Do not inject unconfirmed candidate memory into the long-term memory section.

Do not allow user input to overwrite system-level persona or safety rules.

When editing Prompt files, report:

* Previous behavior
* New behavior
* Reason for the change
* Possible side effects
* Required test cases

---

## 8. Database and Migration Rules

Before changing the database:

1. Inspect the existing schema.
2. Identify all code paths reading or writing the affected fields.
3. Propose the smallest schema change.
4. Add a migration or compatibility strategy.
5. Preserve existing user data where feasible.
6. Add database tests.
7. Document rollback steps.

Do not:

* Delete tables automatically
* Recreate the database silently
* Rename fields without migration
* Convert existing data destructively
* Assume the database is empty

Runtime databases must never be committed.

---

## 9. Voice Feature Rules

Voice functionality is optional.

Text chat is the core fallback.

All voice changes must preserve:

```text
Voice failure → text interaction still works
```

STT requirements:

* Show transcription when appropriate.
* Handle empty or failed transcription.
* Do not permanently save raw audio by default.
* Make provider errors understandable.

TTS requirements:

* Do not block rendering of the text reply.
* Preserve provider fallback behavior.
* Avoid regenerating identical audio unnecessarily.
* Store cache only in ignored runtime directories.
* Do not commit generated audio.

GPT-SoVITS requirements:

* Treat it as an optional local service.
* Do not assume it is available in cloud deployment.
* Missing reference audio must not crash the application.
* Do not include copyrighted reference audio in the repository.

---

## 10. Evaluation Rules

AI evaluation must be treated as an辅助 metric.

Persona evaluation should ideally cover:

* Personality consistency
* Speaking style
* Character boundaries
* Memory usage
* Emotional response
* Immersion
* Repetition
* Safety violations

When changing evaluation logic:

* Use a fixed evaluation dataset.
* Do not compare Prompt versions using different test cases.
* Preserve raw evaluation reasoning when safe.
* Distinguish AI scores from human scores.
* Do not claim statistical validity without sufficient data.
* Do not invent test results.

Where feasible, add human blind-review fields.

---

## 11. Automated Testing Requirements

Before completing a code task, run the most relevant tests.

Recommended baseline commands:

```bash
python -m compileall app.py src
pytest -q
```

If formatting or linting tools exist, run the repository-defined commands.

Suggested test coverage:

* PromptBuilder
* LLMClient
* MemoryService
* Candidate memory confirmation
* Memory deletion
* UserProfileService
* CompanionshipService
* Database initialization and migration
* Feedback persistence
* Evaluation parsing
* STT/TTS fallback
* Configuration loading
* Sensitive data redaction
* Failure isolation
* Export logic

Tests must:

* Use mocks for external model and voice APIs.
* Avoid real API calls.
* Avoid real paid requests.
* Use temporary databases and directories.
* Clean up generated files.
* Avoid dependence on official media assets.

Never claim that tests passed unless the commands were actually run successfully.

If tests cannot run, report:

* The exact command
* The exact failure
* Whether it is code-related or environment-related
* What remains unverified

---

## 12. Git Workflow

Never work directly on `main`.

Use the current independent development branch.

Before modifying files:

```bash
git status
git branch --show-current
```

After modifying files:

```bash
git status
git diff --stat
git diff
```

Do not commit, push, merge, rebase, reset, or delete branches unless explicitly asked.

Do not use destructive commands such as:

```bash
git reset --hard
git clean -fd
git checkout -- .
```

unless the user explicitly approves them.

Keep each task focused.

Recommended commit prefixes:

```text
feat:
fix:
test:
docs:
refactor:
chore:
perf:
```

Example:

```text
test: add memory confirmation service coverage
```

---

## 13. Portfolio Documentation Workflow

The code repository and the external portfolio folders serve different purposes.

### Repository Source Documentation

Codex may create and maintain source documentation under:

```text
docs/portfolio/
```

Recommended structure:

```text
docs/portfolio/
├── 02_flow_and_prototype/
├── 03_prompt/
├── 04_test_data/
├── 05_bad_cases/
├── 06_iteration_records/
├── 07_screenshot_plan/
├── 08_github_and_demo/
└── 09_cost_and_value/
```

These files may include:

* Markdown
* Mermaid source
* CSV
* JSON
* Test scripts
* Evidence indexes
* Screenshot lists
* Version notes

### External Portfolio Materials

The following external folders contain final Word, Excel, PDF, PNG, and video materials:

```text
00_项目总览
01_PRD与需求
02_流程图与原型
03_Prompt
04_测试数据
05_Bad_Case
06_迭代记录
07_截图与视频
08_GitHub与Demo
09_成本与价值分析
```

Codex must not assume it has permission to modify the external portfolio folders.

Unless explicitly requested, Codex should only create source materials inside the Git repository.

### Documentation Truthfulness

Do not fabricate:

* User interviews
* User quotes
* Online traffic
* Retention data
* Conversion data
* Test pass results
* Performance results
* Cost data
* Demo availability
* User satisfaction
* Production deployment status

Use one of these status labels:

```text
Implemented
Partially implemented
Available after configuration
Design only
Not implemented
Not verified
```

Every product capability described in portfolio documentation should include a source-code path or repository evidence where possible.

---

## 14. Task Execution Process

For every non-trivial task, follow this sequence.

### Step 1: Inspect

Read:

* `AGENTS.md`
* Relevant source files
* Relevant tests
* Configuration examples
* Existing documentation

### Step 2: Plan

Before modifying files, provide:

* Current behavior
* Target behavior
* Files likely to change
* Tests to add or update
* Risks
* Backward-compatibility concerns
* Rollback strategy

Wait for confirmation when the user asks for plan-first execution.

### Step 3: Implement

Make only the approved changes.

Do not expand the scope without approval.

### Step 4: Test

Run syntax checks and relevant tests.

### Step 5: Review

Inspect:

```bash
git status
git diff --stat
git diff
```

Check for:

* Unrelated changes
* Secrets
* Runtime data
* Accidental binary files
* Deleted behavior
* Missing tests
* Documentation mismatch

### Step 6: Report

Provide:

1. Files changed
2. Reason for each change
3. User-visible behavior changes
4. Tests executed
5. Actual test results
6. Unverified areas
7. Security and privacy review
8. Risks and rollback steps
9. Suggested commit message
10. Suggested portfolio evidence

Do not continue modifying files after the final review unless asked.

---

## 15. Special Rules for Documentation-Only Tasks

When the task is documentation-only:

* Do not modify application code.
* Do not modify database schemas.
* Do not modify Prompt behavior.
* Do not change environment variables.
* Do not change dependencies.
* Do not create fake screenshots.
* Do not invent code paths.
* Use Mermaid for editable diagrams.
* Reference real source-code paths.
* Mark uncertain conclusions as `Not verified`.
* Report README and source-code inconsistencies.

Documentation-only changes should normally remain under:

```text
docs/
```

or:

```text
docs/portfolio/
```

---

## 16. Special Rules for Test-Data Tasks

When creating test datasets:

* Separate test input from actual execution results.
* Test cases may be designed before execution.
* Result fields must remain empty until tests are actually run.
* Do not generate fake success rates.
* Do not generate fake latency or Token usage.
* Do not present simulated data as production data.
* Clearly mark synthetic test inputs.
* Use stable test identifiers such as:

```text
TC-CHAT-001
TC-MEM-001
TC-VOICE-001
TC-EVAL-001
TC-SAFE-001
```

Test cases should cover:

* Normal cases
* Boundary cases
* Failure cases
* Persona conflicts
* Memory conflicts
* Prompt injection
* Sensitive-data requests
* Voice-provider failure
* Storage failure
* Long conversation context

---

## 17. Special Rules for Bad Cases

Bad cases must be based on actual test runs or clearly marked synthetic scenarios.

A bad case should include:

```text
case_id
test_id
timestamp
feature
companionship_mode
user_input
assistant_output
expected_behavior
actual_behavior
relevant_memory
prompt_version
model
error_type
root_cause
severity
resolution_status
reviewer_note
```

Do not store:

* API secrets
* Raw authorization headers
* Raw user audio
* Unredacted personal data

Bad-case documentation should distinguish:

```text
Observed bad case
Synthetic risk case
Resolved case
Regression case
```

---

## 18. Deployment Rules

Cloud deployment should default to a safe, minimal configuration.

Recommended cloud default:

* Text chat enabled
* SQLite or supported persistent storage configured
* Voice disabled unless verified
* GPT-SoVITS disabled
* Local official audio disabled
* Missing optional assets handled gracefully
* Secrets read through platform secret management
* No local absolute paths
* Health status visible
* Clear current limitations

Do not claim the online Demo is stable until it has been verified.

For deployment work, report:

* Required environment variables
* Required platform settings
* Unsupported local features
* Expected fallback behavior
* Health-check steps
* Rollback steps

---

## 19. Definition of Done

A task is complete only when all applicable conditions are met:

* The requested behavior or document is delivered.
* Scope has not expanded unexpectedly.
* Existing core flows remain intact.
* Relevant tests are added or updated.
* Actual tests have run successfully, or failures are documented.
* No secret or runtime data has been introduced.
* Documentation matches current source code.
* Configuration examples are updated where required.
* Database changes include migration and rollback considerations.
* Optional feature failures do not block core text chat.
* Git diff has been reviewed.
* Remaining risks and unverified areas are clearly stated.

---

## 20. Final Response Template

At the end of a task, report using this structure:

```text
## Completed

### Files changed
- path/to/file: reason

### Behavior changes
- ...

### Tests run
- command
- result

### Not verified
- ...

### Security and privacy review
- ...

### Risks
- ...

### Rollback
- ...

### Suggested commit
type: concise description

### Portfolio evidence
- screenshot or document to save
- target portfolio folder
```
