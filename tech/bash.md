# Bash

## What it is

Bash is a **shell**: a program that reads a line of text, runs the command it names, and shows the result. It is also a small programming language. A **shell script** is a text file of such lines, run top to bottom. This repository has one script, `scripts/demo.sh`, and many shell fragments inside the `Makefile` recipes (a `make` target runs its lines with `/bin/sh`, which on macOS and Linux behaves like a simple Bash).

Terms you will meet: a **process** is a running program; an **exit code** is the number a process returns when it ends (0 = success, anything else = failure); **standard output** (stdout) is where a program prints results; **standard error** (stderr) is where it prints problems; a **signal** is a message the operating system sends to a process (SIGTERM means "please stop").

## Why this repository uses it

The lesson's demo has to start a real server, wait for it, run a scenario against it, stop it cleanly, and show that it stopped cleanly. That is gluing programs together, which is what a shell is for.

## Where it appears

| Path | What it does with Bash |
| --- | --- |
| `scripts/demo.sh` | Starts gunicorn in the background, waits for `/readyz`, runs the scenario, sends SIGTERM, prints the shutdown lines. |
| `Makefile` | Recipes use `if [ ... ]; then ...; fi`, `for file in ...; do ...; done`, pipes and redirects. |
| `docker-compose.yml` | The health check uses `CMD-SHELL`, which runs its text through a shell. |
| `.github/workflows/ci.yml` | Each `run:` line is executed by a shell on the CI machine. |

## How it works underneath

1. You type `ls -l /tmp`. Bash splits the line into **words**: `ls`, `-l`, `/tmp`. The first word is the command; the rest are **arguments**.
2. Bash finds the program (it searches the folders listed in the `PATH` variable), asks the operating system to start a new process for it, and waits.
3. When the program ends, Bash stores its exit code in the special variable `$?`.
4. `&` after a command starts it **in the background**: Bash does not wait. `$!` then holds the new process's id.
5. A **pipe** `a | b` connects a's stdout to b's stdin; both run at once.
6. A **redirect** `> file` sends stdout to a file; `2> file` sends stderr; `2>&1` sends stderr to wherever stdout goes; `< file` feeds a file to stdin.

### Ideas you need first

- **A terminal and a shell.** A terminal is a window where you type text commands instead of clicking. The program that reads what you type is the shell; Bash is one shell. You type a line, press Enter, and the shell runs it.
- **A command, its arguments and its flags.** A command is the name of a program (`ls`, `make`, `docker`). What follows are **arguments**: extra words that tell it what to work on. A **flag** (or option) is an argument that starts with `-` or `--` and changes how the command behaves, such as `-l` or `--help`.
- **A directory, a path and the working directory.** A directory is a folder. A path names a file by listing the folders to open: `scripts/demo.sh` means "the file `demo.sh` inside the folder `scripts`". The **working directory** is the folder you are "in"; relative paths are read from there. `.` means "this folder", `..` means "the folder above".
- **`PATH`.** An environment variable holding a list of folders. When you type `gunicorn`, the shell looks through those folders, in order, for a program with that name. A path with a slash (`.venv/bin/gunicorn`) names the program directly and skips the search.
- **An environment variable.** A named piece of text given to a process when it starts. `NAME=value command` sets one for a single command; `export NAME=value` sets it for the shell and every program it starts afterwards.
- **A process and its exit code.** Running a command starts a process. When it ends it returns a number: 0 means success, anything else means failure. The shell stores the last one in `$?`.
- **Standard input, output and error.** Every process has three text streams: input it reads (stdin, 0), normal output (stdout, 1) and error output (stderr, 2). A **redirect** sends one somewhere else: `> file` writes stdout to a file, `2> file` writes stderr, `2>&1` sends stderr to wherever stdout goes, `< file` reads stdin from a file. `/dev/null` is a special file that throws away whatever is written to it.
- **A pipe.** `a | b` connects a's stdout to b's stdin, so b reads what a prints. Both run at the same time.
- **A file descriptor.** The number the operating system gives to an open stream. 0, 1 and 2 are the three standard ones; you can open more (`exec 3<>...` below).
- **A background process and a signal.** A trailing `&` starts a command without waiting for it. A **signal** is a message the operating system sends to a process; `SIGTERM` means "please stop", and a well-written program cleans up and exits when it gets one.
- **A variable and quoting.** `NAME=value` sets a shell variable; `$NAME` reads it. Double quotes (`"$NAME"`) keep a value with spaces as one word. Single quotes (`'...'`) pass the text exactly as written. `$(command)` runs a command and substitutes its output.
- **A script and the shebang.** A script is a text file of commands. Its first line, `#!/usr/bin/env bash`, tells the operating system which program should run the file. The file must be marked executable (`chmod +x`).

