from typing import Annotated, Literal
from uuid import UUID
from pathlib import PurePosixPath
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .telemetry_schema import SourceText

Language = Literal['cpp17', 'cpp20', 'python3', 'java17']
Status = Literal['QUEUED', 'PREPARING', 'COMPILING', 'RUNNING', 'FINISHED', 'COMPILATION_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'OUTPUT_LIMIT_EXCEEDED', 'CANCELLED', 'INFRASTRUCTURE_ERROR']
TERMINAL = {'FINISHED', 'COMPILATION_ERROR', 'RUNTIME_ERROR', 'TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'OUTPUT_LIMIT_EXCEEDED', 'CANCELLED', 'INFRASTRUCTURE_ERROR'}


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class RunConfiguration(Strict):
    kind: Literal['configuration'] = 'configuration'
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    language: Language
    entryPoint: UUID
    includedFiles: list[UUID] = Field(min_length=1, max_length=100)
    compilerProfile: Literal['release'] = 'release'
    mainClass: str | None = Field(default=None, pattern=r'^[A-Za-z_$][\w$]*(\.[A-Za-z_$][\w$]*)*$', max_length=200)
    defaultTestId: UUID | None = None

    @model_validator(mode='after')
    def entry_included(self):
        if self.entryPoint not in self.includedFiles or len(set(self.includedFiles)) != len(self.includedFiles):
            raise ValueError('Entry must be included exactly once; duplicate IDs are forbidden')
        if self.language == 'java17' and not self.mainClass: raise ValueError('Java requires an explicit main class')
        return self


class TestCase(Strict):
    kind: Literal['test'] = 'test'
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    stdin: str = Field(max_length=262144)
    expectedStdout: str | None = Field(default=None, max_length=262144)


class ResourceMutation(Strict):
    operationId: UUID
    baseRevision: int = Field(ge=0, strict=True)
    value: Annotated[RunConfiguration | TestCase, Field(discriminator='kind')]
    deleted: bool = False


def safe_path(value):
    path = PurePosixPath(value)
    if not value or len(value) > 250 or '\\' in value or '\x00' in value or path.is_absolute() or str(path) != value or any(p in ('', '.', '..') or p.startswith('__ide_') for p in value.split('/')):
        raise ValueError('Unsafe/reserved source path')
    return value


class ManifestFile(Strict):
    id: UUID
    path: str
    _safe = field_validator('path')(safe_path)


class SourceFile(ManifestFile):
    content: SourceText


class ExecutionSubmit(Strict):
    id: UUID  # Idempotency key and durable job ID, chosen before network submission.
    workspaceId: UUID
    configuration: RunConfiguration
    files: list[SourceFile] = Field(min_length=1, max_length=100)
    sourceHash: str = Field(pattern=r'^[0-9a-f]{64}$')
    tests: list[TestCase] = Field(min_length=1, max_length=50)

    @model_validator(mode='after')
    def manifest(self):
        files = {f.id: f for f in self.files}
        if len(files) != len(self.files) or set(files) != set(self.configuration.includedFiles): raise ValueError('Manifest must match included file identities')
        if len({f.path for f in self.files}) != len(files): raise ValueError('Duplicate paths')
        if len({t.id for t in self.tests}) != len(self.tests): raise ValueError('Duplicate test IDs')
        # A file cannot also be an ancestor directory of another file.
        paths = {f.path for f in self.files}
        if any(str(parent) in paths for f in self.files for parent in PurePosixPath(f.path).parents): raise ValueError('File/directory collision')
        extension = {'cpp17': ('.cpp', '.cc', '.cxx'), 'cpp20': ('.cpp', '.cc', '.cxx'), 'python3': ('.py',), 'java17': ('.java',)}[self.configuration.language]
        if not files[self.configuration.entryPoint].path.endswith(extension): raise ValueError('Entry point does not match language')
        allowed = extension + (('.h', '.hpp', '.txt') if self.configuration.language.startswith('cpp') else ('.txt',))
        if any(not f.path.endswith(allowed) for f in self.files): raise ValueError('Unsupported source extension')
        if sum(len(f.content.encode('utf-8', errors='surrogatepass')) for f in self.files) > 4_000_000: raise ValueError('Source snapshot exceeds 4 MB')
        if sum(len(t.stdin.encode()) + len((t.expectedStdout or '').encode()) for t in self.tests) > 1_000_000: raise ValueError('Test batch input/expectations exceed 1 MB')
        # Toolchains consume UTF-8 source, so isolated surrogate code units are rejected, never silently replaced.
        for f in self.files:
            try: f.content.encode('utf-8')
            except UnicodeEncodeError: raise ValueError('Execution source must be valid Unicode/UTF-8')
        return self


class CaseResult(Strict):
    testId: UUID
    name: str
    status: Status
    stdout: str = Field(max_length=1_048_576)
    stderr: str = Field(max_length=1_048_576)
    expectedStdout: str | None = None
    verdict: Literal['Accepted', 'Wrong Answer', 'Not Compared', 'Not Executed']
    exitCode: int | None = None
    cpuTime: float | None = Field(default=None, ge=0)
    wallTime: float | None = Field(default=None, ge=0)
    peakMemoryKiB: int | None = Field(default=None, ge=0)


class JobResult(Strict):
    status: Status
    compilationOutput: str = Field(max_length=1_048_576)
    compilationSeconds: float | None = Field(default=None, ge=0)
    toolchainVersion: str = Field(max_length=500)
    cases: list[CaseResult] = Field(max_length=50)
    error: str | None = Field(default=None, max_length=2000)


class JobView(Strict):
    id: str
    workspaceId: str
    snapshotId: str
    sourceHash: str
    sourceManifest: list[ManifestFile]
    configuration: RunConfiguration
    status: Status
    createdAt: str
    startedAt: str | None
    completedAt: str | None
    cancelRequested: bool
    lastSequence: int
    result: JobResult | None
    tests: list[TestCase]


class JobEvent(Strict):
    sequence: int
    timestamp: str
    eventType: Literal['STATUS', 'OUTPUT', 'CASE_RESULT', 'RESULT']
    status: Status | None = None
    stream: Literal['compiler', 'stdout', 'stderr'] | None = None
    text: str | None = None
    case: CaseResult | None = None


class ResourceView(Strict):
    id: UUID
    workspaceId: UUID
    revision: int
    value: Annotated[RunConfiguration | TestCase, Field(discriminator='kind')]
    deleted: bool


class EventPage(Strict):
    events: list[JobEvent]
    nextAfter: int


class CapacityView(Strict):
    workers: int
    capacity: int
    queuedJobs: int
    activeJobs: int
    failedJobs: int
    cancellationCount: int
