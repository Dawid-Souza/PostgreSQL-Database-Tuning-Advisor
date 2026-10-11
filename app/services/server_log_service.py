from __future__ import annotations

import shlex
import time
from dataclasses import dataclass
from typing import Any

from app.security.secret_store import secret_store
from app.services.config_service import secret_key


@dataclass
class LogFetchResult:
    ok: bool
    text: str = ""
    error: str | None = None
    command: str | None = None
    raw_bytes: int = 0
    truncated: bool = False
    executed: bool = False


def _q(value: str | None) -> str:
    return shlex.quote(str(value or ""))


def _lines(value: int | str | None) -> int:
    try:
        parsed = int(value or 5000)
    except ValueError:
        parsed = 5000
    return max(100, min(parsed, 200000))


def _sudo_prefix(environment: dict[str, Any]) -> str:
    if not environment.get("use_sudo"):
        return ""
    sudo_user = environment.get("sudo_user")
    if sudo_user:
        return f"sudo -S -p '' -u {_q(sudo_user)} "
    return "sudo -S -p '' "


def _auto_direct_log_command(lines: int) -> str:
    script = f"""
set -u
LINES={int(lines)}
tmp="${{TMPDIR:-/tmp}}/pg_dta_log_candidates.$$"
: > "$tmp"

if command -v pg_lsclusters >/dev/null 2>&1; then
  pg_lsclusters -h 2>/dev/null | awk '{{print $NF}}' >> "$tmp" || true
fi

for pattern in \\
  /var/log/postgresql/*.log \\
  /var/log/postgresql/postgresql-*.log \\
  /var/log/pgsql/*.log \\
  /var/log/postgres/*.log \\
  /var/lib/pgsql/*/data/log/*.log \\
  /var/lib/pgsql/*/data/pg_log/*.log \\
  /var/lib/postgresql/*/*/log/*.log \\
  /var/lib/postgresql/*/*/pg_log/*.log
do
  for file in $pattern; do
    [ -f "$file" ] && printf '%s\\n' "$file" >> "$tmp"
  done
done

log_file="$(
  awk 'NF && $0 ~ "^/" {{print}}' "$tmp" |
  sort -u |
  while IFS= read -r file; do
    [ -f "$file" ] || continue
    ts="$(stat -c %Y "$file" 2>/dev/null || echo 0)"
    printf '%s %s\\n' "$ts" "$file"
  done |
  sort -rn |
  head -n 1 |
  cut -d' ' -f2-
)"
rm -f "$tmp"

if [ -n "$log_file" ]; then
  echo "[pg_dta] log_file=$log_file" >&2
  exec tail -n "$LINES" "$log_file"
fi

if command -v journalctl >/dev/null 2>&1; then
  for unit in postgresql postgresql.service 'postgresql-*'; do
    if journalctl -u "$unit" --no-pager -n "$LINES" 2>/dev/null; then
      exit 0
    fi
  done
fi

echo "Não foi possível localizar logs PostgreSQL automaticamente. Informe Arquivo de log ou Comando customizado no ambiente." >&2
exit 2
""".strip()
    return f"sh -lc {_q(script)}"


def build_log_command(environment: dict[str, Any], lines: int | str | None = None) -> str:
    final_lines = _lines(lines or environment.get("default_lines"))
    mode = environment.get("log_mode") or ("container" if environment.get("environment_type") == "container" else "file")
    if environment.get("environment_type") != "container" and mode == "container":
        mode = "file"
    custom = environment.get("custom_log_command") or ""
    base = environment.get("log_base_command") or ""

    if custom:
        command = custom.replace("{lines}", str(final_lines))
    elif base:
        command = (
            base.replace("{lines}", str(final_lines))
            .replace("{container}", str(environment.get("container_name") or ""))
            .replace("{runtime}", str(environment.get("container_runtime") or "docker"))
        )
    elif environment.get("environment_type") == "container" and mode == "container":
        runtime = "podman" if str(environment.get("container_runtime")).lower() == "podman" else "docker"
        container = _q(environment.get("container_name"))
        if environment.get("use_container_exec"):
            user = f" --user {_q(environment.get('container_user'))}" if environment.get("container_user") else ""
            app_dir = environment.get("container_app_dir") or "/"
            log_file = environment.get("log_file_path") or ""
            inner = f"cd {_q(app_dir)} && tail -n {final_lines} {_q(log_file)}" if log_file else f"cd {_q(app_dir)} && ls -la"
            command = f"{runtime} exec{user} {container} sh -lc {_q(inner)}"
        else:
            command = f"{runtime} logs --tail {final_lines} {container} 2>&1"
    elif mode == "custom" and custom:
        command = custom.replace("{lines}", str(final_lines))
    else:
        log_file = environment.get("log_file_path")
        if log_file:
            command = f"tail -n {final_lines} {_q(log_file)}"
        elif environment.get("environment_type") == "direct":
            command = _auto_direct_log_command(final_lines)
        else:
            raise ValueError("Informe arquivo de log ou comando customizado para instalação direta.")

    return _sudo_prefix(environment) + command


def _runtime_secret(environment: dict[str, Any], field: str) -> str | None:
    return secret_store.get(secret_key("environment", str(environment["id"]), field))


def _sudo_password(environment: dict[str, Any]) -> str | None:
    if environment.get("sudo_password_from_ssh"):
        return _runtime_secret(environment, "ssh_password")
    return _runtime_secret(environment, "sudo_password")


