"""
Dialogs: PermissionDialog and SetupDialog.
- PermissionDialog: asks user to allow/deny a tool call
- SetupDialog: configure API key, base URL, model, and MCP servers
"""
from __future__ import annotations

import asyncio
import os
import json
from typing import Callable, Awaitable

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch, DirectoryTree

from agent.config import AgentConfig, ModelProfile, PROVIDER_DEFAULTS, save_config
from agent.tools.base import PermissionResult


# ──────────────────────────────────────────────────────────────────────────────
# PermissionDialog
# ──────────────────────────────────────────────────────────────────────────────

class PermissionDialog(ModalScreen[str]):
    """
    Modal dialog asking the user to permit or deny a tool call.
    Returns a PermissionResult constant.
    """

    DEFAULT_CSS = """
    PermissionDialog {
        align: center middle;
    }
    PermissionDialog #dialog-box {
        width: 70;
        max-height: 30;
        background: $surface;
        border: thick $warning;
        padding: 1 2;
    }
    PermissionDialog #title {
        text-style: bold;
        color: $warning;
        margin-bottom: 1;
    }
    PermissionDialog #tool-name {
        color: $accent;
        text-style: bold;
        margin-bottom: 1;
    }
    PermissionDialog #description {
        color: $text;
        margin-bottom: 1;
    }
    PermissionDialog #params-scroll {
        height: auto;
        max-height: 10;
        border: round $text-muted;
        padding: 0 1;
        margin-bottom: 1;
    }
    PermissionDialog #params-label {
        color: $text-muted;
    }
    PermissionDialog #btn-row {
        height: 3;
        margin-top: 1;
    }
    PermissionDialog Button {
        margin-right: 1;
    }
    PermissionDialog #btn-allow-once {
        background: $success;
    }
    PermissionDialog #btn-allow-all {
        background: $accent;
    }
    PermissionDialog #btn-deny {
        background: $error;
    }
    """

    BINDINGS = [
        Binding("y", "allow_once", "Allow once"),
        Binding("a", "allow_all", "Allow all"),
        Binding("n", "deny", "Deny"),
        Binding("escape", "deny", "Deny"),
    ]

    def __init__(
        self,
        tool_name: str,
        description: str,
        params: dict,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._tool_name = tool_name
        self._description = description
        self._params = params

    def compose(self) -> ComposeResult:
        params_str = json.dumps(self._params, ensure_ascii=False, indent=2)
        with Vertical(id="dialog-box"):
            yield Label("  Permission Required", id="title")
            yield Label(f"Tool: {self._tool_name}", id="tool-name")
            yield Label(self._description, id="description")
            with ScrollableContainer(id="params-scroll"):
                yield Static(params_str, id="params-label")
            with Horizontal(id="btn-row"):
                yield Button("Allow Once (Y)", id="btn-allow-once", variant="success")
                yield Button("Allow All (A)", id="btn-allow-all", variant="primary")
                yield Button("Deny (N)", id="btn-deny", variant="error")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "btn-allow-once":
            self.dismiss(PermissionResult.ALLOW_ONCE)
        elif btn_id == "btn-allow-all":
            self.dismiss(PermissionResult.ALLOW_ALL)
        elif btn_id == "btn-deny":
            self.dismiss(PermissionResult.DENY)

    def action_allow_once(self) -> None:
        self.dismiss(PermissionResult.ALLOW_ONCE)

    def action_allow_all(self) -> None:
        self.dismiss(PermissionResult.ALLOW_ALL)

    def action_deny(self) -> None:
        self.dismiss(PermissionResult.DENY)


# ──────────────────────────────────────────────────────────────────────────────
# SetupDialog  (三标签: Model & API / MCP Servers / Context)
# ──────────────────────────────────────────────────────────────────────────────

class SetupDialog(ModalScreen[AgentConfig | None]):
    """
    Three-tab settings dialog:
      Tab 1 — Model & API  : provider, key, model, thinking, web search
      Tab 2 — MCP Servers  : list configured servers, add / delete / test
      Tab 3 — Context      : compression thresholds
    Bottom bar (docked): profile save + action buttons
    """

    DEFAULT_CSS = """
    SetupDialog {
        align: center middle;
    }
    SetupDialog #dialog-box {
        width: 114;
        height: 90%;
        background: $surface;
        border: thick $accent;
        padding: 0 0;
        layout: vertical;
    }
    SetupDialog #dialog-title {
        text-style: bold;
        color: $accent;
        padding: 1 2 0 2;
        width: 1fr;
        text-align: center;
        height: 2;
    }
    /* ---- tab bar ---- */
    SetupDialog #tab-bar {
        height: 3;
        padding: 0 2;
        background: $surface-darken-1;
    }
    SetupDialog .tab-btn {
        min-width: 20;
        height: 3;
        margin-right: 1;
        border: none;
        background: $surface-darken-1;
        color: $text-muted;
    }
    SetupDialog .tab-btn.-active {
        background: $accent;
        color: $background;
        text-style: bold;
    }
    /* ---- tab panels ---- */
    SetupDialog .tab-panel {
        display: none;
        width: 1fr;
        height: 1fr;
        padding: 0 2;
    }
    SetupDialog .tab-panel.-visible {
        display: block;
    }
    /* ---- shared field styles ---- */
    SetupDialog .section-label {
        text-style: bold;
        color: $accent;
        margin-top: 1;
        margin-bottom: 0;
        background: $surface-darken-1;
        padding: 0 1;
        width: 1fr;
    }
    SetupDialog .field-label {
        color: $text-muted;
        margin-top: 1;
        margin-bottom: 0;
    }
    SetupDialog Input {
        margin-bottom: 0;
        width: 100%;
    }
    /* ---- Model tab columns ---- */
    SetupDialog #columns {
        height: auto;
        width: 1fr;
    }
    SetupDialog #col-left {
        width: 1fr;
        height: auto;
        padding-right: 1;
        border-right: solid $accent-darken-2;
    }
    SetupDialog #col-right {
        width: 1fr;
        height: auto;
        padding-left: 1;
    }
    SetupDialog #profiles-btn-row {
        height: 3;
        margin-top: 1;
    }
    SetupDialog #thinking-switch-row {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    SetupDialog #thinking-switch-row Label {
        width: auto;
        margin-right: 1;
        content-align: left middle;
    }
    SetupDialog #search-switch-row {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    SetupDialog #search-switch-row Label {
        width: auto;
        margin-right: 1;
        content-align: left middle;
    }
    SetupDialog #temp-top-row {
        height: auto;
        margin-top: 0;
    }
    SetupDialog #temp-top-row > Vertical {
        width: 1fr;
        height: auto;
    }
    /* ---- MCP tab ---- */
    SetupDialog #mcp-list-box {
        height: 18;
        border: solid $panel;
        padding: 0 1;
        margin-bottom: 1;
    }
    SetupDialog .mcp-row {
        height: 3;
        align: left middle;
    }
    SetupDialog .mcp-name-lbl {
        width: 14;
        color: $text;
        content-align: left middle;
    }
    SetupDialog .mcp-type-lbl {
        width: 6;
        color: $text-muted;
        content-align: left middle;
    }
    SetupDialog .mcp-url-lbl {
        width: 1fr;
        color: $text-muted;
        content-align: left middle;
    }
    SetupDialog .mcp-status-lbl {
        width: 12;
        content-align: left middle;
    }
    SetupDialog .mcp-del-btn {
        min-width: 12;
        height: 3;
        border: none;
        background: $error;
        color: $background;
    }
    SetupDialog .mcp-connect-btn {
        min-width: 12;
        height: 3;
        border: none;
        background: $success;
        color: $background;
    }
    SetupDialog .mcp-disconnect-btn {
        min-width: 12;
        height: 3;
        border: none;
        background: $warning;
        color: $background;
    }
    SetupDialog .mcp-auto-on-btn {
        min-width: 13;
        height: 3;
        border: none;
        background: $accent;
        color: $background;
    }
    SetupDialog .mcp-auto-off-btn {
        min-width: 13;
        height: 3;
        border: none;
        background: $surface-darken-2;
        color: $text-muted;
    }
    SetupDialog #mcp-add-form {
        height: auto;
        border: solid $accent-darken-2;
        padding: 1 1;
        margin-top: 1;
    }
    SetupDialog #mcp-type-row {
        height: 3;
        align: left middle;
    }
    SetupDialog #mcp-name-input-row {
        height: 3;
        align: left middle;
    }
    SetupDialog #mcp-type-row Label {
        width: 8;
        color: $text-muted;
    }
    SetupDialog #mcp-name-input-row Label {
        width: 8;
        color: $text-muted;
    }
    SetupDialog #input-mcp-name {
        width: 1fr;
    }
    SetupDialog #mcp-transport-select {
        width: 14;
    }
    SetupDialog #mcp-form-rows {
        height: auto;
    }
    SetupDialog #mcp-tab-btns {
        height: 3;
        margin-top: 1;
    }
    SetupDialog #mcp-autoconn-row {
        height: 3;
        margin-top: 1;
        align: left middle;
    }
    SetupDialog #mcp-autoconn-row Label {
        width: auto;
        margin-right: 1;
        content-align: left middle;
    }
    /* ---- per-panel bottom action area ---- */
    SetupDialog .panel-actions {
        height: auto;
        border-top: solid $accent-darken-2;
        padding: 1 0 0 0;
        margin-top: 1;
    }
    SetupDialog #profile-name-row {
        height: auto;
        margin-top: 0;
        margin-bottom: 1;
    }
    SetupDialog #profile-name-row Label {
        width: auto;
        margin-right: 1;
        content-align: left middle;
        padding-top: 1;
    }
    SetupDialog #profile-name-row Input {
        width: 1fr;
    }
    SetupDialog .btn-row {
        height: 3;
    }
    SetupDialog Button {
        margin-right: 1;
    }
    SetupDialog .status-label {
        height: 1;
        margin-top: 0;
        margin-bottom: 0;
        width: 1fr;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+s", "save", "Save"),
    ]

    _PROVIDERS = [
        ("Anthropic (claude-3-x)",  "anthropic"),
        ("Aliyun Bailian (qwen)",    "aliyun"),
        ("MiniMax (M2.x)",           "minimax"),
        ("OpenAI-compatible",        "openai"),
    ]
    _AUTH_TYPES = [
        ("x-api-key  (Anthropic native)",            "x-api-key"),
        ("bearer     (OpenAI / MiniMax / Aliyun)",   "bearer"),
    ]
    _MCP_TYPES = [
        ("stdio", "stdio"),
        ("sse",   "sse"),
        ("http",  "http"),
        ("ws",    "ws"),
    ]

    def __init__(self, config: AgentConfig, mcp_manager=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config
        # MCPManager injected from app for live connect/disconnect in dialog
        self._mcp_manager = mcp_manager
        # Deep-copy so toggling autoconnect never mutates the live config object
        import copy
        self._mcp_entries: dict[str, dict] = copy.deepcopy(dict(config.mcp_servers))
        # connection statuses injected by app: name -> True/False/None
        self._mcp_status: dict[str, bool | None] = {}
        # track which tab is currently active for status label routing
        self._active_tab: str = "model"

    def set_mcp_status(self, statuses: dict[str, bool]) -> None:
        """Inject live connection statuses so the list rows show green/red."""
        self._mcp_status = dict(statuses)
        try:
            self._refresh_mcp_list()
        except Exception:
            pass

    # ── compose ───────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        cfg = self._config
        profiles = cfg.list_profiles()
        profile_opts = [(p.name, p.name) for p in profiles]
        has_profiles = bool(profile_opts)

        # Auto-apply active_profile so fields show the saved values on open,
        # without requiring the user to click Load manually.
        _display = cfg  # fallback: use live config as-is
        if cfg.active_profile:
            _active = next((p for p in profiles if p.name == cfg.active_profile), None)
            if _active is not None:
                _display = _active  # use profile values for initial field display
        with ScrollableContainer():
            with Vertical(id="dialog-box"):
                yield Label("⚙  WXJ Settings", id="dialog-title")

                # ── Tab bar ─────────────────────────────────────────────
                with Horizontal(id="tab-bar"):
                    yield Button("🤖 Model & API",   id="tab-btn-model",   classes="tab-btn -active")
                    yield Button("🔌 MCP Servers",   id="tab-btn-mcp",     classes="tab-btn")
                    yield Button("💡 Context",       id="tab-btn-context", classes="tab-btn")

                # ── Bottom bar (docked) ──────────────────────────────────────
                # (removed — each panel has its own action row)

                # ── Panel 1: Model & API ───────────────────────────────────
                with ScrollableContainer(id="panel-model", classes="tab-panel -visible"):
                    with Horizontal(id="columns"):
                        # LEFT: Profiles + Connection
                        with Vertical(id="col-left"):
                            yield Label("▌ Saved Profiles", classes="section-label")
                            with Vertical(id="profiles-row"):
                                yield Select(
                                    options=profile_opts if has_profiles
                                           else [("(no saved profiles)", "")],
                                    value=cfg.active_profile
                                          if cfg.active_profile in dict(profile_opts) else "",
                                    id="select-profile",
                                )
                            with Horizontal(id="profiles-btn-row"):
                                yield Button("Load",   id="btn-load-profile", variant="primary")
                                yield Button("Delete", id="btn-del-profile",  variant="error")

                            yield Label("▌ Connection", classes="section-label")
                            yield Label("Provider:", classes="field-label")
                            yield Select(
                                options=[(label, val) for label, val in self._PROVIDERS],
                                value=_display.provider, id="select-provider",
                            )
                            yield Label("API Key:", classes="field-label")
                            yield Input(value=_display.api_key, password=True,
                                        placeholder="Your API key", id="input-api-key")
                            yield Label("Base URL:", classes="field-label")
                            yield Input(value=_display.base_url,
                                        placeholder="https://api.anthropic.com", id="input-base-url")
                            yield Label("Model:", classes="field-label")
                            yield Input(value=_display.model,
                                        placeholder="claude-3-5-sonnet-20241022", id="input-model")
                            yield Label("Auth Type:", classes="field-label")
                            yield Select(
                                options=[(label, val) for label, val in self._AUTH_TYPES],
                                value=_display.auth_type, id="select-auth-type",
                            )

                        # RIGHT: Generation + Thinking + Search
                        with Vertical(id="col-right"):
                            yield Label("▌ Generation", classes="section-label")
                            yield Label("Max Tokens:", classes="field-label")
                            yield Input(value=str(_display.max_tokens), placeholder="8192",
                                        id="input-max-tokens")
                            with Horizontal(id="temp-top-row"):
                                with Vertical():
                                    yield Label("Temperature (blank=default):", classes="field-label")
                                    yield Input(
                                        value="" if _display.temperature < 0 else str(_display.temperature),
                                        placeholder="e.g. 0.7", id="input-temperature")
                                with Vertical():
                                    yield Label("Top-P (blank=default):", classes="field-label")
                                    yield Input(
                                        value="" if _display.top_p < 0 else str(_display.top_p),
                                        placeholder="e.g. 0.95", id="input-top-p")

                            yield Label("▌ Thinking / Reasoning", classes="section-label")
                            yield Label(
                                "Anthropic: native thinking param\n"
                                "Aliyun:    extra_body {enable_thinking, thinking_budget}\n"
                                "MiniMax:   top-level thinking {type, budget_tokens}",
                                classes="field-label",
                            )
                            with Horizontal(id="thinking-switch-row"):
                                yield Label("Enable Thinking:")
                                yield Switch(value=_display.enable_thinking, id="switch-thinking")
                            yield Label("Thinking Budget (tokens):", classes="field-label")
                            yield Input(value=str(_display.thinking_budget), placeholder="1024",
                                        id="input-thinking-budget")

                            yield Label("▌ Web Search", classes="section-label")
                            yield Label(
                                "Enable live web search per query (Aliyun Qwen only).\n"
                                "Note: increases response time significantly.",
                                classes="field-label",
                            )
                            with Horizontal(id="search-switch-row"):
                                yield Label("Enable Web Search:")
                                yield Switch(value=_display.enable_search, id="switch-search")

                    # Save as Profile row — only shown in Model & API tab
                    with Vertical(classes="panel-actions"):
                        with Horizontal(id="profile-name-row"):
                            yield Label("Save as Profile:")
                            yield Input(
                                value=cfg.active_profile or "",
                                placeholder="profile name  (leave blank to skip)",
                                id="input-profile-name",
                            )
                        yield Label("", classes="status-label", id="status-label-model")
                        with Horizontal(classes="btn-row"):
                            yield Button("💾 Save (Ctrl+S)",    id="btn-save",         variant="success")
                            yield Button("💾 Save + Profile",   id="btn-save-profile", variant="primary")
                            yield Button("✖ Cancel (Esc)",     id="btn-cancel-model",  variant="default")

                # ── Panel 2: MCP Servers ─────────────────────────────────
                with ScrollableContainer(id="panel-mcp", classes="tab-panel"):
                    yield Label("▌ Configured MCP Servers", classes="section-label")
                    yield Label(
                        "Servers are auto-connected on startup.  "
                        "[green]\u2713 ok[/green] / [red]\u2717 failed[/red] / [dim]-[/dim] = not yet tested.\n"
                        "  Tip: Use \u2018Test Connection\u2019 to verify before saving.",
                        classes="field-label",
                    )
                    # Current server list
                    with ScrollableContainer(id="mcp-list-box"):
                        yield Vertical(id="mcp-rows")

                    # Add-new form
                    yield Label("▌ Add New Server", classes="section-label")
                    with Vertical(id="mcp-add-form"):
                        with Horizontal(id="mcp-name-input-row"):
                            yield Label("Name:")
                            yield Input(placeholder="e.g. myserver", id="input-mcp-name")
                        with Horizontal(id="mcp-type-row"):
                            yield Label("Type:")
                            yield Select(
                                options=self._MCP_TYPES, value="stdio",
                                id="mcp-transport-select",
                            )
                        with Vertical(id="mcp-form-rows"):
                            # stdio fields
                            yield Label("Command (stdio):", classes="field-label", id="lbl-mcp-cmd")
                            yield Input(placeholder="python  or  npx", id="input-mcp-command")
                            yield Label("Args (space-separated):", classes="field-label", id="lbl-mcp-args")
                            yield Input(placeholder="server.py --port 8080", id="input-mcp-args")
                            # url-based fields (hidden by default)
                            yield Label("URL:", classes="field-label", id="lbl-mcp-url")
                            yield Input(placeholder="http://localhost:8765/sse", id="input-mcp-url")
                            yield Label("Headers JSON (optional):", classes="field-label", id="lbl-mcp-headers")
                            yield Input(placeholder='{"Authorization":"Bearer token"}',
                                        id="input-mcp-headers")
                        with Horizontal(id="mcp-tab-btns"):
                            yield Button("➕ Add Server",       id="mcp-form-add-btn",  variant="success")
                            yield Button("🔌 Test Connection",  id="mcp-form-test-btn", variant="primary")
                        with Horizontal(id="mcp-autoconn-row"):
                            yield Label("Auto-connect on startup:", classes="field-label", id="lbl-mcp-autoconn")
                            yield Switch(value=True, id="switch-mcp-autoconn")

                    # MCP panel actions
                    with Vertical(classes="panel-actions"):
                        yield Label("", classes="status-label", id="status-label-mcp")
                        with Horizontal(classes="btn-row"):
                            yield Button("💾 Save (Ctrl+S)", id="btn-save-mcp",    variant="success")
                            yield Button("✖ Cancel (Esc)",    id="btn-cancel-mcp",  variant="default")

                # ── Panel 3: Context / Memory ────────────────────────────
                with ScrollableContainer(id="panel-context", classes="tab-panel"):
                    yield Label("▌ Context Compression", classes="section-label")
                    yield Label(
                        "Summarize threshold: LLM compresses older messages every N turns.\n"
                        "Hard limit: force-truncate (must be > threshold).",
                        classes="field-label",
                    )
                    with Horizontal(id="ctx-compress-row"):
                        with Vertical():
                            yield Label("Summarize after (turns):", classes="field-label")
                            yield Input(
                                value=str(getattr(cfg, "compress_threshold", 10)),
                                placeholder="10", id="input-compress-threshold")
                        with Vertical():
                            yield Label("Hard limit (msgs):", classes="field-label")
                            yield Input(
                                value=str(getattr(cfg, "hard_limit", 20)),
                                placeholder="20", id="input-hard-limit")

                    # Context panel actions
                    with Vertical(classes="panel-actions"):
                        yield Label("", classes="status-label", id="status-label-context")
                        with Horizontal(classes="btn-row"):
                            yield Button("💾 Save (Ctrl+S)", id="btn-save-context",    variant="success")
                            yield Button("✖ Cancel (Esc)",    id="btn-cancel-context",  variant="default")

    # ── on_mount ───────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self._refresh_mcp_list()
        self._refresh_mcp_form_fields("stdio")
        # All panels except panel-model start hidden
        for t in ("mcp", "context"):
            try:
                self.query_one(f"#panel-{t}").display = False
            except Exception:
                pass

    # ── MCP list rendering ──────────────────────────────────────────────────

    def _refresh_mcp_list(self) -> None:
        try:
            container = self.query_one("#mcp-rows", Vertical)
        except Exception:
            return
        container.remove_children()
        if not self._mcp_entries:
            container.mount(Label("  (no MCP servers configured)", classes="field-label"))
            return
        for srv_name, raw in self._mcp_entries.items():
            status = self._mcp_status.get(srv_name)  # True / False / None
            if status is True:
                status_markup = "[green]\u2713 on[/green]"
            elif status is False:
                status_markup = "[red]\u2717 err[/red]"
            else:
                status_markup = "[dim]\u25cb off[/dim]"
            t = raw.get("type", "stdio")
            if t == "stdio":
                detail = (raw.get("command", "") + " " + " ".join(raw.get("args", []))).strip()
            else:
                detail = raw.get("url", "")
            detail = detail[:32]
            # autoconnect toggle button
            autoconn = raw.get("autoconnect", True)
            btn_auto = Button(
                "\U0001f504 Auto: ON" if autoconn else "\u23f8 Auto: OFF",
                id=f"mcp-auto-{srv_name}",
                classes="mcp-auto-on-btn" if autoconn else "mcp-auto-off-btn",
            )
            # connect/disconnect buttons
            is_connected = (status is True)
            btn_connect    = Button("\u26a1 Connect",    id=f"mcp-connect-{srv_name}",    classes="mcp-connect-btn")
            btn_disconnect = Button("\u23cf Disconnect", id=f"mcp-disconnect-{srv_name}", classes="mcp-disconnect-btn")
            btn_delete     = Button("\U0001f5d1 Delete",  id=f"mcp-del-{srv_name}",        classes="mcp-del-btn")
            btn_connect.display    = not is_connected
            btn_disconnect.display = is_connected
            row = Horizontal(
                Label(f"[cyan]{srv_name}[/cyan]", classes="mcp-name-lbl"),
                Label(f"[dim]{t}[/dim]",          classes="mcp-type-lbl"),
                Label(detail,                      classes="mcp-url-lbl"),
                Label(status_markup,               classes="mcp-status-lbl"),
                btn_auto,
                btn_connect,
                btn_disconnect,
                btn_delete,
                classes="mcp-row",
            )
            container.mount(row)

    def _refresh_mcp_form_fields(self, transport: str) -> None:
        is_stdio = transport == "stdio"
        for wid in ("lbl-mcp-cmd", "input-mcp-command", "lbl-mcp-args", "input-mcp-args"):
            try:
                self.query_one(f"#{wid}").display = is_stdio
            except Exception:
                pass
        for wid in ("lbl-mcp-url", "input-mcp-url", "lbl-mcp-headers", "input-mcp-headers"):
            try:
                self.query_one(f"#{wid}").display = not is_stdio
            except Exception:
                pass

    # ── Tab switching ────────────────────────────────────────────────────────

    def _switch_tab(self, tab: str) -> None:
        self._active_tab = tab
        for t in ("model", "mcp", "context"):
            try:
                btn   = self.query_one(f"#tab-btn-{t}", Button)
                panel = self.query_one(f"#panel-{t}")
                active = (t == tab)
                if active:
                    btn.add_class("-active")
                    panel.display = True
                else:
                    btn.remove_class("-active")
                    panel.display = False
            except Exception:
                pass

    # ── Event handlers ───────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id or ""

        # Tab navigation
        if bid in ("tab-btn-model", "tab-btn-mcp", "tab-btn-context"):
            self._switch_tab(bid.replace("tab-btn-", ""))
            return

        # Bottom bar
        if bid == "btn-save":
            self.action_save()
        elif bid == "btn-save-profile":
            self._action_save_profile()
        elif bid in ("btn-cancel-model", "btn-cancel-mcp", "btn-cancel-context"):
            self.dismiss(None)
        elif bid == "btn-load-profile":
            self._load_selected_profile()
        elif bid == "btn-del-profile":
            self._delete_selected_profile()

        # MCP / Context panel save
        elif bid == "btn-save-mcp":
            self._save_mcp_only()
        elif bid == "btn-save-context":
            self._save_context_only()

        # MCP delete
        elif bid.startswith("mcp-del-"):
            srv_name = bid[len("mcp-del-"):]
            self._mcp_entries.pop(srv_name, None)
            self._mcp_status.pop(srv_name, None)
            self._refresh_mcp_list()
            self._show_info(f"Removed '{srv_name}' (save to persist).")

        # MCP autoconnect toggle
        elif bid.startswith("mcp-auto-"):
            srv_name = bid[len("mcp-auto-"):]
            if srv_name in self._mcp_entries:
                current = self._mcp_entries[srv_name].get("autoconnect", True)
                self._mcp_entries[srv_name]["autoconnect"] = not current
                self._refresh_mcp_list()
                state = "ON" if not current else "OFF"
                self._show_info(f"'{srv_name}' autoconnect set to {state}. Save to persist.")

        # MCP connect (live, via injected manager)
        elif bid.startswith("mcp-connect-"):
            srv_name = bid[len("mcp-connect-"):]
            self.run_worker(self._do_connect(srv_name), thread=False)

        # MCP disconnect (live, via injected manager)
        elif bid.startswith("mcp-disconnect-"):
            srv_name = bid[len("mcp-disconnect-"):]
            self.run_worker(self._do_disconnect(srv_name), thread=False)

        # MCP add
        elif bid == "mcp-form-add-btn":
            self._mcp_add_from_form(test_first=False)

        # MCP test + add
        elif bid == "mcp-form-test-btn":
            self._mcp_add_from_form(test_first=True)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "select-provider":
            provider = str(event.value)
            defaults = PROVIDER_DEFAULTS.get(provider, {})
            if not defaults:
                return
            try:
                self.query_one("#input-base-url",   Input).value  = defaults.get("base_url", "")
                self.query_one("#select-auth-type", Select).value = defaults.get("auth_type", "bearer")
                self.query_one("#input-model",      Input).value  = defaults.get("model", "")
            except Exception:
                pass
        elif event.select.id == "mcp-transport-select":
            self._refresh_mcp_form_fields(str(event.value))

    # ── MCP add / test helpers ───────────────────────────────────────────────

    def _mcp_add_from_form(self, test_first: bool = False) -> None:
        try:
            name      = self.query_one("#input-mcp-name", Input).value.strip()
            transport = str(self.query_one("#mcp-transport-select", Select).value)
        except Exception as e:
            self._show_error(f"Form error: {e}"); return

        if not name:
            self._show_error("Server name is required."); return
        if name in self._mcp_entries:
            self._show_error(f"'{name}' already exists. Delete it first."); return

        raw: dict = {"type": transport}
        if transport == "stdio":
            cmd = self.query_one("#input-mcp-command", Input).value.strip()
            if not cmd:
                self._show_error("Command is required for stdio."); return
            raw["command"] = cmd
            args_str = self.query_one("#input-mcp-args", Input).value.strip()
            if args_str:
                raw["args"] = args_str.split()
        else:
            url = self.query_one("#input-mcp-url", Input).value.strip()
            if not url:
                self._show_error("URL is required for sse/http/ws."); return
            raw["url"] = url
            headers_str = self.query_one("#input-mcp-headers", Input).value.strip()
            if headers_str:
                try:
                    raw["headers"] = json.loads(headers_str)
                except json.JSONDecodeError:
                    self._show_error("Headers must be valid JSON."); return
        # Read autoconnect switch (default True)
        try:
            raw["autoconnect"] = self.query_one("#switch-mcp-autoconn", Switch).value
        except Exception:
            raw["autoconnect"] = True

        if test_first:
            self._show_info(f"Testing '{name}'...")
            self.run_worker(self._test_mcp_connection(name, raw), thread=False)
        else:
            self._mcp_entries[name] = raw
            self._refresh_mcp_list()
            self._clear_mcp_form()
            self._show_info(f"Added '{name}'. Click Save to persist.")

    async def _test_mcp_connection(self, name: str, raw: dict) -> None:
        import asyncio
        from agent.mcp_client import MCPClient, parse_mcp_config
        error_msg: str | None = None
        client: MCPClient | None = None
        try:
            cfg = parse_mcp_config(name, raw)
            client = MCPClient(name, cfg)
            # 10-second timeout to avoid hanging on unreachable servers
            await asyncio.wait_for(client.connect(), timeout=10.0)
            tool_count = len(client._tools)
            await client.disconnect()
            self._mcp_entries[name] = raw
            self._mcp_status[name] = True
            self._refresh_mcp_list()
            self._clear_mcp_form()
            self._show_info(
                f"[green]\u2713[/green] Connected! {tool_count} tool(s). Added '{name}'. Click Save."
            )
            return
        except asyncio.TimeoutError:
            error_msg = "Connection timed out (10s). Is the server running?"
        except BaseException as exc:
            # Unwrap ExceptionGroup (anyio TaskGroup used by SSE/HTTP transports)
            if isinstance(exc, BaseExceptionGroup):
                first = exc.exceptions[0] if exc.exceptions else exc
                error_msg = str(first)
            else:
                error_msg = str(exc)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass
        self._mcp_status[name] = False
        self._show_error(f"\u2717 Failed for '{name}': {error_msg}")

    def _clear_mcp_form(self) -> None:
        for wid in ("#input-mcp-name", "#input-mcp-command",
                    "#input-mcp-args", "#input-mcp-url", "#input-mcp-headers"):
            try:
                self.query_one(wid, Input).value = ""
            except Exception:
                pass

    # ── Live connect / disconnect helpers (require injected _mcp_manager) ─────

    async def _do_connect(self, srv_name: str) -> None:
        """Attempt live connection to an existing entry via the injected MCPManager."""
        if self._mcp_manager is None:
            self._show_error("MCPManager not available. Save and restart to connect.")
            return
        raw = self._mcp_entries.get(srv_name)
        if raw is None:
            self._show_error(f"Server '{srv_name}' not found in entries."); return
        self._show_info(f"Connecting to '{srv_name}'...")
        import asyncio
        error_msg: str | None = None
        try:
            await asyncio.wait_for(
                self._mcp_manager.connect_server_from_raw(srv_name, raw), timeout=10.0
            )
            client = self._mcp_manager._clients.get(srv_name)
            tc = len(client._tools) if client else 0
            self._mcp_status[srv_name] = True
            self._refresh_mcp_list()
            self._show_info(f"[green]\u2713[/green] '{srv_name}' connected ({tc} tool(s)).")
            return
        except asyncio.TimeoutError:
            error_msg = "timed out (10s)"
        except BaseException as exc:
            if isinstance(exc, BaseExceptionGroup):
                error_msg = str(exc.exceptions[0] if exc.exceptions else exc)
            else:
                error_msg = str(exc)
        self._mcp_status[srv_name] = False
        self._refresh_mcp_list()
        self._show_error(f"\u2717 Failed to connect '{srv_name}': {error_msg}")

    async def _do_disconnect(self, srv_name: str) -> None:
        """Disconnect a live server via the injected MCPManager."""
        if self._mcp_manager is None:
            self._show_error("MCPManager not available.")
            return
        try:
            await self._mcp_manager.disconnect_server(srv_name)
            self._mcp_status[srv_name] = None
            self._refresh_mcp_list()
            self._show_info(f"[yellow]\u23cf[/yellow] '{srv_name}' disconnected.")
        except Exception as e:
            self._show_error(f"Error disconnecting '{srv_name}': {e}")

    # ── Profile actions ───────────────────────────────────────────────────

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_save(self) -> None:
        cfg = self._collect_form()
        if cfg is None:
            return
        save_config(cfg)
        self.dismiss(cfg)

    def _action_save_profile(self) -> None:
        cfg = self._collect_form()
        if cfg is None:
            return
        profile_name = self.query_one("#input-profile-name", Input).value.strip()
        if not profile_name:
            self._show_error("Profile Name is required for 'Save + Profile'."); return
        profile = cfg.to_profile()
        profile.name = profile_name
        cfg.active_profile = profile_name
        cfg.save_profile(profile)
        save_config(cfg)
        self.dismiss(cfg)

    def _load_selected_profile(self) -> None:
        sel = self.query_one("#select-profile", Select)
        if sel.value is Select.BLANK or not sel.value:
            self._show_error("No profile selected."); return
        name = str(sel.value)
        profiles = self._config.list_profiles()
        profile = next((p for p in profiles if p.name == name), None)
        if profile is None:
            self._show_error(f"Profile '{name}' not found."); return
        try:
            self.query_one("#select-provider",      Select).value = profile.provider
            self.query_one("#input-api-key",         Input).value  = profile.api_key
            self.query_one("#input-base-url",        Input).value  = profile.base_url
            self.query_one("#input-model",           Input).value  = profile.model
            self.query_one("#select-auth-type",      Select).value = profile.auth_type
            self.query_one("#input-max-tokens",      Input).value  = str(profile.max_tokens)
            self.query_one("#input-temperature",     Input).value  = (
                "" if profile.temperature < 0 else str(profile.temperature))
            self.query_one("#input-top-p",           Input).value  = (
                "" if profile.top_p < 0 else str(profile.top_p))
            self.query_one("#switch-thinking",       Switch).value = profile.enable_thinking
            self.query_one("#input-thinking-budget", Input).value  = str(profile.thinking_budget)
            self.query_one("#switch-search",         Switch).value = profile.enable_search
            self.query_one("#input-profile-name",    Input).value  = profile.name
            self._show_info(f"Profile '{name}' loaded — click Save to apply.")
        except Exception as e:
            self._show_error(f"Load error: {e}")

    def _delete_selected_profile(self) -> None:
        sel = self.query_one("#select-profile", Select)
        if sel.value is Select.BLANK or not sel.value:
            self._show_error("No profile selected. Pick one from the dropdown first.")
            return
        name = str(sel.value)
        self._config.delete_profile(name)
        save_config(self._config)

        # Immediately refresh the dropdown — no need to reopen settings
        profiles = self._config.list_profiles()
        profile_opts = [(p.name, p.name) for p in profiles]
        if profile_opts:
            sel.set_options(profile_opts)
            sel.value = profile_opts[0][1]  # select first remaining
        else:
            sel.set_options([("(no saved profiles)", "")])
            sel.clear()
        self._show_info(f"Profile '{name}' deleted.")

    # ── Form collection ───────────────────────────────────────────────────

    def _collect_form(self) -> AgentConfig | None:
        try:
            api_key   = self.query_one("#input-api-key",  Input).value.strip()
            base_url  = self.query_one("#input-base-url", Input).value.strip()
            model     = self.query_one("#input-model",    Input).value.strip()
            auth_type = str(self.query_one("#select-auth-type", Select).value)
            provider  = str(self.query_one("#select-provider",  Select).value)
            max_tokens_str      = self.query_one("#input-max-tokens",      Input).value.strip()
            temp_str            = self.query_one("#input-temperature",     Input).value.strip()
            top_p_str           = self.query_one("#input-top-p",           Input).value.strip()
            thinking_budget_str = self.query_one("#input-thinking-budget", Input).value.strip()
            enable_thinking     = self.query_one("#switch-thinking",       Switch).value
            enable_search       = self.query_one("#switch-search",         Switch).value
            compress_thresh_str = self.query_one("#input-compress-threshold", Input).value.strip()
            hard_limit_str      = self.query_one("#input-hard-limit",         Input).value.strip()

            if not api_key:   self._show_error("API Key is required.");  return None
            if not base_url:  self._show_error("Base URL is required."); return None
            if not model:     self._show_error("Model is required.");    return None

            try:
                max_tokens = int(max_tokens_str) if max_tokens_str else 8192
            except ValueError:
                self._show_error("Max Tokens must be an integer."); return None
            try:
                temperature = float(temp_str) if temp_str else -1.0
            except ValueError:
                self._show_error("Temperature must be a number."); return None
            try:
                top_p = float(top_p_str) if top_p_str else -1.0
            except ValueError:
                self._show_error("Top-P must be a number."); return None
            try:
                thinking_budget = int(thinking_budget_str) if thinking_budget_str else 1024
            except ValueError:
                self._show_error("Thinking Budget must be an integer."); return None
            try:
                compress_threshold = int(compress_thresh_str) if compress_thresh_str else 10
                if compress_threshold < 1: raise ValueError
            except ValueError:
                self._show_error("Summarize threshold must be a positive integer."); return None
            try:
                hard_limit = int(hard_limit_str) if hard_limit_str else 20
                if hard_limit <= compress_threshold:
                    self._show_error("Hard limit must be > compress threshold."); return None
            except ValueError:
                self._show_error("Hard limit must be a positive integer."); return None

            cfg = self._config
            cfg.api_key            = api_key
            cfg.base_url           = base_url
            cfg.model              = model
            cfg.auth_type          = auth_type    # type: ignore
            cfg.provider           = provider     # type: ignore
            cfg.max_tokens         = max_tokens
            cfg.temperature        = temperature
            cfg.top_p              = top_p
            cfg.enable_thinking    = enable_thinking
            cfg.thinking_budget    = thinking_budget
            cfg.enable_search      = enable_search
            cfg.compress_threshold = compress_threshold
            cfg.hard_limit         = hard_limit
            # Persist MCP servers from dialog state
            cfg.mcp_servers        = dict(self._mcp_entries)
            return cfg

        except Exception as e:
            self._show_error(f"Error: {e}")
            return None

    def _show_error(self, message: str) -> None:
        label_id = f"#status-label-{self._active_tab}"
        try:
            self.query_one(label_id, Label).update(f"[red]{message}[/red]")
        except Exception:
            pass

    def _show_info(self, message: str) -> None:
        label_id = f"#status-label-{self._active_tab}"
        try:
            self.query_one(label_id, Label).update(f"[green]{message}[/green]")
        except Exception:
            pass

    # ── Panel-specific save helpers ─────────────────────────────────

    def _save_mcp_only(self) -> None:
        """Save only MCP server changes (no model field validation)."""
        self._config.mcp_servers = dict(self._mcp_entries)
        save_config(self._config)
        self.dismiss(self._config)

    def _save_context_only(self) -> None:
        """Save only context compression settings."""
        try:
            compress_thresh_str = self.query_one("#input-compress-threshold", Input).value.strip()
            hard_limit_str      = self.query_one("#input-hard-limit",         Input).value.strip()
            compress_threshold  = int(compress_thresh_str) if compress_thresh_str else 10
            hard_limit          = int(hard_limit_str)      if hard_limit_str      else 20
            if compress_threshold < 1:
                self._show_error("Summarize threshold must be ≥ 1."); return
            if hard_limit <= compress_threshold:
                self._show_error("Hard limit must be > compress threshold."); return
        except ValueError:
            self._show_error("Threshold values must be integers."); return
        self._config.compress_threshold = compress_threshold
        self._config.hard_limit         = hard_limit
        save_config(self._config)
        self.dismiss(self._config)


# ──────────────────────────────────────────────────────────────────────────────
# HelpDialog
# ──────────────────────────────────────────────────────────────────────────────

_HELP_TEXT = """
# Python TUI Agent — Help

## Slash Commands
| Command     | Description                        |
|-------------|------------------------------------|
| /help       | Show this help dialog              |
| /clear      | Clear conversation history         |
| /setup      | Configure API key and model        |
| /plan       | Toggle Plan Mode task panel        |
| /history    | Show session history               |
| /abort      | Abort the current request          |
| /stop       | Stop run & save resume point       |
| /resume     | Resume from last stop point        |
| /logo       | Cycle logo style (instant, themed)  |
| /newdaily   | Refresh daily.md via LLM (news)    |
| /exit       | Exit the application               |

## Keyboard Shortcuts
| Shortcut    | Action                             |
|-------------|------------------------------------|
| Enter       | Submit message                     |
| Shift+Enter | Insert newline                     |
| Tab         | Cycle slash-command completions    |
| Ctrl+S      | Open settings                      |
| Ctrl+P      | Toggle Plan Mode                   |
| Ctrl+L      | Clear screen                       |
| Ctrl+T      | Toggle theme (dark/light)          |
| Ctrl+H      | Show this help                     |
| Ctrl+C      | Abort current request              |
| Ctrl+Q      | Quit                               |

## Tools Available
| Tool  | Description                        |
|-------|------------------------------------|
| Bash  | Execute shell commands             |
| Read  | Read file contents                 |
| Write | Create/overwrite files             |
| Edit  | Precise str_replace file editing   |
| Glob  | Find files by pattern              |
| Grep  | Search file contents by regex      |
""".strip()


class HelpDialog(ModalScreen[None]):
    """Modal dialog showing help text."""

    DEFAULT_CSS = """
    HelpDialog {
        align: center middle;
    }
    HelpDialog #dialog-box {
        width: 80;
        height: 40;
        background: $surface;
        border: thick $accent;
        padding: 1 2;
    }
    HelpDialog ScrollableContainer {
        height: 1fr;
    }
    HelpDialog #btn-close {
        margin-top: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        from rich.markdown import Markdown as RichMarkdown
        with Vertical(id="dialog-box"):
            with ScrollableContainer():
                yield Static(RichMarkdown(_HELP_TEXT))
            yield Button("Close (Esc)", id="btn-close", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)


