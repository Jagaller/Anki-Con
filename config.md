## Anki-Con

You almost certainly want **Tools ▸ Anki-Con…** instead of this editor — it maps
buttons on a picture of the controllers, which is a lot easier than editing JSON.

### `layouts`

One complete button map per grip. Which one is live depends on what's connected:

| Grip | When it applies |
|---|---|
| `dual` | Both Joy-Cons (or a Pro Controller) connected |
| `single_h` | One Joy-Con, held sideways |
| `single_v` | One Joy-Con, held upright |

With a single Joy-Con, `orientation` (`single_h` or `single_v`) picks between the
last two.

Keys are `L:` or `R:` plus the name printed on the plastic — `R:A`, `L:ZL`,
`R:SR`, `L:Capture` — plus `StickUp` / `StickDown` / `StickLeft` / `StickRight`
for pushing the analog stick, and `LStick` / `RStick` for clicking it in.

Values are action ids: `show_answer`, `again`, `hard`, `good`, `easy`, `undo`,
`replay_audio`, `pause_audio`, `audio_back`, `audio_forward`, `mark_note`,
`toggle_masks`, `bury_card`, `suspend_card`, `flag_1`…`flag_7`, `browse`, `sync`, and the rest of
the More menu. Use `none` to leave a button unbound.

### `colors`

`shell` sets each half's body colour; `buttons` overrides individual buttons by
the same `L:` / `R:` key. Anything absent from `buttons` uses the stock colour.
All values are hex strings like `"#e0474f"`.

### Everything else

If a button does the wrong thing, **Tools ▸ Anki-Con… ▸ Diagnostics…** shows the
button id the add-on actually received when you press it.

- `enabled` — listen for Joy-Cons at all.
- `ease_reveals_answer` — pressing an ease button while the question is showing
  reveals the answer instead of being dropped.
- `rumble_on_answer`, `rumble_strength` — haptic feedback, 0.0–1.0.
- `stick_deadzone` — how far the stick must move to count, 0.2–0.95.
- `seize_device` — take the controller away from macOS's own Joy-Con driver.
  Turn this on if the controller connects but no buttons do anything.
- `player_leds` — light the player LED on a connected controller; off turns it
  out.
- `show_tooltip_on_action` — name each action as it fires (handy for debugging).
- `verbose_log` — log HID activity to the console.

Saved controller profiles are separate files under the add-on's `user_files`
directory, not part of this config.
