"""
Everything a Joy-Con button can be bound to.

Anki renames reviewer methods fairly often between releases, so each action is
resolved at press time in three passes:

  1. Emit the QShortcut Anki itself registered for that key. This is the most
     durable route -- whatever Anki binds to "2" today is what fires, including
     future behaviour changes, and it costs nothing when the shortcut moves.
  2. Trigger a matching QAction from the main window's menus (covers Decks,
     Add, Browse, Stats, Sync, Undo).
  3. Call a known method directly, trying several historical names.

Actions never run while a modal dialog is up, and review-only actions never run
outside the reviewer, so a stray thumb press cannot answer a card from the
deck list.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Callable, List, Optional

from aqt import mw
from aqt.qt import *
from aqt.utils import tooltip


# --------------------------------------------------------------------------
# Low-level triggers
# --------------------------------------------------------------------------

def _exact_match():
    # PyQt6 scopes the enum; PyQt5 does not.
    try:
        return QKeySequence.SequenceMatch.ExactMatch
    except AttributeError:
        return QKeySequence.ExactMatch


def _emit_state_shortcut(seq: str) -> bool:
    """Fire the QShortcut Anki registered for the current state."""
    target = QKeySequence(seq)
    if target.isEmpty():
        return False
    exact = _exact_match()
    for sc in list(getattr(mw, "stateShortcuts", None) or []):
        try:
            if sc.key().matches(target) == exact:
                sc.activated.emit()
                return True
        except Exception:
            continue
    return False


def _trigger_menu_action(seq: str) -> bool:
    target = QKeySequence(seq)
    if target.isEmpty():
        return False
    exact = _exact_match()
    try:
        candidates = mw.findChildren(QAction)
    except Exception:
        return False
    for act in candidates:
        try:
            if not act.isEnabled():
                continue
            for k in act.shortcuts():
                if k.matches(target) == exact:
                    act.trigger()
                    return True
        except Exception:
            continue
    return False


def _call_first(obj, *names, args=()) -> bool:
    for n in names:
        fn = getattr(obj, n, None)
        if callable(fn):
            fn(*args)
            return True
    return False


def _reviewer(*names, args=()) -> Callable[[], bool]:
    def run() -> bool:
        rev = getattr(mw, "reviewer", None)
        return bool(rev) and _call_first(rev, *names, args=args)
    return run


def _main(*names, args=()) -> Callable[[], bool]:
    def run() -> bool:
        return _call_first(mw, *names, args=args)
    return run


# --------------------------------------------------------------------------
# Toggle Masks
#
# Not a reviewer command at all: it is a button inside the card, drawn by the
# card's own template. So it is clicked in the page, like a mouse would.
#
#   #toggle        Anki's built-in Image Occlusion. The id is generic enough to
#                  turn up in unrelated templates, hence the container check.
#                  Anki hides it when the card has nothing to toggle.
#   #io-revl-btn   The Image Occlusion Enhanced add-on. Some templates hide the
#                  button but its handler still works, so visibility is ignored.
#
# Failing both, any visible button captioned "Toggle Masks" will do, which
# covers note types that restyled either of them.
# --------------------------------------------------------------------------

_TOGGLE_MASKS_JS = r"""
(() => {
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const native = document.getElementById("image-occlusion-container")
    && document.getElementById("toggle");
  const enhanced = document.getElementById("io-revl-btn");
  const target = (visible(native) && native) || enhanced
    || [...document.querySelectorAll("button, input[type=button], a")].find(
      (el) => visible(el)
        && /^\s*toggle\s+masks?\s*$/i.test(el.textContent || el.value || ""));
  if (!target) { return false; }
  target.click();
  return true;
})()
"""


def _toggle_masks() -> bool:
    def done(found) -> None:
        if found is False:
            tooltip("This card has no masks to toggle.", period=1200)

    mw.reviewer.web.evalWithCallback(_TOGGLE_MASKS_JS, done)
    return True


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

@dataclass
class Action:
    id: str
    label: str
    group: str
    shortcut: str = ""
    fallback: Optional[Callable[[], bool]] = None
    review_only: bool = True
    answer_side_only: bool = False
    question_side_only: bool = False
    repeatable: bool = True         # False: holding a stick fires it only once
    haptic: bool = True             # False: never rumbles, whatever its group

    def run(self) -> bool:
        if self.shortcut and _emit_state_shortcut(self.shortcut):
            return True
        if self.shortcut and _trigger_menu_action(self.shortcut):
            return True
        if self.fallback:
            try:
                return bool(self.fallback())
            except Exception:
                return False
        return False


# Anki uses a different key on macOS.
_DELETE_NOTE_KEY = "Ctrl+Backspace" if sys.platform == "darwin" else "Ctrl+Delete"


def _flag(n: int) -> Action:
    return Action(f"flag_{n}", f"Flag {n}", "Flags", f"Ctrl+{n}",
                  _reviewer("set_flag_on_current_card", "setFlag", args=(n,)))


ACTIONS: List[Action] = [
    Action("none", "— nothing —", "General", "", lambda: True, review_only=False),

    # --- answering -------------------------------------------------------
    Action("show_answer", "Show Answer", "Answering", " ",
           _reviewer("_showAnswer", "onEnterKey"), question_side_only=True),
    Action("again", "Again (1)", "Answering", "1",
           _reviewer("_answerCard", args=(1,)), answer_side_only=True),
    Action("hard", "Hard (2)", "Answering", "2",
           _reviewer("_answerCard", args=(2,)), answer_side_only=True),
    Action("good", "Good (3)", "Answering", "3",
           _reviewer("_answerCard", args=(3,)), answer_side_only=True),
    Action("easy", "Easy (4)", "Answering", "4",
           _reviewer("_answerCard", args=(4,)), answer_side_only=True),
    Action("space", "Show Answer / Good (Space)", "Answering", " ",
           _reviewer("onEnterKey")),
    Action("undo", "Undo", "Answering", "Ctrl+Z",
           _main("undo", "onUndo"), review_only=False),

    # --- audio (matches the More menu) ------------------------------------
    Action("replay_audio", "Replay Audio", "Audio", "R",
           _reviewer("replayAudio", "replay_audio")),
    Action("pause_audio", "Pause Audio", "Audio", "5",
           _reviewer("on_pause_audio")),
    Action("audio_back", "Audio −5s", "Audio", "6",
           _reviewer("on_seek_backward")),
    Action("audio_forward", "Audio +5s", "Audio", "7",
           _reviewer("on_seek_forward")),
    Action("record_voice", "Record Own Voice", "Audio", "Shift+V",
           _reviewer("onRecordVoice", "on_record_voice")),
    Action("replay_recorded", "Replay Own Voice", "Audio", "V",
           _reviewer("onReplayRecorded", "on_replay_recorded")),

    # --- card / note actions ---------------------------------------------
    Action("toggle_masks", "Toggle Masks", "Card", "", _toggle_masks,
           haptic=False),
    Action("mark_note", "Mark Note", "Card", "*",
           _reviewer("toggle_mark_on_current_note", "onMark", "on_mark")),
    Action("bury_card", "Bury Card", "Card", "-",
           _reviewer("bury_current_card"), repeatable=False),
    Action("bury_note", "Bury Note", "Card", "=",
           _reviewer("bury_current_note"), repeatable=False),
    Action("suspend_card", "Suspend Card", "Card", "@",
           _reviewer("suspend_current_card")),
    Action("suspend_note", "Suspend Note", "Card", "!",
           _reviewer("suspend_current_note")),
    Action("delete_note", "Delete Note", "Card", _DELETE_NOTE_KEY,
           _reviewer("delete_current_note")),
    Action("create_copy", "Create Copy", "Card", "Ctrl+Alt+E",
           _reviewer("on_create_copy")),
    Action("reset_card", "Reset Card", "Card", "Ctrl+Alt+N",
           _reviewer("forget_current_card", "on_forget", "on_reset_card")),
    Action("set_due_date", "Set Due Date", "Card", "Ctrl+Shift+D",
           _reviewer("on_set_due", "set_due_date")),
    Action("card_info", "Card Info", "Card", "I",
           _reviewer("on_card_info", "card_info")),
    Action("previous_card_info", "Previous Card Info", "Card", "Ctrl+Alt+I",
           _reviewer("on_previous_card_info")),
    Action("options", "Deck Options", "Card", "O",
           _reviewer("onOptions", "on_options")),
    Action("auto_advance", "Toggle Auto Advance", "Card", "Shift+A",
           _reviewer("toggle_auto_advance", "on_auto_advance")),
    Action("edit_current", "Edit Current Card", "Card", "E",
           _main("onEditCurrent")),
    Action("more_menu", "Open the More menu", "Card", "",
           _reviewer("showContextMenu", "show_context_menu")),

    # --- flags ------------------------------------------------------------
    _flag(1), _flag(2), _flag(3), _flag(4), _flag(5), _flag(6), _flag(7),

    # --- navigation -------------------------------------------------------
    Action("decks", "Deck list", "Navigation", "D",
           lambda: (mw.moveToState("deckBrowser"), True)[1], review_only=False),
    Action("study_current", "Study current deck", "Navigation", "",
           _main("onOverview"), review_only=False),
    Action("add_note", "Add note", "Navigation", "A",
           _main("onAddCard"), review_only=False),
    Action("browse", "Browse", "Navigation", "B",
           _main("onBrowse"), review_only=False),
    Action("stats", "Statistics", "Navigation", "Shift+S",
           _main("onStats"), review_only=False),
    Action("sync", "Sync", "Navigation", "Y",
           _main("onSync", "on_sync_button_clicked"), review_only=False),
]

ACTIONS_BY_ID = {a.id: a for a in ACTIONS}

GROUP_ORDER = ["Answering", "Audio", "Card", "Flags", "Navigation", "General"]


def grouped_actions():
    """[(group, [Action, ...]), ...] in a stable order for the config UI."""
    out = []
    for g in GROUP_ORDER:
        items = [a for a in ACTIONS if a.group == g]
        if items:
            out.append((g, items))
    return out


def label_for(action_id: str) -> str:
    a = ACTIONS_BY_ID.get(action_id)
    return a.label if a else action_id


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------

def _blocked() -> bool:
    """True while a modal dialog or a popup menu is up."""
    try:
        return (mw is None or mw.app.activeModalWidget() is not None
                or mw.app.activePopupWidget() is not None)
    except Exception:
        return False


def can_run(action: Action) -> bool:
    """Guard rails, so a pocket press cannot do something surprising."""
    if _blocked():
        return False

    if action.review_only:
        if getattr(mw, "state", None) != "review":
            return False
        rev = getattr(mw, "reviewer", None)
        if rev is None or getattr(rev, "card", None) is None:
            return False
        if action.answer_side_only and getattr(rev, "state", None) != "answer":
            return False
        if action.question_side_only and getattr(rev, "state", None) != "question":
            return False
    return True


def run_action(action_id: str, reveal_first: bool = True) -> bool:
    """
    Execute a bound action. If an ease button is pressed while the question is
    still showing, optionally reveal the answer instead of dropping the press.
    """
    action = ACTIONS_BY_ID.get(action_id)
    if action is None or action.id == "none":
        return False

    if (action.answer_side_only and reveal_first
            and getattr(mw, "state", None) == "review"
            and getattr(getattr(mw, "reviewer", None), "state", None) == "question"):
        action = ACTIONS_BY_ID["show_answer"]

    if not can_run(action):
        return False
    return action.run()
