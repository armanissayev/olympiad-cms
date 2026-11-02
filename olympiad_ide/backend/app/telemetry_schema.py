from typing import Annotated, Literal, Union
from uuid import UUID
from pydantic import AwareDatetime, BaseModel, BeforeValidator, ConfigDict, Field, PlainValidator, create_model


def source_text(value):
    # JS/Monaco strings are UTF-16 code units, not necessarily Unicode scalar strings.
    # Pydantic's normal Rust str validator rejects lone surrogates even though JSON can represent them.
    if not isinstance(value, str) or len(value.encode('utf-16-le', errors='surrogatepass')) // 2 > 2_000_000:
        raise ValueError('Source text must be a string of at most 2,000,000 UTF-16 code units')
    return value


SourceText = Annotated[str, PlainValidator(source_text, json_schema_input_type=str)]


def iso_string(value):
    if not isinstance(value, str) or 'T' not in value:
        raise ValueError('Timestamp must be an ISO string with timezone')
    return value


ISOTime = Annotated[AwareDatetime, BeforeValidator(iso_string)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class Node(Strict):
    id: UUID
    parentId: UUID | None
    name: str = Field(min_length=1, max_length=255)
    type: Literal['file', 'folder']
    content: SourceText | None
    revision: int = Field(ge=0, strict=True)


class Range(Strict):
    startLineNumber: int = Field(ge=1, strict=True)
    startColumn: int = Field(ge=1, strict=True)
    endLineNumber: int = Field(ge=1, strict=True)
    endColumn: int = Field(ge=1, strict=True)


class Change(Strict):
    offset: int = Field(ge=0, strict=True)
    deletedLength: int = Field(ge=0, strict=True)
    insertedText: SourceText
    range: Range


class Transaction(Strict):
    transactionId: UUID
    beforeRevision: int = Field(ge=1, strict=True)
    afterRevision: int = Field(ge=2, strict=True)
    changes: list[Change] = Field(max_length=10_000)
    inputEventId: UUID | None
    origin: Literal['editor', 'programmatic']
    eol: Literal['\n', '\r\n']


class Key(Strict):
    paneId: str = Field(max_length=64)
    code: str = Field(max_length=100)
    key: str = Field(max_length=100)
    ctrl: bool; alt: bool; shift: bool; meta: bool; repeat: bool; composing: bool


class Pane(Strict):
    paneId: str = Field(max_length=64)


class Paste(Pane):
    transactionId: UUID | None
    range: Range


class Cursor(Pane):
    lineNumber: int = Field(ge=1, strict=True)
    column: int = Field(ge=1, strict=True)
    source: str = Field(max_length=100)


class Selection(Pane):
    selections: list[Range] = Field(max_length=10_000)
    source: str = Field(max_length=100)


class Active(Pane):
    previousFileId: UUID | None


class Split(Strict):
    enabled: bool
    ratio: float = Field(ge=0, le=100)


class Create(Strict):
    node: Node


class Rename(Strict):
    name: str = Field(min_length=1, max_length=255)


class Move(Strict):
    parentId: UUID | None


class Delete(Strict):
    deletedIds: list[UUID] = Field(min_length=1, max_length=5000)


class Reconcile(Strict):
    reason: str = Field(max_length=200)
    nodes: dict[str, Node] = Field(max_length=5000)


class End(Strict):
    reason: str = Field(max_length=200)
    interrupted: bool


class ExecutionCorrelation(Strict):
    jobId: UUID
    snapshotId: UUID
    sourceHash: str = Field(pattern=r'^[0-9a-f]{64}$')
    configurationId: UUID
    language: Literal['cpp17', 'cpp20', 'python3', 'java17']
    status: str = Field(max_length=40)
    serverTimestamp: ISOTime


class RunStart(Strict):
    runId: UUID
    language: str = Field(max_length=40)
    execution: ExecutionCorrelation | None = None


class RunFinish(Strict):
    runId: UUID
    exitCode: int | None
    durationMs: float = Field(ge=0)
    execution: ExecutionCorrelation | None = None


class CMSSubmissionObservation(Strict):
    intentId: UUID
    snapshotId: UUID
    taskId: str = Field(min_length=1, max_length=128)
    language: str = Field(min_length=1, max_length=128)
    submissionId: str | None = Field(default=None, max_length=128)
    receivedAt: ISOTime | None = None


class DebugStart(Strict):
    debugId: UUID


class DebugAction(DebugStart):
    action: Literal['step', 'continue', 'pause', 'breakpoint']


class DebugFinish(DebugStart):
    reason: str = Field(max_length=200)


class Envelope(Strict):
    schemaVersion: Literal[1]
    eventId: UUID
    sessionId: UUID
    workspaceId: UUID
    fileId: UUID | None
    sequence: int = Field(ge=1, strict=True)
    clientTimestamp: ISOTime
    monotonicOffsetMs: float = Field(ge=0)


DOCUMENT_TYPES = {'TEXT_INSERT', 'TEXT_DELETE', 'TEXT_REPLACE', 'DOCUMENT_CHANGE', 'UNDO', 'REDO'}
payloads = {name: Transaction for name in DOCUMENT_TYPES}
payloads.update({
    'KEY_DOWN': Key, 'KEY_UP': Key, 'PASTE': Paste,
    'COMPOSITION_START': Pane, 'COMPOSITION_END': Pane, 'EDITOR_FOCUS': Pane, 'EDITOR_BLUR': Pane,
    'CURSOR_MOVED': Cursor, 'SELECTION_CHANGED': Selection, 'ACTIVE_FILE_CHANGED': Active, 'TAB_SWITCHED': Active,
    'PAGE_VISIBLE': Strict, 'PAGE_HIDDEN': Strict, 'SPLIT_CHANGED': Split,
    'FILE_CREATED': Create, 'FOLDER_CREATED': Create, 'FILE_RENAMED': Rename, 'FOLDER_RENAMED': Rename,
    'FILE_MOVED': Move, 'FOLDER_MOVED': Move, 'FILE_DELETED': Delete, 'FOLDER_DELETED': Delete,
    'WORKSPACE_RECONCILED': Reconcile, 'SESSION_ENDED': End,
    'CMS_SUBMISSION_INTENT': CMSSubmissionObservation, 'CMS_SUBMISSION_ADMITTED': CMSSubmissionObservation, 'CMS_SUBMISSION_REJECTED': CMSSubmissionObservation,
    'RUN_STARTED': RunStart, 'RUN_FINISHED': RunFinish, 'DEBUG_STARTED': DebugStart, 'DEBUG_ACTION': DebugAction, 'DEBUG_FINISHED': DebugFinish,
})
Event = Annotated[Union[tuple(create_model(name + 'Event', __base__=Envelope, eventType=(Literal[name], ...), payload=(payload, ...)) for name, payload in payloads.items())], Field(discriminator='eventType')]


class Checkpoint(Strict):
    id: UUID
    sessionId: UUID
    sequence: int = Field(ge=0, strict=True)
    workspaceRevision: int = Field(ge=0, strict=True)
    nodes: dict[str, Node] = Field(max_length=5000)
    stateHash: str = Field(pattern=r'^[0-9a-f]{64}$')
    createdAt: ISOTime
    reason: str = Field(max_length=100)


class SessionCreate(Strict):
    id: UUID
    workspaceId: UUID
    startedAt: ISOTime
    initial: Checkpoint


class Batch(Strict):
    id: UUID
    sessionId: UUID
    events: list[Event] = Field(max_length=200)
    checkpoints: list[Checkpoint] = Field(max_length=200)
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')


class Chunk(Strict):
    sessionId: UUID
    digest: str = Field(pattern=r'^[0-9a-f]{64}$')
    index: int = Field(ge=0, le=1023, strict=True)
    total: int = Field(ge=1, le=1024, strict=True)
    data: str = Field(max_length=64_000)


Integrity = Literal['Complete', 'Missing Events', 'Revision Mismatch', 'Checkpoint Mismatch', 'Recording Interrupted', 'Invalid Event']


class Close(Strict):
    completedAt: ISOTime | None
    integrity: Integrity
    lastSequence: int = Field(ge=0, strict=True)
