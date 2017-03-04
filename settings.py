import sublime
import sublime_plugin

DEFAULT_SETTINGS = {
    "enabled": True,
    "neovim_path": "",
    "indent_priority": "sublime",
    "settings": {
        "sublime": {
            "inverse_caret_state": False,
        },
        "vim": {
            "bell": {
                "color_scheme": "Packages/actualvim/Bell.tmTheme",
                "duration": 0.001
            },
            "inverse_caret_state": False,
            "modes": {
                "all insert": {},
                "all visual": {},
                "command": {},
                "insert": {},
                "normal": {
                    "inverse_caret_state": True,
                },
                "replace": {},
                "visual": {},
                "visual block": {},
                "visual line": {}
            }
        }
    }
}

if not 'settings' in globals():
    settings = None
    was_enabled = False

def load():
    global settings, was_enabled
    settings = sublime.load_settings('ActualVim.sublime-settings')
    settings.add_on_change('settings', _changed)
    changed = False
    for k, v in DEFAULT_SETTINGS.items():
        if not settings.has(k):
            settings.set(k, v)
            changed = True
    if changed:
        save()
    was_enabled = enabled()

def enabled():
    return settings and settings.get('enabled')

def enable():
    set('enabled', True)
    save()

def disable():
    set('enabled', False)
    save()

def _changed():
    from .view import ActualVim
    v = ActualVim.get(sublime.active_window().active_view(), create=False)
    if v:
        v.update_view()

    global was_enabled
    en = get('enabled')
    if en != was_enabled:
        was_enabled = en
        ActualVim.enable(en)

def set(key, value):
    return settings.set(key, value)

def has(key):
    return settings.has(key)

def get(key, default=None):
    return settings.get(key, default)

def save():
    sublime.save_settings('ActualVim.sublime-settings')
