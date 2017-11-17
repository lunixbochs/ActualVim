import platform
import sublime
import sublime_plugin

DEFAULT_SETTINGS = {
    "bufopts": {
        "completefunc": "ActualVimComplete",
    },
    "enabled": True,
    "large_file_disable": {
        "bytes": 52428800,
        "lines": 50000,
    },
    'smooth_scroll': False,
    "neovim_path": "",
    "neovim_args": ["--cmd", "let g:actualvim = 1"],
    "settings_priority": "sublime",
    "settings": {
        "sublime": {
            "inverse_caret_state": False,
        },
        "vim": {
            "bell": {
                "color_scheme": "Packages/ActualVim/Bell.tmTheme",
                "duration": 0.001
            },
            "inverse_caret_state": False,
            "modes": {
                "all insert": {},
                "all visual": {},
                "command": {
                    "inverse_caret_state": True,
                },
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

if platform.system() != 'Darwin':
    keys = {
        'av:ctrl+n': True,
        'av:ctrl+s': True,
        'av:ctrl+w': True,
    }
    DEFAULT_SETTINGS['settings']['vim']['modes']['normal'].update(keys)

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

# proxy settings load
# this is necessary due to a bug when disabling/enabling via package control
def s():
    if not settings:
        load()
    return settings

def enabled():
    return s().get('enabled')

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
    return s().set(key, value)

def has(key):
    return s().has(key)

def get(key, default=None):
    return s().get(key, default)

def save():
    sublime.save_settings('ActualVim.sublime-settings')
