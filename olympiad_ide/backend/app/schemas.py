import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Node(Schema):
    id: UUID
    parentId: UUID | None = None
    name: str = Field(min_length=1, max_length=255)
    type: Literal["file", "folder"]
    content: str | None = Field(default=None, max_length=2_000_000)
    language: Literal["cpp", "python", "java", "plaintext"] | None = None
    documentRevision: int = Field(default=1, ge=1)
    createdAt: datetime
    updatedAt: datetime

    @field_validator("name")
    @classmethod
    def safe_name(cls, value: str) -> str:
        if value.strip() != value or value in (".", "..") or any(c in value for c in ("/", "\\", "\x00")):
            raise ValueError("Invalid file name")
        return value

    @model_validator(mode="after")
    def content_type(self):
        if self.type == "file" and (self.content is None or self.language is None):
            raise ValueError("Files require content and language")
        if self.type == "folder" and (self.content is not None or self.language is not None):
            raise ValueError("Folders cannot contain text or a language")
        return self


class EditorSettings(Schema):
    theme: Literal["dark-modern", "light", "high-contrast"] = "dark-modern"
    fontSize: int = Field(default=14, ge=10, le=28)
    fontFamily: str = Field(default="monospace", max_length=300)
    tabSize: int = Field(default=4, ge=1, le=8)
    insertSpaces: bool = True
    wordWrap: Literal["on", "off"] = "off"
    minimap: bool = True
    autoClosingBrackets: Literal["always", "never"] = "always"
    lineNumbers: Literal["on", "off", "relative"] = "on"
    cursorStyle: Literal["line", "block", "underline"] = "line"
    autoSave: Literal["off", "afterDelay"] = "afterDelay"
    renderWhitespace: Literal["none", "selection", "all"] = "selection"


class EditorGroup(Schema):
    id: Literal["primary", "secondary"]
    tabIds: list[UUID] = Field(max_length=1000)
    activeFileId: UUID | None = None


class EditorGroups(Schema):
    primary: EditorGroup
    secondary: EditorGroup


class ViewState(Schema):
    lineNumber: int = Field(ge=1)
    column: int = Field(ge=1)
    scrollTop: float = Field(ge=0, allow_inf_nan=False)
    scrollLeft: float = Field(ge=0, allow_inf_nan=False)


class EditorSession(Schema):
    groups: EditorGroups | None = None
    expandedFolderIds: list[UUID] = Field(default_factory=list, max_length=1000)
    activeGroupId: Literal["primary", "secondary"] = "primary"
    splitEnabled: bool = False
    splitRatio: float = Field(default=50, ge=25, le=75)
    viewStates: dict[str, ViewState] = Field(default_factory=dict, max_length=2000)
    activeView: Literal["explorer", "search", "run", "history", "settings"] = "explorer"
    explorerVisible: bool = True
    explorerSize: float = Field(default=19, ge=14, le=36)
    bottomPanelVisible: bool = True
    bottomPanelSize: float = Field(default=25, ge=12, le=55)
    bottomPanelView: Literal["terminal", "problems", "tests"] = "terminal"
    zenMode: bool = False


class WorkspaceDocument(Schema):
    name: str = Field(min_length=1, max_length=200)
    nodes: dict[str, Node] = Field(default_factory=dict, max_length=1000)
    settings: EditorSettings = Field(default_factory=EditorSettings)
    editorState: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_tree(self):
        session = EditorSession.model_validate(self.editorState)
        self.editorState = session.model_dump(mode="json", exclude_unset=True)
        if self.editorState.get("groups", {}) is None:
            raise ValueError("Editor groups must be an object")
        siblings: set[tuple[str | None, str]] = set()
        for key, node in self.nodes.items():
            if key != str(node.id):
                raise ValueError("Node key must match its stable UUID")
            parent = str(node.parentId) if node.parentId else None
            if parent and (parent not in self.nodes or self.nodes[parent].type != "folder"):
                raise ValueError("Parent must be a live folder in this workspace")
            sibling = (parent, node.name.casefold())
            if sibling in siblings:
                raise ValueError("Sibling names must be unique")
            siblings.add(sibling)
            seen = {key}
            while parent:
                if parent in seen:
                    raise ValueError("Folder cycles are prohibited")
                seen.add(parent)
                ancestor = self.nodes[parent].parentId
                parent = str(ancestor) if ancestor else None
        if len(json.dumps(self.model_dump(mode="json")).encode()) > 8_000_000:
            raise ValueError("Workspace exceeds 8 MB")
        return self


class WorkspaceCreate(Schema):
    id: UUID
    document: WorkspaceDocument


class WorkspaceResponse(Schema):
    id: str
    ownerId: str
    revision: int
    createdAt: datetime
    updatedAt: datetime
    document: WorkspaceDocument


class SyncOperation(Schema):
    operationId: UUID
    workspaceId: UUID
    baseRevision: int = Field(ge=0)
    document: WorkspaceDocument


class SyncBatch(Schema):
    operations: list[SyncOperation] = Field(min_length=1, max_length=20)


class SyncAcknowledgement(Schema):
    operationId: str
    revision: int


class SyncResponse(Schema):
    acknowledgements: list[SyncAcknowledgement]


class WorkspacePatch(Schema):
    baseRevision: int = Field(ge=0)
    document: WorkspaceDocument
    operationId: UUID


class DeleteRequest(Schema):
    baseRevision: int = Field(ge=0)
