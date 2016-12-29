# Crater

A really really simple package dependency manager.

Except we use the word "crate" instead of "package" because it sounds more cool.
The word also differentiates this particualar solution from others, especially
in the following areas.

 * There is no centralized crate repository.
   Every git repo or zip file that is publicly visible is automatically a viable crate.
 * There is no preferred programming language.
   You can use crater for C++ projects as easily as for JavaScript.
   Feel free to ditch npm.
 * Crater doesn't differentiate between source and binary crates.
   If you want to pull pre-built binaries, go right ahead.
 * Crater doesn't do builds.
   It does however export all the information necessary
   for you to integrate your favorite build system.
 * Crater handles diamond dependencies.
   A lot of other package managers do that too, but it's still worth mentioning.
   Otherwise, you might as well use git submodules.

## Installation

Crater is written in python, so you'll need that.
You'll also need pip, the python package manager.

    $ pip install crater