def validate_environment_for_fetch(environment: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if not environment.get("host"):
        errors.append("Host/IP da instância é obrigatório.")
    if not environment.get("ssh_login"):
        errors.append("Login SSH é obrigatório.")
    if environment.get("ssh_auth_method") == "password" and environment.get("has_ssh_password") and not _runtime_secret(environment, "ssh_password"):
        errors.append("Senha SSH não está carregada na sessão atual.")
    if environment.get("ssh_auth_method") == "key" and not environment.get("ssh_key_path"):
        errors.append("Caminho da chave privada é obrigatório para autenticação por chave.")
    if environment.get("use_sudo") and not environment.get("sudo_password_from_ssh") and environment.get("has_sudo_password") and not _runtime_secret(environment, "sudo_password"):
        errors.append("Senha sudo não está carregada na sessão atual.")
    if environment.get("environment_type") == "container" and not environment.get("container_name"):
        errors.append("Nome ou ID do container é obrigatório para ambiente Container.")
    return errors


def command_preview(environment: dict[str, Any], lines: int | str | None = None) -> str:
    return secret_store.redact(build_log_command(environment, lines)) or ""


def fetch_server_logs(environment: dict[str, Any], *, lines: int = 5000, max_bytes: int | None = None, confirm_execution: bool = False) -> LogFetchResult:
    command = build_log_command(environment, lines)
    safe_command = secret_store.redact(command)
    if not confirm_execution:
        return LogFetchResult(ok=False, error="Execução remota não confirmada. O comando foi apenas gerado para revisão.", command=safe_command, executed=False)

    validation_errors = validate_environment_for_fetch(environment)
    if validation_errors:
        return LogFetchResult(ok=False, error="; ".join(validation_errors), command=safe_command, executed=False)

    try:
        import paramiko  # type: ignore
    except Exception as exc:
        return LogFetchResult(ok=False, error=f"Paramiko não está instalado: {exc}", command=safe_command, executed=False)

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        kwargs: dict[str, Any] = {
            "hostname": environment.get("host"),
            "port": int(environment.get("ssh_port") or 22),
            "username": environment.get("ssh_login"),
            "timeout": int(environment.get("timeout_seconds") or 20),
        }
        if environment.get("ssh_auth_method") == "key":
            kwargs["key_filename"] = environment.get("ssh_key_path")
        else:
            password = _runtime_secret(environment, "ssh_password")
            if password:
                kwargs["password"] = password
        client.connect(**kwargs)

        needs_sudo = bool(environment.get("use_sudo")) or "sudo -S" in command
        stdin, stdout, stderr = client.exec_command(command, timeout=max(30, int(environment.get("timeout_seconds") or 20) * 3), get_pty=False)
        if needs_sudo:
            sudo_password = _sudo_password(environment)
            if not sudo_password:
                return LogFetchResult(ok=False, error="Comando usa sudo, mas nenhuma senha sudo está carregada na sessão atual.", command=safe_command, executed=True)
            stdin.write(sudo_password + "\n")
            stdin.flush()

        configured_limit = max_bytes if max_bytes is not None else environment.get("max_bytes")
        try:
            byte_limit = int(configured_limit or 0)
        except (TypeError, ValueError):
            byte_limit = 0
        unlimited_bytes = byte_limit <= 0
        chunks: list[bytes] = []
        err_chunks: list[bytes] = []
        total = 0
        truncated = False
        channel = stdout.channel
        while True:
            while channel.recv_ready():
                data = channel.recv(65536 if unlimited_bytes else min(65536, byte_limit - total))
                if not data:
                    break
                chunks.append(data)
                total += len(data)
                if not unlimited_bytes and total >= byte_limit:
                    truncated = True
                    break
            while channel.recv_stderr_ready():
                data = channel.recv_stderr(65536)
                if data:
                    err_chunks.append(data)
            if truncated:
                try:
                    channel.close()
                except Exception:
                    pass
                break
            if channel.exit_status_ready():
                while channel.recv_ready():
                    data = channel.recv(65536 if unlimited_bytes else min(65536, byte_limit - total))
                    if not data:
                        break
                    chunks.append(data)
                    total += len(data)
                    if not unlimited_bytes and total >= byte_limit:
                        truncated = True
                        break
                while channel.recv_stderr_ready():
                    data = channel.recv_stderr(65536)
                    if data:
                        err_chunks.append(data)
                break
            time.sleep(0.05)

        code = 124 if truncated else channel.recv_exit_status()
        out = secret_store.redact(b"".join(chunks).decode("utf-8", errors="replace")) or ""
        err = secret_store.redact(b"".join(err_chunks).decode("utf-8", errors="replace")) or ""
        trunc_msg = f"\n[TRUNCADO PELO APP: limite de {byte_limit} bytes atingido]" if truncated else ""
        if code != 0 and not out:
            return LogFetchResult(ok=False, error=(err or f"Comando retornou código {code}") + trunc_msg, command=safe_command, raw_bytes=total, truncated=truncated, executed=True)
        return LogFetchResult(ok=True, text=(out if out else err) + trunc_msg, error=(err if code != 0 and not truncated else None), command=safe_command, raw_bytes=total, truncated=truncated, executed=True)
    except Exception as exc:
        return LogFetchResult(ok=False, error=secret_store.redact(str(exc)), command=safe_command, executed=True)
    finally:
        client.close()
