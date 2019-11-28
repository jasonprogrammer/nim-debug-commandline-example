# How to debug Nim using command-line GDB

The steps below demonstrate how to debug [Nim](https://nim-lang.org/) code from the command-line using [GDB](https://www.gnu.org/software/gdb/).

## Prerequisites

1. Nim is installed.
2. GDB is installed.
3. Python 3 is installed (used for pretty-printing with GDB).

## Debugging

1. Run `./build.sh` to build an executable.
2. Run `./debug.sh` to start a debugging session.
3. A GDB session should start, and allow you to set breakpoints and print variables, e.g.:

```
Loading Nim Runtime support.
(gdb) b main.nim:15
Breakpoint 1 at 0x10dd0: file /home/jason/projects/nim-debug-commandline-example/main.nim, line 15.
(gdb) r
Starting program: /home/jason/projects/nim-debug-commandline-example/bin/main 

Breakpoint 1, main__9bQIWt54CdTNMd7hgR2Bl9cw () at /home/jason/projects/nim-debug-commandline-example/main.nim:15
15	  echo name
(gdb) print name
$1 = "bob"
(gdb) n
bob
16	  echo people[0].name
(gdb) print people[0].name
$2 = "John"
(gdb)
```

## Notes

The `nim-gdb.py` script was copied from [here](https://github.com/nim-lang/Nim/blob/master/tools/nim-gdb.py),
and exists in this repository simply to reduce the number of steps in setting this up. It might be a good
idea to update your copy of this file with the official latest file from the repository.

