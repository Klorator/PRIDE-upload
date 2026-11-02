# make_checksums.py
# Step 2 of the submission workflow. Reads the curated list of files from
# tools\checksum_input.txt, finds each file under the project folder (the
# parent of the tools folder), computes SHA-1 checksums in parallel, and writes
# tools\checksum.txt as  file name <TAB> sha1  (one line per file, same order
# as the input). Nothing outside the tools folder is created or modified.
#
# Input format (see checksum_input.txt):
#   - one file name per line; blank lines and lines starting with # are ignored
#   - a line that is a folder path applies to the file names below it, so whole
#     blocks can be pasted from the _filelists\*.txt files
#   - file names without a folder line, or not found in that folder, are looked
#     up anywhere in the project folder and must match exactly one file
# The script does not guess. If any name is missing, matches more than one file,
# or is listed twice, it reports the problem and writes nothing.
#
# Progress is printed as each file finishes (count, name, folder, size, time
# taken, amount done so far). Results are also saved to tools\checksum_cache.tsv, so
# files that are unchanged since an earlier run (same path, size and
# modification time) are not checksummed again, and an interrupted run resumes.
#
# Only the Python 3.6+ standard library is used.
# Run by double-clicking run_checksums.bat, or:
#   python make_checksums.py [path\to\other_input.txt]

import hashlib
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

CHUNK = 4 * 1024 * 1024  # 4 MB read blocks
SKIP_DIRS = {".git", ".posit"}