# ──────────────────────────────────────────────────────────────────────────────
# DirectoryDialog
# ──────────────────────────────────────────────────────────────────────────────

class DirectoryDialog(ModalScreen[str | None]):
    """
    Modal directory picker using Textual's built-in DirectoryTree.
    - Type a path + Enter to jump anywhere (any drive letter / absolute path).
    - Tab in path input to cycle through matching sub-directories.
    - Up/Down arrow keys to pick from Tab completions.
    - Click a directory in the tree to select it.
    - "^ Parent" button to navigate up one level.
    - Press Open / Enter to confirm, Cancel / Esc to abort.
    """

    DEFAULT_CSS = """
    DirectoryDialog {
        align: center middle;
    }
    DirectoryDialog #dir-box {
        width: 90;
        height: 38;
        background: $surface;
        border: thick $accent;
        padding: 0 1;
    }
    DirectoryDialog #dir-title {
        text-style: bold;
        color: $accent;
        padding: 1 0 0 0;
        height: 2;
    }
    DirectoryDialog #dir-path-row {
        height: 3;
        align: left middle;
    }
    DirectoryDialog #dir-path-label {
        width: 7;
        color: $text-muted;
    }
    DirectoryDialog #dir-path-input {
        width: 1fr;
    }
    DirectoryDialog #dir-nav-row {
        height: 2;
        align: left middle;
    }
    DirectoryDialog #btn-parent {
        min-width: 12;
        height: 1;
        border: none;
        background: $panel;
        color: $accent;
    }
    DirectoryDialog #dir-tab-hints {
        color: $text-muted;
        padding-left: 1;
        height: 1;
        width: 1fr;
    }
    DirectoryDialog DirectoryTree {
        height: 1fr;
        border: solid $panel;
    }
    DirectoryDialog #drive-list {
        height: 1fr;
        border: solid $panel;
        padding: 0 1;
    }
    DirectoryDialog .drive-btn {
        width: 1fr;
        height: 3;
        margin-bottom: 0;
    }
    DirectoryDialog #dir-selected {
        height: 1;
        padding: 0;
    }
    DirectoryDialog #dir-btn-row {
        height: 3;
        align: right middle;
        padding-top: 1;
    }
    DirectoryDialog #btn-cd-ok {
        margin-left: 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(self, start_path: str = ".") -> None:
        super().__init__()
        from pathlib import Path
        self._start = str(Path(os.path.expanduser(start_path)).resolve())
        self._chosen: str = self._start
        # Tab-completion state
        self._tab_matches: list[str] = []
        self._tab_idx: int = -1
        self._applying_tab: bool = False  # guard: suppress on_input_changed during tab-fill
        self._drives_mode: bool = False   # True when showing the drive-list view

    # ── Drive listing helpers ─────────────────────────────────────────────

    @staticmethod
    def _list_drives() -> list[str]:
        """Return available drive roots on Windows (C:\\, D:\\, …), or ["/"] on Unix."""
        import sys
        if sys.platform == "win32":
            import string
            from pathlib import Path
            return [
                f"{d}:\\"
                for d in string.ascii_uppercase
                if Path(f"{d}:\\").exists()
            ]
        else:
            return ["/"]

    def _show_drives(self) -> None:
        """Switch the tree area to a drive-picker view."""
        self._drives_mode = True
        self._update_path_input("[drives]")
        self._update_hint("  Click a drive to enter it")
        self._update_selected("[bold cyan]Select a drive[/bold cyan]")
        # Swap DirectoryTree for a drive button list
        try:
            tree = self.query_one("#dir-tree", DirectoryTree)
            tree.display = False
        except Exception:
            pass
        # Remove old drive list if any
        try:
            self.query_one("#drive-list").remove()
        except Exception:
            pass
        drives = self._list_drives()
        drive_box = Vertical(id="drive-list")
        try:
            selected_label = self.query_one("#dir-selected", Label)
            self.query_one("#dir-box", Vertical).mount(drive_box, before=selected_label)
        except Exception:
            return
        for drv in drives:
            drive_box.mount(Button(f"🗂  {drv}", id=f"drv-{drv[0]}", classes="drive-btn"))

    def _hide_drives(self) -> None:
        """Remove the drive-picker view and restore the DirectoryTree."""
        self._drives_mode = False
        try:
            self.query_one("#drive-list").remove()
        except Exception:
            pass
        try:
            self.query_one("#dir-tree", DirectoryTree).display = True
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Vertical(id="dir-box"):
            yield Label("▣ Select Working Directory", id="dir-title")
            # Path input row
            with Horizontal(id="dir-path-row"):
                yield Label("Path: ", id="dir-path-label")
                yield Input(
                    value=self._start,
                    placeholder="Type path + Enter to jump. Tab to complete.",
                    id="dir-path-input",
                )
            # Navigation row: parent button + tab hint
            with Horizontal(id="dir-nav-row"):
                yield Button("↑ Parent", id="btn-parent")
                yield Label("  Tab: complete path  ↑↓: pick match", id="dir-tab-hints")
            yield DirectoryTree(self._start, id="dir-tree")
            yield Label(f"[green]{self._start}[/green]", id="dir-selected")
            with Horizontal(id="dir-btn-row"):
                yield Button("Cancel", id="btn-cd-cancel", variant="default")
                yield Button("Open", id="btn-cd-ok", variant="primary")

    def on_mount(self) -> None:
        self.query_one("#dir-path-input", Input).focus()

    # ── Internal helpers ─────────────────────────────────────────────────

    def _navigate_to(self, path: str, update_input: bool = True) -> None:
        """Jump the tree and state to a new directory path."""
        from pathlib import Path
        target = Path(os.path.expanduser(path)).resolve()
        if not target.is_dir():
            self._update_selected(f"[red]Not a directory: {path}[/red]")
            return
        self._chosen = str(target)
        self._tab_matches = []
        self._tab_idx = -1
        if update_input:
            self._update_path_input(self._chosen)
        self._reload_tree(self._chosen)
        self._update_selected(f"[green]{self._chosen}[/green]")
        self._update_hint("  Tab: complete path  ↑↓: pick match")

    def _reload_tree(self, path: str) -> None:
        """Update the DirectoryTree to show a new root path.
        DirectoryTree.path is a reactive — assigning it reloads the tree in-place.
        """
        try:
            tree = self.query_one("#dir-tree", DirectoryTree)
            from pathlib import Path as _P
            tree.path = _P(path)
        except Exception:
            pass

    def _update_selected(self, markup: str) -> None:
        try:
            self.query_one("#dir-selected", Label).update(markup)
        except Exception:
            pass

    def _update_path_input(self, value: str) -> None:
        try:
            self._applying_tab = True
            self.query_one("#dir-path-input", Input).value = value
            # Clear flag AFTER the Changed event fires (next frame)
            self.call_after_refresh(self._clear_applying_tab)
        except Exception:
            self._applying_tab = False

    def _clear_applying_tab(self) -> None:
        self._applying_tab = False

    def _update_hint(self, text: str) -> None:
        try:
            self.query_one("#dir-tab-hints", Label).update(text)
        except Exception:
            pass

    @staticmethod
    def _fs_matches(partial: str) -> list[str]:
        """Return sub-directories matching the given partial path prefix."""
        from pathlib import Path
        partial = os.path.expanduser(partial)
        if not partial:
            base = Path.cwd()
            prefix = ""
        else:
            p = Path(partial)
            if partial.endswith((os.sep, "/")):
                base = p if p.is_dir() else p.parent
                prefix = ""
            else:
                base = p.parent
                prefix = p.name.lower()
        try:
            return [
                str(d) + os.sep
                for d in sorted(base.iterdir())
                if d.is_dir() and d.name.lower().startswith(prefix)
                and not d.name.startswith(".")
            ][:14]
        except (PermissionError, FileNotFoundError, OSError):
            return []

    # ── Path input: Enter → jump, Tab → complete, Up/Down → cycle matches ───

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._navigate_to(event.value.strip())

    def on_input_changed(self, event: Input.Changed) -> None:
        """Reset tab-completion state whenever the user manually edits the path."""
        if self._applying_tab:
            return  # ignore programmatic changes (tab fill / navigate_to)
        self._tab_matches = []
        self._tab_idx = -1
        self._update_hint("  Tab: complete path  ↑↓: pick match")

    def on_key(self, event) -> None:
        """Handle Tab / Up / Down inside the path Input for path completion."""
        # Only act when the path input is focused
        try:
            focused = self.query_one("#dir-path-input", Input)
            if not focused.has_focus:
                return
        except Exception:
            return

        key = event.key

        if key == "tab":
            event.prevent_default()
            event.stop()
            try:
                partial = self.query_one("#dir-path-input", Input).value
            except Exception:
                return
            # Build / refresh match list
            matches = self._fs_matches(partial)
            if not matches:
                self._update_hint("  [dim]No matches[/dim]")
                return
            self._tab_matches = matches
            self._tab_idx = 0
            self._apply_tab_match()

        elif key == "up" and self._tab_matches:
            event.prevent_default()
            event.stop()
            self._tab_idx = max(0, self._tab_idx - 1)
            self._apply_tab_match()

        elif key == "down" and self._tab_matches:
            event.prevent_default()
            event.stop()
            self._tab_idx = min(len(self._tab_matches) - 1, self._tab_idx + 1)
            self._apply_tab_match()

    def _apply_tab_match(self) -> None:
        """Fill the input with the currently highlighted tab match."""
        m = self._tab_matches[self._tab_idx]
        self._update_path_input(m)
        total = len(self._tab_matches)
        self._update_hint(
            f"  [{self._tab_idx+1}/{total}] Tab/↑↓: cycle  Enter: jump"
        )

    # ── Parent dir button ─────────────────────────────────────────────────

    # ── Click directory in tree ───────────────────────────────────────────

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self._chosen = str(event.path)
        self._update_selected(f"[green]{self._chosen}[/green]")
        self._update_path_input(self._chosen)

    # ── Buttons ─────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "btn-cd-ok":
            self.dismiss(self._chosen)
        elif bid == "btn-parent":
            from pathlib import Path
            p = Path(self._chosen)
            parent = p.parent
            # If already at drive root (parent == self), show drive picker
            if parent == p or self._drives_mode:
                self._show_drives()
            else:
                self._navigate_to(str(parent))
        elif bid and bid.startswith("drv-"):
            # Drive button clicked
            drive_letter = bid[4:]  # e.g. "C"
            drive_path = f"{drive_letter}:\\"
            self._hide_drives()
            self._navigate_to(drive_path)
        else:  # btn-cd-cancel
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
