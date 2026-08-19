#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: ./scripts/remote/validate_dut.sh [options]

Default: run a 30-second passive observation at a 2-second interval.

Options:
  --duration SECONDS          Passive duration (default: 30)
  --interval SECONDS          Requested sampling interval (default: 2)
  --cpu                       Explicitly enable controlled CPU characterization
  --baseline SECONDS          CPU baseline duration (default: 6)
  --stimulus-duration SECONDS CPU stimulus duration (default: 10)
  --recovery SECONDS          CPU recovery duration (default: 6)
  --max-temperature CELSIUS   CPU thermal guardrail (default: 85)
  --workers COUNT             CPU worker count (default: automatic)
  --privileged-read           Opt in to sudo -n SMART/IPMI reads only
  --no-archive                Do not create an upload package
  -h, --help                  Show this help

CPU-only options require --cpu. CPU mode is interactive-only and requires
typing CPU at the confirmation prompt.
EOF
}

die() {
    printf 'validate_dut.sh: %s\n' "$1" >&2
    exit 1
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

duration=30
interval=2
baseline=6
stimulus_duration=10
recovery=6
max_temperature=85
workers=''
cpu=false
cpu_only_option=false
no_archive=false
privileged_read=false

while (($# > 0)); do
    case "$1" in
        --duration)
            (($# >= 2)) || die "--duration requires a value"
            duration=$2
            shift 2
            ;;
        --interval)
            (($# >= 2)) || die "--interval requires a value"
            interval=$2
            shift 2
            ;;
        --cpu)
            cpu=true
            shift
            ;;
        --baseline)
            (($# >= 2)) || die "--baseline requires a value"
            baseline=$2
            cpu_only_option=true
            shift 2
            ;;
        --stimulus-duration)
            (($# >= 2)) || die "--stimulus-duration requires a value"
            stimulus_duration=$2
            cpu_only_option=true
            shift 2
            ;;
        --recovery)
            (($# >= 2)) || die "--recovery requires a value"
            recovery=$2
            cpu_only_option=true
            shift 2
            ;;
        --max-temperature)
            (($# >= 2)) || die "--max-temperature requires a value"
            max_temperature=$2
            cpu_only_option=true
            shift 2
            ;;
        --workers)
            (($# >= 2)) || die "--workers requires a value"
            workers=$2
            cpu_only_option=true
            shift 2
            ;;
        --privileged-read)
            privileged_read=true
            shift
            ;;
        --no-archive)
            no_archive=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "unknown option: $1"
            ;;
    esac
done

if [[ "$cpu" == false && "$cpu_only_option" == true ]]; then
    die "CPU characterization options require explicit --cpu"
fi

is_number() {
    [[ "$1" =~ ^[0-9]+([.][0-9]+)?$ ]]
}

for numeric_name in duration interval baseline stimulus_duration recovery max_temperature; do
    if ! is_number "${!numeric_name}"; then
        die "$numeric_name must be a non-negative decimal number"
    fi
done
if [[ -n "$workers" && ! "$workers" =~ ^[1-9][0-9]*$ ]]; then
    die "workers must be a positive integer"
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
repo_root=$(cd -- "$script_dir/../.." && pwd -P)
if ! top_level=$(git -C "$repo_root" rev-parse --show-toplevel 2>/dev/null); then
    die "repository root is not a Git worktree: $repo_root"
fi
if [[ "$top_level" != "$repo_root" ]]; then
    die "resolved path is not the repository root: $repo_root"
fi
for required_path in pyproject.toml scripts/remote/deploy_and_run.py scripts/remote/result_tools.py; do
    if [[ ! -e "$repo_root/$required_path" ]]; then
        die "unrecognized repository structure; missing $required_path"
    fi
done

env_file="$repo_root/.env"
[[ -f "$env_file" ]] || die "missing $env_file; run ./scripts/remote/setup_dut.sh first"

while IFS= read -r env_line || [[ -n "$env_line" ]]; do
    case "$env_line" in
        ''|\#*) ;;
        HTC_DUT_HOST=*|HTC_DUT_USER=*|HTC_DUT_PORT=*|HTC_DUT_DIR=*|HTC_DUT_SSH_KEY=*) ;;
        *) die "unsupported line in .env; refusing to source it" ;;
    esac
done <"$env_file"

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a
command -v python3 >/dev/null 2>&1 || die "python3 is required on this development machine"
command -v ssh >/dev/null 2>&1 || die "ssh is required on this development machine"
if ! python3 "$repo_root/scripts/remote/deploy_and_run.py" --check-config >/dev/null; then
    die ".env failed deploy_and_run.py validation"
fi

ssh_options=(-p "$HTC_DUT_PORT" -o BatchMode=yes -o ConnectTimeout=10)
if [[ -n "${HTC_DUT_SSH_KEY:-}" ]]; then
    ssh_options+=(-i "$HTC_DUT_SSH_KEY")
fi
target="$HTC_DUT_USER@$HTC_DUT_HOST"
if ! ssh "${ssh_options[@]}" "$target" true >/dev/null 2>&1; then
    die "SSH connectivity check failed for configured DUT; no deployment was attempted"
fi

if [[ "$cpu" == true ]]; then
    printf '\nCPU characterization is explicitly enabled:\n'
    printf '  Mode: cpu\n'
    if [[ -n "$workers" ]]; then
        printf '  Workers: %s\n' "$workers"
    else
        printf '  Workers: automatic default (approximately 25%% of logical CPUs)\n'
    fi
    printf '  Baseline duration: %s seconds\n' "$baseline"
    printf '  Stimulus duration: %s seconds\n' "$stimulus_duration"
    printf '  Recovery duration: %s seconds\n' "$recovery"
    printf '  Maximum-temperature guardrail: %s °C\n' "$max_temperature"
    [[ -t 0 ]] || die "CPU mode requires an interactive terminal"
    read -r -p "Type CPU to begin bounded CPU characterization: " confirmation || die "confirmation input ended"
    [[ "$confirmation" == "CPU" ]] || die "CPU characterization was not confirmed"
else
    printf 'Starting passive validation (30-second defaults unless overridden; no CPU stimulus).\n'
fi
if [[ "$privileged_read" == true ]]; then
    printf 'Privileged READ-ONLY collectors enabled (SMART/IPMI only; no CPU privilege elevation).\n'
fi

helper_output=$(mktemp)
trap 'rm -f -- "$helper_output"' EXIT
helper_command=(
    python3 "$repo_root/scripts/remote/deploy_and_run.py"
    --mode
)
if [[ "$cpu" == true ]]; then
    helper_command+=(cpu)
else
    helper_command+=(passive)
fi
helper_command+=(--duration "$duration" --interval "$interval")
if [[ "$cpu" == true ]]; then
    helper_command+=(
        --baseline "$baseline"
        --stimulus-duration "$stimulus_duration"
        --recovery "$recovery"
        --max-temperature "$max_temperature"
    )
    if [[ -n "$workers" ]]; then
        helper_command+=(--workers "$workers")
    fi
fi
if [[ "$privileged_read" == true ]]; then
    helper_command+=(--privileged-read)
fi

if ! "${helper_command[@]}" 2>&1 | tee "$helper_output"; then
    die "remote validation failed; inspect the command output above"
fi

if ! result_dir=$(python3 "$repo_root/scripts/remote/result_tools.py" parse \
    --output-file "$helper_output" --results-root "$repo_root/hardware-results"); then
    die "could not parse the local result directory; evidence may require manual inspection"
fi
if ! python3 "$repo_root/scripts/remote/result_tools.py" validate --run-dir "$result_dir"; then
    die "retrieved evidence is incomplete; preserved result directory: $result_dir"
fi

printf '\nRun summary:\n'
python3 "$repo_root/scripts/remote/result_tools.py" summary --run-dir "$result_dir" || \
    die "result files exist but their summary could not be read"

if [[ "$no_archive" == true ]]; then
    archive_path='not created (--no-archive)'
else
    archive_path=$(python3 "$repo_root/scripts/remote/result_tools.py" archive \
        --run-dir "$result_dir" --packages-dir "$repo_root/hardware-results/packages") || \
        die "could not create upload package; result directory preserved: $result_dir"
fi

printf '\nResult directory:\n%s\n\nUpload package:\n%s\n' "$result_dir" "$archive_path"
