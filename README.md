ActualVim
----

Actual uses an embedded Neovim instance to accurately manipulate a Sublime Text buffer as though you were editing the text directly in vim.

You can still use the entire native Sublime interface, including plugins. Changes and selection are bidirectionally synced. Multiple selection is a WIP.

Why?
----

This project allows you to use your own vimrc, plugins, and any real vim motions/commands.

Other vim emulation plugins, including the built-in Vintage, are only rough approximations of the functionality of vim itself.
They are missing features or behave differently than the real thing.

This project does not have those problems, because it *is* vim.

Usage
----

This plugin requires Neovim to be installed, but should otherwise work on all Sublime Text 3 platforms.

Just clone ActualVim to the path found in "Preferences -> Browse Packages..." or `sublime.packages\_path()`. Usually found here:

- macOS: `~/Library/Application Support/Sublime Text 3/Packages/`
- Linux: `~/.config/sublime-text-3/Packages/`
- Windows: `%APPDATA%/Sublime Text 3/Packages/`

ActualVim launches a single Neovim embedded instance and multiplexes each Sublime view into a separate buffer.

Misc
----

On OS X 10.7+, you should do `defaults write com.sublimetext.3 ApplePressAndHoldEnabled -bool false` to enable key repeat.

You can run `ActualVim: Disable` or `ActualVim: Enable` via the command pallete to toggle the input mode without losing vim state.