## Walkthrough of this repository's use

### `scripts/demo.sh`

```bash
#!/usr/bin/env bash
```
The first line (the **shebang**) tells the operating system which program runs this file. `env bash` finds `bash` wherever it is installed.

```bash
set -euo pipefail
```
Three safety switches. `-e`: stop the script when any command fails. `-u`: treat use of an unset variable as an error (catches typos). `-o pipefail`: a pipeline fails if *any* command in it fails, not only the last one. Without these, a script keeps going after errors and reports success.

```bash
PY=.venv/bin/python
LOG=$(mktemp)
```
`PY` is a variable holding a path. `$(...)` runs a command and substitutes its output; `mktemp` creates an empty temporary file and prints its name, so `LOG` holds a unique file name for the server's log.

```bash
.venv/bin/gunicorn -c python:notes_app.interfaces.gunicorn_conf "notes_app.interfaces.wsgi:build_app()" 2>"$LOG" &
SERVER=$!
```
Starts the real server (see `tech/gunicorn.md`). `2>"$LOG"` redirects stderr (where gunicorn and the app write their JSON logs) into the temp file. The double quotes keep the `build_app()` text as one argument; without quotes the parentheses would be shell syntax. `&` puts it in the background and `SERVER=$!` remembers its process id.

```bash
trap 'kill -TERM "$SERVER" 2>/dev/null || true' EXIT
```
A **trap** runs a command when something happens. `EXIT` means "when the script ends, however it ends". So even if a later line fails and `set -e` aborts the script, the server is still told to stop. `2>/dev/null` throws away error text (for example "no such process" when it is already gone), and `|| true` turns a failure into success so the trap itself cannot fail.

```bash
for _ in $(seq 1 40); do
  if .venv/bin/notes-app-health >/dev/null 2>&1; then break; fi
  sleep 0.5
done
.venv/bin/notes-app-health
```
Wait up to 40 times, half a second apart (20 seconds). `seq 1 40` prints 1 to 40; `_` is a throwaway loop variable. The health program exits 0 when `/readyz` answers 200; `>/dev/null 2>&1` hides its output; `break` leaves the loop on success. The last line runs the check once more and, because of `set -e`, aborts the script if the server never became ready.

```bash
status=0
$PY -m notes_app.interfaces.demo_cli || status=$?
```
Run the scenario. `a || b` runs `b` only if `a` failed, and it also stops `set -e` from aborting. `status=$?` saves the scenario's exit code so the script can still print the shutdown evidence and then exit with that code at the end.

```bash
grep '"message":"audit"' "$LOG" | cut -c1-230 | tail -n 8 || true
```
Search the log for audit lines, keep the first 230 characters of each, show the last 8. A pipe of three programs. `|| true` keeps `set -e` quiet if no audit line exists (`grep` returns 1 when it finds nothing).

```bash
kill -TERM "$SERVER"
wait "$SERVER" || true
trap - EXIT
```
Send SIGTERM, wait for the server process to finish, then remove the trap so it does not run a second time. `wait` returns the server's exit code, which could be non-zero, hence `|| true`.

