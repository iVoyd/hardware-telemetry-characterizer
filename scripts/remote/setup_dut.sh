#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/remote/setup_dut.sh

Interactively configure a local .env for one remote Linux DUT and perform a
read-only SSH prerequisite check. No source is copied and no characterization
is run.
EOF
}

die() {
    printf 'setup_dut.sh: %s\n' "$1" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi
if (($# != 0)); then
    usage >&2
    exit 2
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)

if ! top_level=$(git -C "$repo_root" rev-parse --show-toplevel 2>/dev/null); then
    die "repository root is not a Git worktree: $repo_root"
fi
if [[ "$top_level" != "$repo_root" ]]; then
    die "resolved path is not the repository root: $repo_root"
fi
for required_path in AGENTS.md pyproject.toml scripts/remote/deploy_and_run.py; do
    if [[ ! -e "$repo_root/$required_path" ]]; then
        die "unrecognized repository structure; missing $required_path"
    fi
done
if ! git -C "$repo_root" check-ignore -q .env; then
    die ".env is not ignored; refusing to write connection configuration"
fi
if git -C "$repo_root" ls-files --error-unmatch -- .env >/dev/null 2>&1; then
    die ".env is tracked; refusing to write connection configuration"
fi
command -v python3 >/dev/null 2>&1 || die "python3 is required on this development machine"
command -v ssh >/dev/null 2>&1 || die "ssh is required on this development machine"

read -r -p "HTC_DUT_HOST: " dut_host || die "input ended before HTC_DUT_HOST was provided"
[[ -n "$dut_host" ]] || die "HTC_DUT_HOST must not be empty"
read -r -p "HTC_DUT_USER: " dut_user || die "input ended before HTC_DUT_USER was provided"
[[ -n "$dut_user" ]] || die "HTC_DUT_USER must not be empty"
read -r -p "HTC_DUT_PORT [22]: " dut_port || die "input ended before HTC_DUT_PORT was provided"
dut_port=${dut_port:-22}
read -r -p "HTC_DUT_DIR [/tmp/htc-deploy]: " dut_dir || die "input ended before HTC_DUT_DIR was provided"
dut_dir=${dut_dir:-/tmp/htc-deploy}
read -r -p "HTC_DUT_SSH_KEY (optional): " dut_ssh_key || die "input ended before HTC_DUT_SSH_KEY was provided"
if [[ -n "$dut_ssh_key" && ! -r "$dut_ssh_key" ]]; then
    die "HTC_DUT_SSH_KEY is not readable: $dut_ssh_key"
fi

export HTC_DUT_HOST="$dut_host"
export HTC_DUT_USER="$dut_user"
export HTC_DUT_PORT="$dut_port"
export HTC_DUT_DIR="$dut_dir"
if [[ -n "$dut_ssh_key" ]]; then
    export HTC_DUT_SSH_KEY="$dut_ssh_key"
else
    unset HTC_DUT_SSH_KEY || true
fi
if ! python3 "$repo_root/scripts/remote/deploy_and_run.py" --check-config; then
    die "connection settings failed deploy_and_run.py validation"
fi

env_file="$repo_root/.env"
if [[ -e "$env_file" ]]; then
    read -r -p ".env already exists. Overwrite it? Type OVERWRITE: " overwrite || die "input ended"
    [[ "$overwrite" == "OVERWRITE" ]] || die "existing .env was not changed"
fi

quote_env_value() {
    printf '%q' "$1"
}

umask 077
temp_env=$(mktemp "$repo_root/.env.tmp.XXXXXX")
trap 'rm -f -- "$temp_env"' EXIT
{
    printf 'HTC_DUT_HOST=%s\n' "$(quote_env_value "$dut_host")"
    printf 'HTC_DUT_USER=%s\n' "$(quote_env_value "$dut_user")"
    printf 'HTC_DUT_PORT=%s\n' "$(quote_env_value "$dut_port")"
    printf 'HTC_DUT_DIR=%s\n' "$(quote_env_value "$dut_dir")"
    if [[ -n "$dut_ssh_key" ]]; then
        printf 'HTC_DUT_SSH_KEY=%s\n' "$(quote_env_value "$dut_ssh_key")"
    fi
} >"$temp_env"
chmod 600 "$temp_env"
mv -f -- "$temp_env" "$env_file"
trap - EXIT
chmod 600 "$env_file"

ssh_options=(-p "$dut_port" -o BatchMode=yes -o ConnectTimeout=10)
if [[ -n "$dut_ssh_key" ]]; then
    ssh_options+=(-i "$dut_ssh_key")
fi
target="$dut_user@$dut_host"

printf '\nRead-only DUT prerequisites:\n'
prerequisites=$(ssh "${ssh_options[@]}" "$target" '
printf "whoami: "; whoami
printf "uname: "; uname -srm
if ! command -v python3 >/dev/null 2>&1; then
    printf "python3_version: unavailable\n"
    exit 1
fi
printf "python3_version: "; python3 --version 2>&1
printf "python3 path: "; command -v python3 || true
if command -v ipmitool >/dev/null 2>&1; then
    printf "ipmitool: available\n"
    if test -e /dev/ipmi0 || test -e /dev/ipmi/0 || test -e /dev/ipmidev/0; then
        printf "local IPMI interface: present\n"
        if ipmitool sensor >/dev/null 2>&1; then
            printf "IPMI unprivileged access: available\n"
        else
            printf "IPMI unprivileged access: restricted\n"
        fi
    else
        printf "local IPMI interface: absent\n"
        printf "IPMI unprivileged access: unavailable (no local interface)\n"
    fi
    if sudo -n ipmitool sensor >/dev/null 2>&1; then
        printf "IPMI sudo-n read access: available\n"
    else
        printf "IPMI sudo-n read access: unavailable or denied\n"
    fi
else
    printf "ipmitool: unavailable (IPMI collector will report unavailable)\n"
    printf "local IPMI interface: not checked\n"
fi
if command -v smartctl >/dev/null 2>&1; then
    printf "smartctl: available\n"
    if smartctl --scan >/dev/null 2>&1; then
        printf "SMART unprivileged access: available\n"
    else
        printf "SMART unprivileged access: restricted\n"
    fi
    if sudo -n smartctl --scan-open >/dev/null 2>&1; then
        printf "SMART sudo-n read access: available\n"
    else
        printf "SMART sudo-n read access: unavailable or denied\n"
    fi
else
    printf "smartctl: unavailable (SMART collector will report unavailable)\n"
fi
if test -r /sys/class/hwmon; then printf "hwmon: readable\n"; else printf "hwmon: not readable\n"; fi
if test -r /proc/stat; then printf "proc-stat: readable\n"; else printf "proc-stat: not readable\n"; fi
') || die "SSH connectivity or read-only prerequisite check failed"
python_version=$(printf '%s\n' "$prerequisites" | sed -n 's/^python3_version: //p')
[[ -n "$python_version" ]] || die "remote python3 version was not reported"
if ! python_status=$(python3 "$repo_root/scripts/remote/deploy_and_run.py" \
    --check-python-version "$python_version" 2>&1); then
    printf '%s\n' "$prerequisites" | sed '/^python3_version:/d'
    printf 'python3: %s\n' "$python_status" >&2
    die "remote Python version is unsupported; no source or characterization was run"
fi
printf '%s\n' "$prerequisites" | sed '/^python3_version:/d'
printf 'python3: %s\n' "$python_status"

if ! git -C "$repo_root" check-ignore -q .env; then
    die ".env is no longer ignored"
fi

printf '\nConnection setup complete.\nNext:\n  ./scripts/remote/validate_dut.sh\n'
