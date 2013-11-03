Actual Vim
----

Warning: This is alpha software. Editing files is not yet entirely consistent.

The goal is to use a hidden Vim instance to accurately manipulate a Sublime Text buffer as though you were editing the text directly in Vim. This has been accomplished.

It's not simply a terminal emulator embedded in a text editor. Sublime is still in control of the text buffer. You will be able to use the entire native Sublime interface while in INSERT mode, including plugins.

Why?
----

This project allows you to use your own vimrc, plugins, and pretty much any Vim motions and commands whatsoever.

Vim emulation plugins are rough approximations of the functionality of Vim itself. They are missing features or behave differently than the real thing.

This project does not have those problems, because it IS Vim.

Usage
----

This plugin relies on Vim itself, and operating system features not found in Windows. Thats means it's likely to only work in Linux and OS X for the near future. It's only been tested with an unmodified copy of Vim 7.4 on OS X 10.8 thus far.

Just clone this to `Sublime Text 3/Packages/actualvim/`

Actual will launch a controlling instance of Vim for every Sublime Text view you open.

Misc
----

On OS X 10.7+, you should do `defaults write com.sublimetext.3 ApplePressAndHoldEnabled -bool false` to enable key repeat.
