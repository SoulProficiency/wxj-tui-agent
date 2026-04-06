"""
LogoPanel: Persistent header with three-column layout.

[NewsPanel]  |  [GreetingArea]  |  [LogoArea]
  1fr               1fr               2fr

NewsPanel   — rotating news headlines / health tips (from daily.md or fallback)
GreetingArea — greeting text + date + themes
LogoArea    — ASCII logo, cycles style on each /logo call

/logo     — advance to next logo style (instant, no LLM)
/newdaily — regenerate daily.md via LLM, refresh all panels
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static


# ── Base mixin: make compose-only widgets renderable ─────────────────────────
# All panels inherit Vertical (a layout container). We must NOT override
# _render() because Textual uses that name internally. We also must NOT
# override render() on containers — Vertical.render() returns Blank() which
# is the correct Visual for a container. Adding layout:vertical to DEFAULT_CSS
# ensures is_container=True so the Blank path is taken.

# ── Theme → color mapping ─────────────────────────────────────────────────────

_THEME_COLORS: dict[str, str] = {
    "spring":     "bold green",
    "summer":     "bold yellow",
    "autumn":     "bold red",
    "winter":     "bold blue",
    "creativity": "bold magenta",
    "technology": "bold cyan",
    "innovation": "bold bright_cyan",
    "code":       "bold bright_green",
    "renewal":    "bold green",
    "blooming":   "bold magenta",
    "dawn":       "bold yellow",
    "awakening":  "bold cyan",
    "easter":     "bold magenta",
    "blossom":    "bold bright_magenta",
    "rain":       "bold blue",
    "growth":     "bold green",
    "energy":     "bold yellow",
    "focus":      "bold cyan",
    "flow":       "bold bright_blue",
    "weekend":    "bold bright_yellow",
    "friday":     "bold bright_yellow",
    "monday":     "bold blue",
}
_DEFAULT_COLOR = "bold cyan"

# ── Logo style library ────────────────────────────────────────────────────────
# (label, lines)  — last line is subtitle, rendered dim

_LOGO_STYLES: list[tuple[str, list[str]]] = [
    ("standard", [
        "__      __ __  __       _",
        "\\ \\    / / \\ \\/ /      | |",
        " \\ \\  / /   >  <    _  | |",
        "  \\ \\/ /   / /\\ \\  | |_/ /",
        "   \\__/   /_/  \\_\\  \\___/",
        "  AI Coding Assistant v0.1.0",
    ]),
    ("boxed", [
        "+---------------------------+",
        "| \\\\  /  \\ \\ / /        |  |  |",
        "|  \\\\/    \\ V /    _ |  |  |",
        "|  / \\     > <   | || | / |",
        "| /    \\  /_/ \\_\\|_||_|/ |",
        "+---------------------------+",
        "  AI Coding Assistant v0.1.0",
    ]),
    ("eyes", [
        "__      __ __  __       _",
        "\\ \\    / / \\ \\/ /      | |",
        " \\ \\  / /   >  <    _  | |",
        "  \\ \\/ /   / /\\ \\  | |_/ /",
        "   \\(o)/   /_/  \\_\\  \\___/",
        "  (^_^)  AI Coding Assistant",
    ]),
    ("shadow", [
        " __      __  _  _  _",
        " \\ \\    / / | || || |",
        "  \\ \\  / /  \\_  _/ | |",
        "   \\ \\/ /   / / \\  | |",
        "    \\__/   /_/   \\_\\|_|",
        "  ~~ AI Coding Assistant ~~",
    ]),
    ("mirrored", [
        "  _       _ __  __      __",
        " | |     | |\\ \\/ /    / /",
        " | |  _  | | \\  /  _ / /",
        " | | | |_| | /  \\ | \\ \\",
        " |_|  \\___/ /_/\\_\\  \\_\\",
        "  0.1v  tnatsissA gnidoC IA",
    ]),
    ("minimal", [
        ". . . W . X . J . . .",
        ":::::::::::::::::::::::",
        "  AI  Coding Assistant ",
        ":::::::::::::::::::::::",
        "       v 0.1.0         ",
    ]),
    ("block", [
        "##  ##  ## ##   ###",
        "##  ##   ####    ## ",
        "######    ##      ## ",
        "##  ##   ####  ## ##",
        "##  ##  ##  ##  ###",
        "  AI Coding Assistant v0.1.0  ",
    ]),
    ("retro", [
        ">>===[ W X J ]===<<",
        "   AI Coding System   ",
        "  >> v0.1.0 ONLINE << ",
        " [ STATUS: READY ]    ",
        ">>==================<<",
    ]),
    ("heart", [
        "  <3   W X J   <3   ",
        " ~~ Your Code Buddy ~~",
        "   __      __ __  __  ",
        "   \\ \\    / / \\ \\/ /  ",
        "    \\ \\  / /   >  <   ",
        "     \\__/   /_/\\_\\  ",
    ]),
    ("banner", [
        "  /$$      /$$  /$$  /$$  /$$     /$$",
        " | $$  /$ | $$ \\ $$\\/ $$/ /$$   | $$",
        " | $$ /$$\\| $$  \\  $$$$/ /$$$$  | $$",
        " | $$/$$ $$ $$   \\  $$/  | $$__  | $$",
        " | $$$$_  $$$$   | $$   | $$  \\  |__/",
        "  AI Coding Assistant  v0.1.0 ",
    ]),
]

_TOTAL_STYLES = len(_LOGO_STYLES)

# ── Fallback health tips ──────────────────────────────────────────────────────

_FALLBACK_TIPS: list[str] = [
    "20-20-20: look 20ft away 20s",
    "Drink water — brain is 75% H2O",
    "Posture: feet flat, back straight",
    "Stand & stretch every hour",
    "4s in, 4s hold, 4s out breath",
    "Wrist stretch — prevent RSI",
    "Sleep 7-9h: boosts coding flow",
    "Look at a window — natural light",
    "5 min brain break catches bugs",
    "Nuts/fruit beat energy drinks",
    "Blink more — reduce eye strain",
    "Hydrate before caffeine",
    "Walk during calls if possible",
    "Dim screen after sunset",
    "End the day with /stop :)",
]

_NEWS_INTERVAL = 8    # seconds — fast enough to feel like a ticker
_GREET_INTERVAL = 60  # seconds — greeting area slow-refresh


# ── NewsPanel ─────────────────────────────────────────────────────────────────

class NewsPanel(Vertical):
    """
    Left column: news ticker / health tips.
    Shows one item at a time, cycles every _NEWS_INTERVAL seconds.
    """

    DEFAULT_CSS = """
    NewsPanel {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        background: $surface;
        border-right: solid $accent;
        padding: 0 1;
        align: center middle;
    }
    NewsPanel #news-index {
        color: $accent;
        text-style: bold;
        text-align: center;
        width: 1fr;
    }
    NewsPanel #news-item {
        color: $text;
        text-align: center;
        width: 1fr;
        text-wrap: wrap;
    }
    NewsPanel #news-source {
        color: $text-muted;
        text-align: center;
        width: 1fr;
        text-style: dim;
    }
    NewsPanel #news-status {
        text-align: center;
        width: 1fr;
        text-style: dim;
    }
    """

    # Status constants
    STATUS_OK      = "ok"       # green  — up to date / never errored
    STATUS_BUSY    = "busy"     # yellow — LLM running
    STATUS_STALE   = "stale"    # red    — date mismatch / LLM error

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._items: list[str] = []
        self._idx: int = 0
        self._has_daily: bool = False
        self._timer = None
        self._status: str = self.STATUS_OK

    def compose(self) -> ComposeResult:
        yield Static("", id="news-index")
        yield Static("", id="news-item")
        yield Static("", id="news-source")
        yield Static("", id="news-status")

    def on_mount(self) -> None:
        self._reload()
        self._timer = self.set_interval(_NEWS_INTERVAL, self._tick)

    def refresh_daily(self) -> None:
        self._reload()

    def set_daily_status(self, status: str) -> None:
        """Update the status indicator dot in the news panel.

        status values:
          STATUS_OK    ("ok")    → green  ● daily up to date
          STATUS_BUSY  ("busy")  → yellow ● updating…
          STATUS_STALE ("stale") → red    ● needs update / error
        """
        self._status = status
        self._render_status()

    def _render_status(self) -> None:
        color_map = {
            self.STATUS_OK:    ("green",  "● daily ok"),
            self.STATUS_BUSY:  ("yellow", "● updating…"),
            self.STATUS_STALE: ("red",    "● needs /newdaily"),
        }
        color, label = color_map.get(self._status, ("green", "● daily ok"))
        markup = f"[{color}]{label}[/{color}]"
        try:
            self.query_one("#news-status", Static).update(markup)
        except Exception:
            pass

    def _reload(self) -> None:
        from agent.daily import load_daily, parse_news
        daily = load_daily()
        if daily:
            news = parse_news(daily)
            if news:
                self._items = news
                self._has_daily = True
            else:
                self._items = _FALLBACK_TIPS
                self._has_daily = False
        else:
            self._items = _FALLBACK_TIPS
            self._has_daily = False
        self._idx = 0
        self._update_display()

    def _tick(self) -> None:
        if not self._items:
            return
        self._idx = (self._idx + 1) % len(self._items)
        self._update_display()

    def _update_display(self) -> None:
        if not self._items:
            return
        item = self._items[self._idx]
        total = len(self._items)
        idx_str = f"[{self._idx + 1}/{total}]"
        source = "Today's News" if self._has_daily else "Health Tips"
        try:
            self.query_one("#news-index", Static).update(idx_str)
            self.query_one("#news-item", Static).update(item)
            self.query_one("#news-source", Static).update(source)
        except Exception:
            pass
        self._render_status()


# ── GreetingArea ──────────────────────────────────────────────────────────────

class GreetingArea(Vertical):
    """
    Middle column: greeting + date info + themes tags.
    """

    DEFAULT_CSS = """
    GreetingArea {
        width: 1fr;
        height: 1fr;
        layout: vertical;
        background: $surface;
        border-right: solid $accent;
        padding: 0 1;
        align: center middle;
    }
    GreetingArea #greet-text {
        color: $accent;
        text-style: bold italic;
        text-align: center;
        width: 1fr;
        text-wrap: wrap;
    }
    GreetingArea #greet-date {
        color: $text-muted;
        text-align: center;
        width: 1fr;
        margin-top: 1;
    }
    GreetingArea #greet-themes {
        color: $text-muted;
        text-align: center;
        width: 1fr;
        text-style: dim;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)

    def compose(self) -> ComposeResult:
        yield Static("", id="greet-text")
        yield Static("", id="greet-date")
        yield Static("", id="greet-themes")

    def on_mount(self) -> None:
        self._reload()

    def refresh_daily(self) -> None:
        self._reload()

    def _reload(self) -> None:
        from datetime import date as _date
        from agent.daily import load_daily, parse_greeting, parse_themes

        today = _date.today()
        date_str = today.strftime("%B %d, %Y  %A")

        daily = load_daily()
        if daily:
            greeting = parse_greeting(daily) or "Good day, developer!"
            themes = parse_themes(daily)
            themes_str = "  ".join(f"#{t}" for t in themes[:4]) if themes else ""
        else:
            greeting = "Run /newdaily for today's content"
            themes_str = "#code  #build  #ship"

        try:
            self.query_one("#greet-text", Static).update(greeting)
            self.query_one("#greet-date", Static).update(date_str)
            self.query_one("#greet-themes", Static).update(themes_str)
        except Exception:
            pass


