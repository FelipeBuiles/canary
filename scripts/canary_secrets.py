#!/usr/bin/env python3
"""Portable app secret boundary. Never emit plaintext or exception details.

Only the private exporter writes plaintext, to a parent-owned pipe. This file
is standalone so the exact reviewed exporter can execute on an existing Fly VM.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import grp
import hashlib
import hmac
import json
import os
import re
import resource
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

REQUIRED = frozenset({
    "LITELLM_MASTER_KEY", "LITELLM_API_KEY", "LITELLM_SALT_KEY",
    "CANARY_OPS_TOKEN", "SUPABASE_SECRET_KEY", "CANARY_QUEUE_DATABASE_URL",
    "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET",
})
OPTIONAL = frozenset({
    "CANARY_TEXTRACT_ACCESS_KEY_ID", "CANARY_TEXTRACT_SECRET_ACCESS_KEY", "CANARY_TEXTRACT_SESSION_TOKEN",
    "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "FAL_KEY", "FAL_ADMIN_KEY", "RUNWARE_API_KEY", "OPENROUTER_API_KEY",
    "TOGETHER_API_KEY", "R2_ACCESS_KEY", "R2_SECRET_KEY", "DATABASE_URL",
    "AWS_BEARER_TOKEN_BEDROCK",
})
ALLOWED = REQUIRED | OPTIONAL
ADC_NAME = "google-adc.json"
ADC_PATH = "/run/credentials/google-adc.json"
MAX_BYTES = 1024 * 1024
DIGEST = re.compile(r"[a-f0-9]{64}")
RECIPIENT = re.compile(r"age1[0-9a-z]{58}")
# Key sources other than the pinned age recipients. sops reads several of these
# from SOPS_* environment variables, so a stray variable could add a decryptor.
FOREIGN_KEY_SOURCES = ("kms", "gcp_kms", "azure_kv", "hc_vault", "pgp", "key_groups",
                       "shamir_threshold", "keyservices")
ENTRYPOINT = b"/app/entrypoint.sh"


class SecretError(Exception):
    """Messages are fixed codes, never untrusted input or secret fragments."""


def reject(code: str):
    raise SecretError(code)


def pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            reject("duplicate_field")
        result[key] = value
    return result


def parse(raw: bytes | str):
    if len(raw) > MAX_BYTES:
        reject("oversize")
    try:
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError):
        reject("invalid_json")


def validate_adc(raw: str):
    adc = parse(raw)
    if not isinstance(adc, dict):
        reject("invalid_adc")
    required = {
        "authorized_user": {"client_id", "client_secret", "refresh_token"},
        "service_account": {"client_email", "private_key", "token_uri"},
        "impersonated_service_account": {"service_account_impersonation_url", "source_credentials"},
    }.get(adc.get("type"))
    if required is None or any(not adc.get(k) for k in required):
        reject("invalid_adc")
    if adc["type"] == "impersonated_service_account":
        validate_adc(json.dumps(adc["source_credentials"]))


def validate(bundle):
    if not isinstance(bundle, dict) or set(bundle) != {"version", "env", "files"}:
        reject("invalid_schema")
    if type(bundle["version"]) is not int or bundle["version"] != 1:
        reject("unsupported_version")
    env, files = bundle["env"], bundle["files"]
    if not isinstance(env, dict) or not REQUIRED <= env.keys() or not env.keys() <= ALLOWED:
        reject("invalid_secret_names")
    if any(not isinstance(v, str) or not v or "\0" in v for v in env.values()):
        reject("invalid_secret_value")
    if env["LITELLM_API_KEY"] != env["LITELLM_MASTER_KEY"]:
        reject("gateway_key_mismatch")
    if ("R2_ACCESS_KEY" in env) != ("R2_SECRET_KEY" in env):
        reject("incomplete_r2_pair")
    if ("CANARY_TEXTRACT_ACCESS_KEY_ID" in env) != ("CANARY_TEXTRACT_SECRET_ACCESS_KEY" in env):
        reject("incomplete_textract_pair")
    if "CANARY_TEXTRACT_SESSION_TOKEN" in env and "CANARY_TEXTRACT_ACCESS_KEY_ID" not in env:
        reject("incomplete_textract_pair")
    if not isinstance(files, dict) or not files.keys() <= {ADC_NAME}:
        reject("invalid_file_names")
    for value in files.values():
        if not isinstance(value, str) or "\0" in value:
            reject("invalid_file_value")
        validate_adc(value)
    return bundle


def private_read(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            reject("unsafe_file_permissions")
        return stream.read(MAX_BYTES + 1)


def homebrew_directory_allowed(path: Path, directory: Path, info) -> bool:
    """Explicit non-root macOS opt-in trusts admin-group writes inside Homebrew.

    Linux hosts cannot enable this exception, even with the same environment.
    Executable files, ownership, world writes and ancestors above the prefix
    retain their normal checks.
    """
    if (os.environ.get("CANARY_ALLOW_HOMEBREW_TOOLS") != "1"
            or sys.platform != "darwin" or os.geteuid() == 0):
        return False
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & stat.S_IWOTH:
        return False
    prefixes = (Path("/opt/homebrew"), Path("/usr/local"))
    if not any(path.is_relative_to(prefix / "Cellar")
               and directory.is_relative_to(prefix) for prefix in prefixes):
        return False
    try:
        return info.st_gid == grp.getgrnam("admin").gr_gid
    except KeyError:
        return False


def trusted_tool(name: str) -> str:
    """Check tool ownership and path writes, with an opt-in local Homebrew exception."""
    found = shutil.which(name)
    if not found:
        reject("tool_missing")
    path = Path(found).resolve()
    # Any writable ancestor lets another user swap a whole subtree, so check up to /.
    # A sticky shared directory (e.g. /tmp) is fine: others cannot rename or
    # delete the trusted entry beneath it, which is itself checked.
    for item in (path, *path.parents):
        info = item.stat()
        writable = info.st_mode & 0o022
        sticky_dir = item != path and info.st_mode & stat.S_ISVTX
        brew_directory = item != path and homebrew_directory_allowed(path, item, info)
        if info.st_uid not in (0, os.geteuid()) or (writable and not sticky_dir and not brew_directory):
            reject("untrusted_tool")
    return str(path)


def tool_env(**extra):
    # No inherited SOPS_*, cloud credentials or config search: only what is pinned here.
    return {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), **extra}


def sops(*args) -> list[str]:
    # An empty config disables any .sops.yaml creation rule (e.g. unencrypted_regex).
    return [trusted_tool("sops"), "--config", os.devnull, *args]


def checked_process(argv, *, data=None, env=None) -> bytes:
    # Never relay third-party stderr: parsers/SDKs can echo their secret input.
    result = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, env=env, timeout=120, check=False)
    if result.returncode:
        reject("subprocess_failed")
    return result.stdout


def sops_env(identity: Path):
    private_read(identity)
    return tool_env(SOPS_AGE_KEY_FILE=str(identity.resolve()))


def read_ciphertext(bundle: Path, expected: str) -> bytes:
    raw = bundle.read_bytes()
    if not DIGEST.fullmatch(expected) or hashlib.sha256(raw).hexdigest() != expected:
        reject("ciphertext_digest_mismatch")
    return raw


def decrypt(bundle: Path, identity: Path, expected: str):
    raw = read_ciphertext(bundle, expected)
    # Decrypt the checked bytes, not a path that could change after verification.
    plain = checked_process(sops("--decrypt", "--input-type", "json",
                                 "--output-type", "json", "/dev/stdin"),
                            data=raw, env=sops_env(identity))
    return validate(parse(plain))


def ciphertext_recipients(stored) -> set[str]:
    """The exact decryptors of a stored bundle. Anything but age recipients fails."""
    meta = stored.get("sops") if isinstance(stored, dict) else None
    if not isinstance(meta, dict):
        reject("invalid_ciphertext")
    if any(meta.get(source) for source in FOREIGN_KEY_SOURCES):
        reject("unexpected_ciphertext_recipients")
    entries = meta.get("age")
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        reject("unexpected_ciphertext_recipients")
    found = [e.get("recipient") for e in entries]
    if len(found) != len(set(found)) or not all(isinstance(r, str) and RECIPIENT.fullmatch(r) for r in found):
        reject("unexpected_ciphertext_recipients")
    return set(found)


def write_private(path: Path, value: bytes):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(value)


def publish_ciphertext(path: Path, value: bytes):
    # A failed write leaves no published bundle; link refuses existing targets.
    fd, name = tempfile.mkstemp(prefix=".canary-ciphertext-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(name, path)
    finally:
        os.unlink(name)


def require_no_swap(allow_encrypted: bool, swaps: Path = Path("/proc/swaps")):
    # tmpfs pages can be swapped to disk. Only an operator-attested encrypted swap is allowed.
    if any(line.strip() for line in swaps.read_text().splitlines()[1:]) and not allow_encrypted:
        reject("swap_enabled")


def require_tmpfs(root: Path):
    if sys.platform != "linux" or os.geteuid() != 0:
        reject("linux_root_required")
    if root != root.resolve() or not root.is_dir():
        reject("unsafe_runtime_directory")
    info = root.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        reject("unsafe_runtime_permissions")
    mounts = []
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        mount = Path(left.split()[4])
        if root == mount or mount in root.parents:
            mounts.append((len(mount.parts), right.split()[0]))
    if not mounts or max(mounts)[1] != "tmpfs":
        reject("tmpfs_required")


def materialize(bundle: dict, root: Path, digest: str, *, allow_encrypted_swap: bool = False):
    require_tmpfs(root)
    require_no_swap(allow_encrypted_swap)
    destination = root / digest
    runtime = {**bundle, "files": {}}
    # Reboot/restart is idempotent. Never mutate files used by a container.
    if destination.exists():
        if destination.is_symlink() or destination.stat().st_mode & 0o077:
            reject("unsafe_runtime_directory")
        if parse(private_read(destination / "runtime.json")) != runtime:
            reject("runtime_version_mismatch")
        credentials = destination / "credentials"
        if credentials.is_symlink() or credentials.stat().st_mode & 0o077:
            reject("unsafe_runtime_directory")
        if {p.name for p in credentials.iterdir()} != set(bundle["files"]):
            reject("runtime_version_mismatch")
        for name, value in bundle["files"].items():
            if private_read(credentials / name) != value.encode():
                reject("runtime_version_mismatch")
        return destination
    staging = Path(tempfile.mkdtemp(prefix=".prepare-", dir=root))
    try:
        write_private(staging / "runtime.json", json.dumps(runtime).encode())
        credentials = staging / "credentials"
        credentials.mkdir(mode=0o700)
        for name, value in bundle["files"].items():
            write_private(credentials / name, value.encode())
        staging.rename(destination)
    except BaseException:
        shutil.rmtree(staging)
        raise
    return destination


def mounted_roots(proc: Path) -> set[str]:
    """Every mount source path visible in any process, including container namespaces."""
    roots = set()
    for info in proc.glob("[0-9]*/mountinfo"):
        try:
            text = info.read_text()
        except OSError:
            continue  # The process exited while scanning.
        for line in text.splitlines():
            fields = line.split()
            if len(fields) > 4:
                roots.add(fields[3])
    return roots


def prune(root: Path, keep: str | None, proc: Path = Path("/proc")) -> list[str]:
    """Remove plaintext versions that no container mounts. Live mounts are never touched."""
    require_tmpfs(root)
    roots = mounted_roots(proc)
    removed = []
    for entry in sorted(root.iterdir()):
        name = entry.name
        if name == keep or not (DIGEST.fullmatch(name) or name.startswith(".prepare-")):
            continue
        if entry.is_symlink() or not entry.is_dir():
            continue
        if any(f"/{name}/" in source or source.endswith(f"/{name}") for source in roots):
            continue
        shutil.rmtree(entry)
        removed.append(name)
    return removed


def loader_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def require_loader_digest():
    # Host and image copies of this loader must both be the reviewed release.
    expected = os.environ.get("CANARY_LOADER_SHA256", "")
    if not DIGEST.fullmatch(expected) or not hmac.compare_digest(loader_digest(), expected):
        reject("loader_digest_mismatch")


def child_environment(runtime: Path):
    bundle = validate(parse(private_read(runtime)))
    if bundle["files"]:
        reject("runtime_files_must_be_separate")
    env = {k: v for k, v in os.environ.items() if k not in ALLOWED}
    env.update(bundle["env"])
    # A stale ambient AWS credential must never select an unintended account.
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                "AWS_PROFILE", "AWS_PROFILE_NAME", "AWS_CONFIG_FILE",
                "AWS_SHARED_CREDENTIALS_FILE", "CANARY_VERTEX_ADC_B64"):
        env.pop(key, None)
    if env.get("GOOGLE_APPLICATION_CREDENTIALS"):
        if env["GOOGLE_APPLICATION_CREDENTIALS"] != ADC_PATH:
            reject("invalid_adc_path")
        validate_adc(private_read(Path(ADC_PATH)).decode())
    return env


def runtime_environment(proc: Path) -> dict[str, str]:
    """The running supervisor's environment: the values the app actually uses.

    An SSH session's environment may be absent or differ from the active
    release. Values are only selected for the encrypted stream, never emitted.
    """
    candidates = []
    for cmdline in proc.glob("[0-9]*/cmdline"):
        try:
            argv = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue
        if ENTRYPOINT in argv:
            candidates.append(int(cmdline.parent.name))
    if not candidates:
        reject("runtime_process_not_found")
    # The lowest PID is the supervisor; higher ones are transient subshells.
    raw = (proc / str(min(candidates)) / "environ").read_bytes()
    env = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            env[os.fsdecode(key)] = os.fsdecode(value)
    return env


def export_active(names: list[str], with_adc: bool, proc: Path = Path("/proc")):
    if len(names) != len(set(names)) or not REQUIRED <= set(names) or not set(names) <= ALLOWED:
        reject("invalid_export_names")
    active = runtime_environment(proc)
    bundle = {"version": 1, "env": {k: active.get(k, "") for k in names}, "files": {}}
    if with_adc:
        # Fly platform permissions may differ; export does not change them.
        bundle["files"][ADC_NAME] = Path(ADC_PATH).read_text()
    return validate(bundle)


def encrypt_export(data: bytes, recipients: list[str], output: Path):
    validate(parse(data))
    validate_recipients(recipients)
    encrypted = checked_process(sops(
        "--encrypt", "--age", ",".join(recipients),
        "--input-type", "json", "--output-type", "json", "/dev/stdin",
    ), data=data, env=tool_env())
    # Fail closed if a broken resolver returns the input instead of ciphertext.
    stored = parse(encrypted)
    if not isinstance(stored, dict) or "sops" not in stored:
        reject("invalid_ciphertext")
    if ciphertext_recipients(stored) != set(recipients):
        reject("unexpected_ciphertext_recipients")
    for section in ("env", "files"):
        if not isinstance(stored.get(section), dict) or set(stored[section]) != set(parse(data)[section]):
            reject("invalid_ciphertext")
        if any(not isinstance(v, str) or not v.startswith("ENC[AES256_GCM,")
               for v in stored[section].values()):
            reject("plaintext_in_ciphertext")
    publish_ciphertext(output, encrypted)
    return hashlib.sha256(encrypted).hexdigest()


def validate_recipients(recipients):
    if len(set(recipients)) < 2 or any(not RECIPIENT.fullmatch(r) for r in recipients):
        reject("host_and_recovery_recipients_required")


# The gateway authenticates the app with its master key; they change together.
MIRRORED = {"LITELLM_MASTER_KEY": "LITELLM_API_KEY", "LITELLM_API_KEY": "LITELLM_MASTER_KEY"}


def change_values(bundle: dict, changes: dict[str, str | None]) -> dict:
    """Apply set (str) or remove (None) changes; the result must still validate."""
    updated = json.loads(json.dumps(bundle))
    for name, value in changes.items():
        if name != ADC_NAME and name not in ALLOWED:
            reject("invalid_secret_names")
        section = updated["files"] if name == ADC_NAME else updated["env"]
        targets = [name, *([MIRRORED[name]] if name in MIRRORED else [])]
        for target in targets:
            if value is None:
                if target not in section:
                    reject("name_not_present")
                del section[target]
            else:
                section[target] = value
    return validate(updated)


def read_new_values(names: list[str], remove: bool) -> dict[str, str | None]:
    if remove:
        return dict.fromkeys(names)
    if sys.stdin.isatty():
        # No echo, no shell history, no argv: the value only exists in memory.
        return {name: getpass.getpass(f"{name}: ") for name in names}
    if len(names) != 1:
        reject("multiple_names_require_tty")
    raw = sys.stdin.buffer.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        reject("oversize")
    value = raw.decode()
    return {names[0]: value.removesuffix("\n")}


def update_bundle(bundle: Path, identity: Path, expected: str, changes, recipients,
                  output: Path, change_recipients: bool):
    validate_recipients(recipients)
    current = parse(read_ciphertext(bundle, expected))
    if not change_recipients and ciphertext_recipients(current) != set(recipients):
        reject("recipient_change_requires_flag")
    updated = change_values(decrypt(bundle, identity, expected), changes)
    return encrypt_export(json.dumps(updated).encode(), recipients, output)


def export_fly(app, machine, names, with_adc, recipients, output):
    validate_recipients(recipients)
    if output.exists() or output.is_symlink():
        reject("output_exists")
    # Source and arguments contain no secret values. No remote file installation.
    source = base64.b64encode(Path(__file__).read_bytes()).decode()
    invocation = "import base64;exec(compile(base64.b64decode(" + repr(source) + "),'canary_secrets.py','exec'))"
    command = ["python3", "-c", invocation, "_export", "--names", ",".join(names)]
    if with_adc:
        command.append("--with-adc")
    raw = checked_process([trusted_tool("fly"), "ssh", "console", "--quiet", "--app", app,
                           "--machine", machine, "--command", shlex.join(command)])
    return encrypt_export(raw, recipients, output)


def main(argv=None):
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("run")
    commands.add_parser("digest", help="Print this loader's SHA-256 for the release record")
    identity = commands.add_parser("create-identity")
    identity.add_argument("--output", type=Path, required=True)
    for name in ("verify", "materialize"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--bundle", type=Path, required=True)
        cmd.add_argument("--identity", type=Path, required=True)
        cmd.add_argument("--sha256", required=True)
        if name == "materialize":
            cmd.add_argument("--root", type=Path, default=Path("/run/canary/secrets"))
            cmd.add_argument("--allow-encrypted-swap", action="store_true")
    clean = commands.add_parser("prune")
    clean.add_argument("--root", type=Path, default=Path("/run/canary/secrets"))
    clean.add_argument("--keep")
    change = commands.add_parser("set", help="Change values in memory; read from a TTY or stdin")
    change.add_argument("--bundle", type=Path, required=True)
    change.add_argument("--identity", type=Path, required=True)
    change.add_argument("--sha256", required=True)
    change.add_argument("--name", action="append", required=True)
    change.add_argument("--remove", action="store_true")
    change.add_argument("--recipient", action="append", required=True)
    change.add_argument("--change-recipients", action="store_true")
    change.add_argument("--output", type=Path, required=True)
    export = commands.add_parser("export-fly")
    export.add_argument("--app", required=True)
    export.add_argument("--machine", required=True)
    export.add_argument("--names", required=True)
    export.add_argument("--with-adc", action="store_true")
    export.add_argument("--recipient", action="append", required=True)
    export.add_argument("--output", type=Path, required=True)
    encrypt = commands.add_parser("encrypt-file")
    encrypt.add_argument("--input", type=Path, required=True)
    encrypt.add_argument("--recipient", action="append", required=True)
    encrypt.add_argument("--output", type=Path, required=True)
    internal = commands.add_parser("_export", help=argparse.SUPPRESS)
    internal.add_argument("--names", required=True)
    internal.add_argument("--with-adc", action="store_true")
    internal.add_argument("--proc-root", type=Path, default=Path("/proc"))
    args = parser.parse_args(argv)
    try:
        if args.command == "create-identity":
            parent = args.output.parent
            if parent.stat().st_uid != os.geteuid() or parent.stat().st_mode & 0o077:
                reject("private_identity_directory_required")
            if args.output.exists() or args.output.is_symlink():
                reject("output_exists")
            keygen = trusted_tool("age-keygen")
            checked_process([keygen, "--output", str(args.output)], env=tool_env())
            args.output.chmod(0o600)
            private_read(args.output)
            recipient = checked_process([keygen, "-y", str(args.output)], env=tool_env()).decode().strip()
            print(json.dumps({"status": "identity_created", "recipient": recipient}))
        elif args.command == "run":
            runtime = os.environ.get("CANARY_SECRETS_FILE")
            if os.environ.get("CANARY_SECRET_BUNDLE_REQUIRED") == "1":
                if not runtime:
                    reject("bundle_required")
                require_loader_digest()
            env = child_environment(Path(runtime)) if runtime else dict(os.environ)
            os.execve("/app/entrypoint.sh", ["/app/entrypoint.sh"], env)
        elif args.command == "_export":
            if not stat.S_ISFIFO(os.fstat(sys.stdout.fileno()).st_mode) and not stat.S_ISSOCK(os.fstat(sys.stdout.fileno()).st_mode):
                reject("export_requires_pipe")
            sys.stdout.write(json.dumps(export_active(args.names.split(","), args.with_adc,
                                                      args.proc_root)))
        elif args.command == "export-fly":
            digest = export_fly(args.app, args.machine, args.names.split(","),
                                args.with_adc, args.recipient, args.output)
            print(json.dumps({"status": "encrypted", "sha256": digest}))
        elif args.command == "digest":
            print(json.dumps({"loader_sha256": loader_digest()}))
        elif args.command == "prune":
            if args.keep is not None and not DIGEST.fullmatch(args.keep):
                reject("invalid_keep_digest")
            removed = prune(args.root, args.keep)
            print(json.dumps({"status": "pruned", "removed": removed}))
        elif args.command == "set":
            changes = read_new_values(args.name, args.remove)
            digest = update_bundle(args.bundle, args.identity, args.sha256, changes,
                                   args.recipient, args.output, args.change_recipients)
            print(json.dumps({"status": "encrypted", "sha256": digest,
                              "changed": sorted(changes)}))
        elif args.command == "encrypt-file":
            digest = encrypt_export(private_read(args.input), args.recipient, args.output)
            print(json.dumps({"status": "encrypted", "sha256": digest}))
        else:
            if args.command == "materialize":
                require_loader_digest()  # Before any plaintext exists.
            bundle = decrypt(args.bundle, args.identity, args.sha256)
            if args.command == "materialize":
                path = materialize(bundle, args.root, args.sha256,
                                   allow_encrypted_swap=args.allow_encrypted_swap)
                print(json.dumps({"status": "materialized", "directory": str(path)}))
            else:
                print(json.dumps({"status": "verified", "sha256": args.sha256}))
        return 0
    except SecretError as error:
        print("canary-secrets: " + str(error), file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 — CLI boundary must never echo secret-bearing exceptions.
        print("canary-secrets: operation_failed", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
