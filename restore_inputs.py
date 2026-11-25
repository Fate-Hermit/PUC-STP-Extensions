#!/usr/bin/env python3
"""Restore the 47 BIP86 matrices from the accompanying verified ZIP parts.

Run with Python 3.8 or later. Only the Python standard library is required.
All paths are relative to this script, regardless of the current directory.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import zipfile


ARCHIVE_BYTES = 444316566
ARCHIVE_SHA256 = "0b5159ae3e8204b73398a06ddc7843042d1f33d5f021d9395cd11e9d9df87152"
ARCHIVE_NAME = "STP-Benchmark-Review.zip"
ARCHIVE_PREFIX = "STP-Benchmark-Review/BIP86/scp/"
MATRIX_COUNT = 47
PART_BYTES = 7 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
HEX_SHA256 = re.compile(r"[0-9a-f]{64}")
MATRIX_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *]scp/([A-Za-z0-9][A-Za-z0-9_.-]*\.txt)")


class RestoreError(Exception):
    pass


def require(condition, message):
    if not condition:
        raise RestoreError(message)


def checked_path(path, directory=False):
    """Reject symlinks and Windows junctions/reparse points before local I/O."""
    info = path.lstat()
    require(not stat.S_ISLNK(info.st_mode), "Symbolic link is not allowed: {}".format(path))
    attributes = getattr(info, "st_file_attributes", 0)
    require(not attributes & 0x400, "Reparse point is not allowed: {}".format(path))
    predicate = stat.S_ISDIR if directory else stat.S_ISREG
    require(predicate(info.st_mode), "Expected a {}: {}".format("directory" if directory else "regular file", path))


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def unique_json_keys(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate manifest key: {}".format(key))
        result[key] = value
    return result


def read_manifest(parts_dir):
    checked_path(parts_dir, directory=True)
    manifest_path = parts_dir / "manifest.json"
    checked_path(manifest_path)
    with manifest_path.open("r", encoding="utf-8") as source:
        manifest = json.load(source, object_pairs_hook=unique_json_keys)
    require(isinstance(manifest, dict), "Manifest must be a JSON object.")
    require(type(manifest.get("schema_version")) is int and manifest["schema_version"] == 1,
            "Unsupported manifest schema_version.")
    require(manifest.get("archive_prefix") == ARCHIVE_PREFIX, "Manifest archive_prefix does not match this snapshot.")
    require(type(manifest.get("expected_matrix_count")) is int and manifest["expected_matrix_count"] == MATRIX_COUNT,
            "Manifest expected_matrix_count must be 47.")
    require(type(manifest.get("part_size_bytes")) is int and manifest["part_size_bytes"] == PART_BYTES,
            "Manifest part_size_bytes does not match this snapshot.")
    archive = manifest.get("archive")
    require(isinstance(archive, dict), "Manifest archive must be an object.")
    require(archive.get("file") == ARCHIVE_NAME, "Manifest archive filename does not match this snapshot.")
    require(type(archive.get("bytes")) is int and archive["bytes"] == ARCHIVE_BYTES,
            "Manifest archive size does not match this snapshot.")
    require(archive.get("sha256") == ARCHIVE_SHA256, "Manifest archive SHA256 does not match this snapshot.")
    parts = manifest.get("parts")
    count = (ARCHIVE_BYTES + PART_BYTES - 1) // PART_BYTES
    require(isinstance(parts, list) and len(parts) == count, "Manifest must list exactly {} parts.".format(count))
    for index, part in enumerate(parts, 1):
        require(isinstance(part, dict), "Part {} must be an object.".format(index))
        expected_name = "part-{:03d}.bin".format(index)
        expected_bytes = min(PART_BYTES, ARCHIVE_BYTES - (index - 1) * PART_BYTES)
        require(part.get("file") == expected_name, "Expected manifest part filename {}.".format(expected_name))
        require(type(part.get("bytes")) is int and part["bytes"] == expected_bytes,
                "Incorrect manifest size for {}.".format(expected_name))
        require(isinstance(part.get("sha256"), str) and HEX_SHA256.fullmatch(part["sha256"]),
                "Invalid SHA256 for {}.".format(expected_name))
    return parts


def read_expected_hashes(bip_dir):
    checked_path(bip_dir, directory=True)
    checksum_path = bip_dir / "source_files.sha256"
    checked_path(checksum_path)
    expected = {}
    seen_names = set()
    with checksum_path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, 1):
            line = line.rstrip("\r\n")
            match = MATRIX_LINE.fullmatch(line)
            require(match is not None, "Invalid source_files.sha256 line {}.".format(line_number))
            digest, name = match.groups()
            require(name.casefold() not in seen_names, "Duplicate matrix checksum: {}".format(name))
            seen_names.add(name.casefold())
            expected[name] = digest.lower()
    require(len(expected) == MATRIX_COUNT, "source_files.sha256 must list exactly 47 matrices.")
    return expected


def assemble_archive(parts_dir, parts, archive_path):
    archive_digest = hashlib.sha256()
    total = 0
    with archive_path.open("xb") as destination:
        for index, part in enumerate(parts, 1):
            path = parts_dir / part["file"]
            checked_path(path)
            require(path.stat().st_size == part["bytes"], "Part size mismatch: {}".format(part["file"]))
            digest = hashlib.sha256()
            size = 0
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    size += len(chunk)
                    require(size <= part["bytes"], "Part grew while being read: {}".format(part["file"]))
                    digest.update(chunk)
                    archive_digest.update(chunk)
                    destination.write(chunk)
            require(size == part["bytes"], "Part size mismatch while reading: {}".format(part["file"]))
            require(digest.hexdigest() == part["sha256"], "Part SHA256 mismatch: {}".format(part["file"]))
            total += size
            print("Verified part {}/{}: {}".format(index, len(parts), part["file"]), flush=True)
    require(total == ARCHIVE_BYTES, "Reassembled ZIP size mismatch.")
    require(archive_digest.hexdigest() == ARCHIVE_SHA256, "Reassembled ZIP SHA256 mismatch.")
    print("Verified complete ZIP SHA256.", flush=True)


def inspect_archive(archive, expected):
    selected = {}
    seen = set()
    for member in archive.infolist():
        name = member.filename
        require(name and "\\" not in name and ":" not in name and "\x00" not in name,
                "Unsafe ZIP member name: {!r}".format(name))
        require(not name.startswith("/"), "Absolute ZIP member path: {!r}".format(name))
        components = name.rstrip("/").split("/")
        require(all(component not in ("", ".", "..") for component in components),
                "Unsafe ZIP member path: {!r}".format(name))
        normalized = "/".join(components).casefold()
        require(normalized not in seen, "Duplicate ZIP member: {!r}".format(name))
        seen.add(normalized)
        mode = member.external_attr >> 16
        kind = stat.S_IFMT(mode)
        require(kind in (0, stat.S_IFDIR, stat.S_IFREG), "Link or special file in ZIP: {!r}".format(name))
        require(not member.external_attr & 0x400, "Reparse point in ZIP: {!r}".format(name))
        require(not member.flag_bits & 1, "Encrypted ZIP member is unsupported: {!r}".format(name))
        if name.startswith(ARCHIVE_PREFIX) and not member.is_dir():
            relative = name[len(ARCHIVE_PREFIX):]
            require(relative in expected and "/" not in relative,
                    "Unexpected matrix ZIP member: {!r}".format(name))
            require(relative not in selected, "Duplicate matrix ZIP member: {!r}".format(name))
            selected[relative] = member
    require(set(selected) == set(expected), "ZIP does not contain exactly the 47 expected matrices.")
    return selected


def extract_verified(archive_path, staging_dir, expected):
    staging_dir.mkdir()
    with zipfile.ZipFile(archive_path, "r") as archive:
        selected = inspect_archive(archive, expected)
        for name, digest in expected.items():
            output_path = staging_dir / name
            actual = hashlib.sha256()
            size = 0
            with archive.open(selected[name], "r") as source, output_path.open("xb") as destination:
                for chunk in iter(lambda: source.read(CHUNK_BYTES), b""):
                    actual.update(chunk)
                    size += len(chunk)
                    destination.write(chunk)
            require(size == selected[name].file_size, "Extracted size mismatch: {}".format(name))
            require(actual.hexdigest() == digest, "Matrix SHA256 mismatch: {}".format(name))
    print("Verified all 47 matrices against BIP86/source_files.sha256.", flush=True)


def install(staging_dir, target_dir, expected):
    # All archive and matrix checks finish before any destination file is written.
    if not os.path.lexists(str(target_dir)):
        os.rename(str(staging_dir), str(target_dir))
        return
    checked_path(target_dir, directory=True)
    missing = []
    for name, digest in expected.items():
        path = target_dir / name
        if os.path.lexists(str(path)):
            checked_path(path)
            require(file_sha256(path) == digest,
                    "Existing file differs; left untouched: {}. Move it aside before retrying.".format(path))
        else:
            missing.append(name)
    # Hard links add each already verified file atomically without overwriting.
    # The staging directory is on the same filesystem as the destination.
    for name in missing:
        destination = target_dir / name
        try:
            os.link(str(staging_dir / name), str(destination))
        except FileExistsError:
            checked_path(destination)
            require(file_sha256(destination) == expected[name],
                    "A conflicting file appeared during installation: {}".format(destination))
        except OSError as error:
            raise RestoreError("Cannot install {} atomically ({}). Previously installed files are valid; "
                               "move the existing BIP86/scp directory aside and retry.".format(destination, error)) from error
    for name, digest in expected.items():
        checked_path(target_dir / name)
        require(file_sha256(target_dir / name) == digest, "Final verification failed: {}".format(name))


def main():
    root = Path(__file__).resolve().parent
    bip_dir = root / "BIP86"
    parts_dir = root / "data-parts"
    parts = read_manifest(parts_dir)
    expected = read_expected_hashes(bip_dir)
    # The temporary archive and fully checked extraction are always cleaned up.
    # Keeping staging next to BIP86 also permits atomic directory installation.
    with tempfile.TemporaryDirectory(prefix=".restore-inputs-", dir=str(root)) as temporary:
        temporary_dir = Path(temporary)
        archive_path = temporary_dir / ARCHIVE_NAME
        staging_dir = temporary_dir / "scp"
        assemble_archive(parts_dir, parts, archive_path)
        extract_verified(archive_path, staging_dir, expected)
        install(staging_dir, bip_dir / "scp", expected)
    print("Restored and verified 47 matrices in {}".format(bip_dir / "scp"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("ERROR: Restoration interrupted. Run the script again to retry.", file=sys.stderr)
        sys.exit(1)
    except (RestoreError, OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
        print("ERROR: {}".format(error), file=sys.stderr)
        sys.exit(1)