# ── LogoArea ──────────────────────────────────────────────────────────────────

class LogoArea(Vertical):
    """Right column: ASCII logo, cycles style on /logo."""

    DEFAULT_CSS = """
    LogoArea {
        width: 2fr;
        height: 1fr;
        layout: vertical;
        background: $surface;
        padding: 0 1;
        align: center middle;
    }
    LogoArea #logo-text {
        width: auto;
        height: auto;
        content-align: center middle;
        text-align: center;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._style_idx: int = 0
        self._color: str = _DEFAULT_COLOR

    def compose(self) -> ComposeResult:
        yield Static("", id="logo-text", markup=True)

    def on_mount(self) -> None:
        self._refresh_logo()

    def set_themes(self, themes: list[str]) -> None:
        for t in (t.lower() for t in themes):
            if t in _THEME_COLORS:
                self._color = _THEME_COLORS[t]
                break
        self._refresh_logo()

    def next_style(self) -> str:
        self._style_idx = (self._style_idx + 1) % _TOTAL_STYLES
        self._refresh_logo()
        return _LOGO_STYLES[self._style_idx][0]

    def _refresh_logo(self) -> None:
        label, lines = _LOGO_STYLES[self._style_idx]
        color = self._color
        body = "\n".join(f"[{color}]{l}[/{color}]" for l in lines[:-1])
        sub  = f"[dim]{lines[-1]}[/dim]"
        try:
            self.query_one("#logo-text", Static).update(body + "\n" + sub)
        except Exception:
            pass


# ── LogoPanel (container) ─────────────────────────────────────────────────────

class LogoPanel(Vertical):
    """
    Full-width header panel below app Header.
    Three columns: NewsPanel | GreetingArea | LogoArea
    """

    DEFAULT_CSS = """
    LogoPanel {
        height: 8;
        width: 1fr;
        layout: vertical;
        background: $surface;
        border-bottom: solid $accent;
    }
    LogoPanel > Horizontal {
        height: 1fr;
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield NewsPanel(id="news-panel")
            yield GreetingArea(id="greeting-area")
            yield LogoArea(id="logo-area")

    def on_mount(self) -> None:
        self._apply_daily_themes()
        self._init_daily_status()

    def _init_daily_status(self) -> None:
        """On startup: set status red if daily.md is missing or stale."""
        from agent.daily import load_daily
        daily = load_daily()  # returns '' if missing or not today
        status = NewsPanel.STATUS_OK if daily else NewsPanel.STATUS_STALE
        try:
            self.query_one("#news-panel", NewsPanel).set_daily_status(status)
        except Exception:
            pass

    def _apply_daily_themes(self) -> None:
        from agent.daily import load_daily, parse_themes
        daily = load_daily()
        if daily:
            themes = parse_themes(daily)
            try:
                self.query_one("#logo-area", LogoArea).set_themes(themes)
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────────────────────

    def next_logo_style(self) -> str:
        """Instant style cycle. Returns new style label."""
        try:
            return self.query_one("#logo-area", LogoArea).next_style()
        except Exception:
            return "unknown"

    def set_daily_status(self, status: str) -> None:
        """Forward status to NewsPanel. Use NewsPanel.STATUS_* constants."""
        try:
            self.query_one("#news-panel", NewsPanel).set_daily_status(status)
        except Exception:
            pass

    def refresh_daily(self) -> None:
        """Reload all panels from daily.md after /newdaily."""
        for widget_id, cls in [
            ("#news-panel", NewsPanel),
            ("#greeting-area", GreetingArea),
        ]:
            try:
                self.query_one(widget_id, cls).refresh_daily()
            except Exception:
                pass
        self._apply_daily_themes()