```bash
grep -E 'Handling signal|database pool closed|Shutting down' "$LOG" | cut -c1-160
rm -f "$LOG"
exit "$status"
```
Prove the shutdown was graceful by printing the three log lines that show it, delete the temp file, and exit with the scenario's code.

### Shell inside the `Makefile`

```make
@if [ "$$($(PSQL) -tAc "SELECT to_regclass('public.users') IS NOT NULL")" = "t" ]; then \
  echo "schema already present"; else $(MAKE) --no-print-directory db; fi
```
`$$` is how a Makefile writes a literal `$` for the shell. `$$( ... )` runs the `psql` command and captures its output; `[ "..." = "t" ]` is the test command comparing it to the letter `t`; the trailing `\` continues the line. Meaning: if the table `users` exists, say so, otherwise run the `db` target.

```make
@for file in sql/migrations/*.sql; do echo "migrate $$file"; $(PSQL) < $$file; done
```
Loops over each migration file (the shell expands the `*` in alphabetical order, which is why the files are numbered) and feeds it to `psql` through `<`.

```make
@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | sort
```
The `help` target: `grep -h` prints matching lines without file names, `sed` turns `target: deps ## text` into `target<TAB>text`, `sort` orders them.

```yaml
test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
```
In `docker-compose.yml`. `CMD-SHELL` means "run this string through `/bin/sh`". `$$` stops Compose from replacing the variable itself, so the shell inside the container expands it.

## Try it yourself

1. Watch the safety switches work:
   ```bash
   bash -c 'set -euo pipefail; false; echo "not reached"'; echo "exit code: $?"
   ```
   Expect only `exit code: 1`.
2. See what a pipeline does without `pipefail`:
   ```bash
   bash -c 'false | true; echo "exit: $?"'; bash -c 'set -o pipefail; false | true; echo "exit: $?"'
   ```
   Expect `exit: 0`, then `exit: 1`.
3. Read the script as the shell sees it, without running it:
   ```bash
   bash -n scripts/demo.sh && echo "syntax ok"
   ```
   Expect `syntax ok`.
4. Watch a trap fire (this is the pattern in `demo.sh`):
   ```bash
   bash -c 'trap "echo cleaning up" EXIT; echo working; exit 3'; echo "code $?"
   ```
   Expect `working`, `cleaning up`, `code 3`.
5. With the database up (`make up`), run `make demo`. Expect the numbered steps from the scenario, then the audit lines, then `Handling signal: term` and `database pool closed` from the shutdown.

## Mistakes people make

- Forgetting quotes: `rm -f $LOG` breaks when the value contains a space. The script quotes every variable.
- No `set -e`: a failed step is ignored and the script says "success". Here the script stops on failure and still cleans up through the `EXIT` trap.
- Leaving a background server running when the script dies. The trap solves it.
- Using `|| true` everywhere, which hides real failures. This script uses it only where "no output" or "already gone" is an acceptable outcome, and saves the real status in `status`.
- Parsing `ls` output, or relying on `echo` flags that differ between shells. The script avoids both.

## Check yourself

1. What does `set -e` change?
   *The script exits as soon as a command fails.*
2. What does `trap '...' EXIT` guarantee?
   *The command runs when the script ends, whether it finished or failed.*
3. Why `2>"$LOG"` on the gunicorn line?
   *To send stderr (where the structured logs go) to a file the script can search later.*
4. Why does the Makefile write `$$file` instead of `$file`?
   *Make would otherwise treat `$file` as its own variable; `$$` passes a literal `$` to the shell.*
5. What does `wait "$SERVER" || true` do?
   *Waits for the background process to finish and ignores its exit code so `set -e` does not abort the script.*

## Further reading

- GNU Bash manual (this machine runs Bash 5.3): https://www.gnu.org/software/bash/manual/bash.html
- The `set` builtin: https://www.gnu.org/software/bash/manual/bash.html#The-Set-Builtin
- `trap`: https://www.gnu.org/software/bash/manual/bash.html#index-trap