def sha1_of_file(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def work(path):
    """Runs in a worker process. Returns (digest, error, seconds)."""
    start = time.monotonic()
    try:
        digest = sha1_of_file(path)
        return digest, None, time.monotonic() - start
    except (OSError, IOError) as e:
        return None, str(e), time.monotonic() - start


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return ("%d %s" % (n, unit)) if unit == "B" else ("%.1f %s" % (n, unit))
        n /= 1024.0


def fmt_time(seconds):
    seconds = int(round(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    if h:
        return "%dh %02dm %02ds" % (h, m, s)
    if m:
        return "%dm %02ds" % (m, s)
    return "%ds" % s


# ---------------------------------------------------------------------------
# Cache of earlier results: sha1 <TAB> size <TAB> mtime_ns <TAB> full path.
# A cached checksum is reused only if the file's size and modification time are
# unchanged, so edited or replaced files are always checksummed again.
def cache_key(path):
    return os.path.normcase(os.path.abspath(path))


def load_cache(cache_path):
    cache = {}
    if not os.path.isfile(cache_path):
        return cache
    with open(cache_path, encoding="utf-8") as f:
        for line in f:
            parts = line.rstrip("\n").split("\t")
            if len(parts) != 4 or line.startswith("#"):
                continue
            digest, size, mtime, path = parts
            try:
                cache[cache_key(path)] = (digest, int(size), int(mtime))
            except ValueError:
                continue
    return cache


def read_lines(path):
    # Notepad may save as UTF-8 (with or without BOM) or as the Windows ANSI code page
    try:
        with open(path, encoding="utf-8-sig") as f:
            return f.read().splitlines()
    except UnicodeDecodeError:
        with open(path, encoding="mbcs" if os.name == "nt" else "latin-1") as f:
            return f.read().splitlines()


def parse_input(path, project_dir):
    """Return a list of (line number, folder or None, name)."""
    entries = []
    folder = None
    for n, raw in enumerate(read_lines(path), 1):
        line = raw.strip().strip('"').strip()
        if not line or line.startswith("#"):
            continue
        candidate = line if os.path.isabs(line) else os.path.join(project_dir, line)
        looks_like_path = "\\" in line or "/" in line or ":" in line
        if (
            looks_like_path
            and os.path.isdir(candidate)
            and not line.lower().endswith(".d")
        ):
            folder = candidate
            continue
        entries.append((n, folder, line))
    return entries


def index_project(project_dir, tools_dir):
    """Map lowercase file name -> list of full paths under project_dir."""
    index = {}
    tools_dir = os.path.normcase(os.path.abspath(tools_dir))
    for dirpath, dirnames, filenames in os.walk(project_dir):
        dirnames[:] = [
            d
            for d in dirnames
            if d.lower() not in SKIP_DIRS
            and os.path.normcase(os.path.abspath(os.path.join(dirpath, d))) != tools_dir
        ]
        for fn in filenames:
            index.setdefault(fn.lower(), []).append(os.path.join(dirpath, fn))
    return index


def resolve(folder, name, index, project_dir):
    """Return (path, problem). Exactly one of them is None."""
    in_folder = os.path.join(folder, name) if folder else None
    if os.path.isabs(name):
        path = name
    elif in_folder and os.path.exists(in_folder):
        path = in_folder
    elif os.path.exists(os.path.join(project_dir, name)):
        path = os.path.join(project_dir, name)
    else:
        # Not in the current folder (or no folder given): look everywhere,
        # but only accept a single match
        matches = index.get(os.path.basename(name).lower(), [])
        if not matches:
            return None, "not found anywhere in the project folder"
        if len(matches) > 1:
            listing = "\n".join(
                "        " + os.path.relpath(m, project_dir) for m in matches
            )
            return None, (
                "found in %d places - add the folder path on a line above it:\n%s"
                % (len(matches), listing)
            )
        path = matches[0]

    if os.path.isfile(path):
        return path, None
    if os.path.isdir(path):
        return None, "is a folder, not a file (Bruker .d folders must be zipped first)"
    return None, "not found"


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(here)
    input_path = (
        sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, "checksum_input.txt")
    )

    if not os.path.isfile(input_path):
        print("Input file not found: %s" % input_path)
        return finish(1)

    entries = parse_input(input_path, project_dir)
    if not entries:
        print("No file names in %s - paste the file names into it first." % input_path)
        return finish(1)

    print("Looking up %d file name(s) under %s ..." % (len(entries), project_dir))
    index = index_project(project_dir, here)

    problems = []
    resolved = []  # full paths, in input order
    seen_paths = set()
    seen_names = {}  # lowercase file name -> path
    for n, folder, name in entries:
        path, problem = resolve(folder, name, index, project_dir)
        if problem:
            problems.append("line %d: %s - %s" % (n, name, problem))
            continue
        key = os.path.normcase(os.path.abspath(path))
        if key in seen_paths:
            problems.append("line %d: %s - listed more than once" % (n, name))
            continue
        base = os.path.basename(path).lower()
        if base in seen_names:
            problems.append(
                "line %d: %s - another file with the same name is already listed (%s); "
                "file names must be unique in a PRIDE submission"
                % (n, name, os.path.relpath(seen_names[base], project_dir))
            )
            continue
        seen_paths.add(key)
        seen_names[base] = path
        resolved.append(path)

    if problems:
        print(
            "\nNothing was written. Fix these lines in %s and run again:\n" % input_path
        )
        for p in problems:
            print("  " + p)
        return finish(1)

    # ---- Reuse checksums from earlier runs when the file is unchanged --------
    cache_path = os.path.join(here, "checksum_cache.tsv")
    cache = load_cache(cache_path)
    digests = {}
    todo = []  # (path, size, mtime_ns)
    for path in resolved:
        st = os.stat(path)
        hit = cache.get(cache_key(path))
        if hit and hit[1] == st.st_size and hit[2] == st.st_mtime_ns:
            digests[path] = hit[0]
        else:
            todo.append((path, st.st_size, st.st_mtime_ns))

    total_bytes = sum(size for _, size, _ in todo)
    print("\n%d file(s) in the list:" % len(resolved))
    print("  %d already done in an earlier run and unchanged (reused)" % len(digests))
    print("  %d to checksum now, %s in total\n" % (len(todo), fmt_size(total_bytes)))
    for path in resolved:
        if path in digests:
            print("  reused   %s" % os.path.relpath(path, project_dir))
    if digests:
        print("")

    # ---- Compute the rest in parallel, reporting each file as it finishes ----
    errors = []
    start = time.monotonic()
    if todo:
        n_workers = max(1, min(32, os.cpu_count() or 4, len(todo)))
        print(
            "Checksumming with %d parallel worker(s). A line is printed as each "
            "file finishes; large files can take several minutes each.\n" % n_workers
        )
        done_bytes = 0
        # Nested "with" blocks on purpose: the bracketed multi-item form needs
        # Python 3.10+, and this script must run on Python 3.6.
        with open(cache_path, "a", encoding="utf-8", newline="\n") as cache_out:
            with ProcessPoolExecutor(max_workers=n_workers) as ex:
                futures = {
                    ex.submit(work, p): (p, size, mtime) for p, size, mtime in todo
                }
                for i, fut in enumerate(as_completed(futures), 1):
                    path, size, mtime = futures[fut]
                    digest, err, secs = fut.result()
                    done_bytes += size
                    elapsed = time.monotonic() - start
                    if err:
                        errors.append((path, err))
                        status = "FAILED"
                    else:
                        digests[path] = digest
                        # Saved immediately, so an interrupted run can be resumed
                        cache_out.write(
                            "%s\t%d\t%d\t%s\n"
                            % (digest, size, mtime, os.path.abspath(path))
                        )
                        cache_out.flush()
                        status = "done  "
                    print(
                        "[%d/%d] %s %s  (%s in %s)   %s of %s done, total elapsed %s"
                        % (
                            i,
                            len(todo),
                            status,
                            os.path.basename(path),
                            fmt_size(size),
                            fmt_time(secs),
                            fmt_size(done_bytes),
                            fmt_size(total_bytes),
                            fmt_time(elapsed),
                        )
                    )
                    print(
                        "         in %s"
                        % os.path.dirname(os.path.relpath(path, project_dir))
                    )
                    sys.stdout.flush()

    if errors:
        print("\nchecksum.txt was NOT written. These files could not be read:\n")
        for p, e in errors:
            print("  %s - %s" % (p, e))
        print(
            "\nFiles that did finish are saved and will be reused when you run again."
        )
        return finish(1)

    out_path = os.path.join(here, "checksum.txt")
    with open(out_path, "w", encoding="utf-8", newline="\n") as out:
        for path in resolved:
            out.write("%s\t%s\n" % (os.path.basename(path), digests[path]))

    print(
        "\nFinished in %s. %d checksums written to %s"
        % (fmt_time(time.monotonic() - start), len(resolved), out_path)
    )
    return finish(0)


def finish(code):
    try:
        input("Press Enter to close...")
    except EOFError:
        pass
    return code


if __name__ == "__main__":
    sys.exit(main())
