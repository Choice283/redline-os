<#
Phase 14.1 — proposed single-process live-execution runbook (revision 7).

STATUS: PROPOSED. NOT AUTHORIZED. NOT EXECUTED.

Revision history (see docs/PHASE14_ENABLEMENT_STATIC_REVIEW.md for full detail):
  - Rev4 was constructed and staged for a staged-diff review. The staged
    candidate was rejected for commit consideration after that review found
    three Important and two Minor findings (repository-root validation
    ordering, incomplete exception-safe coverage of the post-confirmation
    probe-hash checks, diluted exception identity in runbook_failure.json,
    a redundant duplicate hash check, and a "rehash timing" documentation
    claim that didn't match the code). No commit or publication occurred.
    Rev4 was superseded by Rev5 corrections.
  - Rev5 fixed all five Rev4 findings (repository-root validation ordering,
    six real individually-reachable probe-hash checkpoints, preserved
    exception identity, removal of the redundant duplicate hash check, and
    "immediately before" documentation precision). Rev5 was itself
    constructed and staged for a second, independent read-only staged-diff
    review, which found one Important finding (a stale test-count claim in
    `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md` §10, which still said
    "46 tests" after the suite had grown to 70) and one Minor finding (two
    of the six probe-hash checkpoint comments claimed "no other operation
    sits between" a check and its guarded step when a non-mutating
    variable assignment or guard call actually sat between them). The
    staged candidate was rejected for commit consideration. No commit or
    publication occurred. Rev5 was superseded by these Rev6 corrections.
  - Rev6 (this revision) fixes both Rev5 findings:
    - `docs/PHASE14_READ_ONLY_COMPARISON_CONTRACT.md` §10 now states the
      current, verified test count (70) and retains the prior 46-test
      figure only as clearly labeled Rev2-era historical information.
    - The probe-hash checkpoint comments (here and in
      `docs/PHASE14_LIVE_EXECUTION_RUNBOOK.md` §9) now state precisely what
      they can actually guarantee -- that no operation capable of
      modifying or replacing the hashed probe file sits between the check
      and its guarded step -- rather than the broader, not-quite-accurate
      "no other operation sits between" claim. The non-mutating path
      construction and file-guard calls that sit between some checks and
      their guarded steps are unchanged; only the documentation's claim
      about them was corrected.


  - Rev7 (this revision) corrects the native-process boundary after the
    published Rev6 non-contact preflight stopped before evidence creation.
    The observed Rev6 failure was a Python `-c` NameError at the structured
    identity probe. A later exact-host compatibility probe did not reproduce
    that one-time NameError, so Rev7 does not claim a deterministic cause for
    it. The same compatibility run did prove a separate deterministic blocker:
    Windows PowerShell 5.1 / CLR 4 exposes no
    `ProcessStartInfo.ArgumentList`, which Rev6 used for manifest validation.
  - Rev7 replaces every Python launch boundary with one Windows CRT argv
    encoder using `ProcessStartInfo.Arguments`; uses a quote-free Python
    identity probe; transports the exact single-read manifest bytes as strict
    Base64 through argv to the probe's `validate-manifest-base64` command; and
    uses the same capture helper for the eventual snapshot process.
  - Native compatibility evidence on the target host passed under Windows
    PowerShell 5.1.26100.8875, CLR 4.0.30319.42000, and Python 3.11:
    quote-free identity, difficult argv round-trip, Base64 byte transport,
    and the real manifest validator all passed without preflight, Resolve
    scripting contact, or SQLite access.

Single `-File` execution only, never pasted as individual statements.
Evidence lives entirely OUTSIDE the repository. Supports exactly ONE
context per invocation and fails the whole script nonzero on any check,
probe, or validation failure. No retry is attempted or authorized.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Control", "Production")]
    [string]$Context,

    [Parameter(Mandatory = $true)]
    [string]$ExecutionAuthorization,

    [Parameter(Mandatory = $true)]
    [string]$AuthorizationManifest,

    [Parameter(Mandatory = $true)]
    [string]$ExpectedManifestSha256,

    [switch]$PreflightOnly
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repo               = "C:\Users\pj198\Documents\redline-os"
$expectedOriginUrl  = "git@github.com:Choice283/redline-os.git"
$expectedRevisionId = "phase14.1-live-interlock-construction-rev7"
$expectedMission    = "phase14.1-live-snapshot"
$expectedContextDefinitions = @{
    Control    = @{ Project = "redline-os-test-duplicate"; Timeline = "RLO-LIVE-ASM-92701_TIMELINE" }
    Production = @{ Project = "RLC-E9001_MASTER";          Timeline = "RLC-E9001_TIMELINE" }
}
$expectedProject  = $expectedContextDefinitions[$Context].Project
$expectedTimeline = $expectedContextDefinitions[$Context].Timeline

$modeLabel = if ($PreflightOnly) { "PREFLIGHT (non-contact)" } else { "LIVE CAPTURE" }
Write-Host "=== Phase 14.1 (rev7) live-execution runbook: $Context context [$modeLabel] ==="

# ============================================================================
# Reusable guards
# ============================================================================
function Assert-OrdinaryFile {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) { throw "STOP: $Label does not exist: $Path" }
    $item = Get-Item -LiteralPath $Path -Force
    if ($item.PSIsContainer) { throw "STOP: $Label is a directory, not a file: $Path" }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "STOP: $Label is a reparse point (symlink/junction), not an ordinary file: $Path"
    }
}

function Assert-OrdinaryDirectoryNotReparsePoint {
    param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$Label)
    $item = Get-Item -LiteralPath $Path -Force
    if (-not $item.PSIsContainer) { throw "STOP: $Label is not a directory: $Path" }
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "STOP: $Label is a reparse point: $Path"
    }
}

function Get-Sha256HexOfBytes {
    param([Parameter(Mandatory = $true)][byte[]]$Bytes)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $hashBytes = $sha.ComputeHash($Bytes)
    }
    finally {
        $sha.Dispose()
    }
    return -join ($hashBytes | ForEach-Object { $_.ToString("x2") })
}

function Get-Sha256HexOfFile {
    param([Parameter(Mandatory = $true)][string]$Path)
    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

# BEGIN PHASE14_NATIVE_PROCESS_HELPERS
function ConvertTo-WindowsCommandLineArgument {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyString()]
        [string]$Argument
    )

    # Windows CRT argv encoding, equivalent to Python subprocess.list2cmdline.
    $needsOuterQuotes = $Argument.Length -eq 0 -or $Argument -match '[\s]'
    $builder = New-Object System.Text.StringBuilder

    if ($needsOuterQuotes) {
        [void]$builder.Append([char]34)
    }

    $backslashCount = 0
    foreach ($character in $Argument.ToCharArray()) {
        if ($character -eq [char]92) {
            $backslashCount += 1
            continue
        }

        if ($character -eq [char]34) {
            if ($backslashCount -gt 0) {
                [void]$builder.Append((-join ('\' * ($backslashCount * 2))))
            }
            [void]$builder.Append([char]92)
            [void]$builder.Append([char]34)
            $backslashCount = 0
            continue
        }

        if ($backslashCount -gt 0) {
            [void]$builder.Append((-join ('\' * $backslashCount)))
            $backslashCount = 0
        }

        [void]$builder.Append($character)
    }

    if ($backslashCount -gt 0) {
        $terminalCount = if ($needsOuterQuotes) {
            $backslashCount * 2
        }
        else {
            $backslashCount
        }
        [void]$builder.Append((-join ('\' * $terminalCount)))
    }

    if ($needsOuterQuotes) {
        [void]$builder.Append([char]34)
    }

    return $builder.ToString()
}

function Join-WindowsCommandLineArguments {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [AllowEmptyString()]
        [string[]]$Arguments
    )

    return (
        $Arguments |
            ForEach-Object {
                ConvertTo-WindowsCommandLineArgument -Argument $_
            }
    ) -join " "
}

function Invoke-NativeProcessCapture {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)]
        [AllowEmptyCollection()]
        [AllowEmptyString()]
        [string[]]$Arguments
    )

    Assert-OrdinaryFile -Path $FilePath -Label "native executable"

    $processInfo = New-Object System.Diagnostics.ProcessStartInfo
    $processInfo.FileName = $FilePath
    $processInfo.Arguments = Join-WindowsCommandLineArguments -Arguments $Arguments
    $processInfo.UseShellExecute = $false
    $processInfo.CreateNoWindow = $true
    $processInfo.RedirectStandardOutput = $true
    $processInfo.RedirectStandardError = $true
    $processInfo.RedirectStandardInput = $false

    $process = $null
    try {
        $process = [System.Diagnostics.Process]::Start($processInfo)
        if ($null -eq $process) {
            throw "STOP: native process start returned null."
        }

        $stdoutTask = $process.StandardOutput.ReadToEndAsync()
        $stderrTask = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()

        return [pscustomobject]@{
            ExitCode  = $process.ExitCode
            Stdout    = $stdoutTask.Result
            Stderr    = $stderrTask.Result
            Arguments = $processInfo.Arguments
        }
    }
    finally {
        if ($null -ne $process) {
            $process.Dispose()
        }
    }
}

function Get-PythonRuntimeIdentity {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$PythonPath
    )

    # No literal quote character is embedded in this python -c program.
    $versionProbeScript = 'import sys; print(sys.version_info.major, sys.version_info.minor, sys.executable, sep=chr(31))'
    $result = Invoke-NativeProcessCapture `
        -FilePath $PythonPath `
        -Arguments @("-c", $versionProbeScript)

    if ($result.ExitCode -ne 0) {
        throw "STOP: quote-free Python identity probe failed."
    }

    $versionText = $result.Stdout.TrimEnd([char]13, [char]10)
    $parts = $versionText.Split([char]31)
    if ($parts.Count -ne 3) {
        throw "STOP: quote-free Python identity probe returned an unexpected field count."
    }

    $major = 0
    $minor = 0
    if (-not [int]::TryParse($parts[0], [ref]$major)) {
        throw "STOP: Python major version was not an integer."
    }
    if (-not [int]::TryParse($parts[1], [ref]$minor)) {
        throw "STOP: Python minor version was not an integer."
    }

    return [pscustomobject]@{
        Major      = $major
        Minor      = $minor
        Executable = $parts[2]
    }
}

function Resolve-Python311Runtime {
    [CmdletBinding()]
    param()

    $launcher = Get-Command "py.exe" -CommandType Application -ErrorAction Stop
    $launcherPath = [string]$launcher.Source
    Assert-OrdinaryFile -Path $launcherPath -Label "Python launcher"

    $pathProbeScript = 'import sys; print(sys.executable)'
    $pathResult = Invoke-NativeProcessCapture `
        -FilePath $launcherPath `
        -Arguments @("-3.11", "-c", $pathProbeScript)

    if ($pathResult.ExitCode -ne 0) {
        throw "STOP: Python 3.11 interpreter not found via py.exe."
    }

    $pythonPath = $pathResult.Stdout.Trim()
    Assert-OrdinaryFile -Path $pythonPath -Label "resolved Python executable"

    $identity = Get-PythonRuntimeIdentity -PythonPath $pythonPath
    if ($identity.Major -ne 3 -or $identity.Minor -ne 11) {
        throw "STOP: resolved interpreter is not exactly Python 3.11."
    }

    $reportedPath = (Resolve-Path -LiteralPath $identity.Executable).Path
    $resolvedPath = (Resolve-Path -LiteralPath $pythonPath).Path
    if ($reportedPath -cne $resolvedPath) {
        throw "STOP: Python identity probe reported a different executable path."
    }

    return [pscustomobject]@{
        Path  = $resolvedPath
        Major = $identity.Major
        Minor = $identity.Minor
    }
}
# END PHASE14_NATIVE_PROCESS_HELPERS

# ============================================================================
# Validation-persistence: every attempted check is recorded, and the file is
# rewritten after every single check, success or failure, via an
# exception-safe wrapper -- a thrown exception while *evaluating* a check is
# itself recorded, not left to crash the script silently.
# ============================================================================
$validationKeys = @(
    "repository_probe_hash_pre_copy", "evidence_probe_hash_post_copy",
    "repository_probe_hash_pre_confirmation", "evidence_probe_hash_pre_confirmation",
    "repository_probe_hash_pre_launch", "evidence_probe_hash_pre_launch",
    "exit_code_zero", "output_exists_as_file", "output_hash_computed",
    "json_parses", "snapshot_complete_is_true", "expected_project_matches",
    "expected_timeline_matches", "pre_post_guard_identity_matches",
    "success_stdout_empty", "success_stderr_empty",
    "repository_checkpoint_unchanged", "repository_probe_hash_unchanged",
    "copied_probe_hash_unchanged"
)
$validation = [ordered]@{}
foreach ($key in $validationKeys) { $validation[$key] = "not_run" }
$validation["failure_code"] = $null
$validation["failure_exception_type"] = $null
$script:evidenceDir = $null  # set once created

function Save-Validation {
    if ($null -ne $script:evidenceDir -and (Test-Path -LiteralPath $script:evidenceDir -PathType Container)) {
        ($validation | ConvertTo-Json -Depth 5) |
            Set-Content -LiteralPath (Join-Path $script:evidenceDir "execution_validation.json") -Encoding UTF8
    }
}

function Invoke-ValidationCheck {
    param(
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][scriptblock]$Check,
        [Parameter(Mandatory = $true)][string]$FailureMessage
    )
    try {
        $passed = [bool](& $Check)
    }
    catch {
        # Preserve the original exception's identity: record the stable
        # failure code and the real exception type, persist the validation
        # file, then re-raise with a bare `throw` (not `throw "STOP: ..."`).
        # A bare `throw` inside a catch block re-throws the exact exception
        # object currently being handled, so the outer handler's
        # runbook_failure.json records the same real type -- not a
        # replacement RuntimeException manufactured from a string.
        $validation[$Key] = $false
        $validation["failure_code"] = $Key
        $validation["failure_exception_type"] = $_.Exception.GetType().FullName
        Save-Validation
        throw
    }
    $validation[$Key] = $passed
    if (-not $passed) {
        $validation["failure_code"] = $Key
        Save-Validation
        throw "STOP: $FailureMessage"
    }
    Save-Validation
}

# ============================================================================
# Top-level controlled failure capture. Active for everything from evidence-
# directory creation onward (assigned just before that point). Any otherwise-
# unclassified terminating exception is recorded to runbook_failure.json
# before the script exits nonzero, without exposing the authorization value
# or manifest contents.
# ============================================================================
function Write-RunbookFailure {
    param($ErrorRecord)
    if ($null -ne $script:evidenceDir -and (Test-Path -LiteralPath $script:evidenceDir -PathType Container)) {
        @{
            failureExceptionType = $ErrorRecord.Exception.GetType().Name
            failureMessage       = $ErrorRecord.Exception.Message
            capturedAt           = (Get-Date).ToUniversalTime().ToString("o")
        } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $script:evidenceDir "runbook_failure.json") -Encoding UTF8
    }
}

try {

# ============================================================================
# Item 3/4: single-byte-read, duplicate-key-safe manifest validation.
# ============================================================================
if ($ExpectedManifestSha256 -cnotmatch "^[0-9a-f]{64}$") {
    throw "STOP: -ExpectedManifestSha256 must be exactly 64 lowercase hex characters."
}
Assert-OrdinaryFile -Path $AuthorizationManifest -Label "authorization manifest"

$manifestBytes = [System.IO.File]::ReadAllBytes($AuthorizationManifest)  # the ONE read
$manifestHash = Get-Sha256HexOfBytes -Bytes $manifestBytes
if ($manifestHash -ne $ExpectedManifestSha256.ToLowerInvariant()) {
    throw "STOP: authorization manifest hash does not match -ExpectedManifestSha256. found=$manifestHash"
}

$strictUtf8 = New-Object System.Text.UTF8Encoding($false, $true)
try {
    [void]$strictUtf8.GetString($manifestBytes)
}
catch {
    throw "STOP: authorization manifest is not strict UTF-8."
}

# Item 5 (order): resolve the exact Python 3.11 executable once, before
# manifest schema parsing, and reuse it for every later check and execution.
# Rev7 routes py.exe and python.exe through the same tested Windows CRT argv
# encoder; the identity program contains no literal quote character.
$pythonRuntime = Resolve-Python311Runtime
$pyPath = $pythonRuntime.Path
$versionInfo = [pscustomobject]@{
    major      = $pythonRuntime.Major
    minor      = $pythonRuntime.Minor
    executable = $pythonRuntime.Path
}
Write-Host "Python interpreter (resolved once, reused for every check and execution): $pyPath (3.$($versionInfo.minor))"

# Duplicate-key-safe, exact-schema manifest validation via the probe's own
# validate-manifest subcommand, fed the exact bytes already read above.
$repoProbePathForValidator = Join-Path $repo "scripts\phase14_resolve_context_snapshot.py"
if (-not (Test-Path -LiteralPath $repoProbePathForValidator -PathType Leaf)) {
    throw "STOP: repository probe script missing; cannot run manifest validator: $repoProbePathForValidator"
}
$manifestBase64 = [Convert]::ToBase64String($manifestBytes)
$validatorResult = Invoke-NativeProcessCapture `
    -FilePath $pyPath `
    -Arguments @(
        $repoProbePathForValidator,
        "validate-manifest-base64",
        $manifestBase64
    )
$validatorStdout = $validatorResult.Stdout
$validatorStderr = $validatorResult.Stderr

if ($validatorResult.ExitCode -ne 0) {
    $validatorErrorCode = "manifest_validation_failed"
    try {
        $validatorErrorCode = ($validatorStderr | ConvertFrom-Json -ErrorAction Stop).code
    }
    catch { }
    throw "STOP: authorization manifest failed duplicate-key-safe schema validation: $validatorErrorCode"
}
# Safe to parse with the ordinary (non-duplicate-safe) JSON parser: this is
# the validator's own output, serialized from a real Python dict, which by
# construction cannot contain a duplicate key.
$manifestResult = $validatorStdout | ConvertFrom-Json -ErrorAction Stop
if ($manifestResult.valid -ne $true) { throw "STOP: manifest validator reported invalid without a usable error code." }
$manifest = $manifestResult.manifest

if ($manifest.mission -cne $expectedMission) { throw "STOP: manifest mission field mismatch." }
if ($manifest.repository_root -cne $repo) { throw "STOP: manifest repository_root does not match this runbook's expected repository root." }
if ($manifest.origin_url -cne $expectedOriginUrl) { throw "STOP: manifest origin_url does not match this runbook's expected origin URL." }
if ($manifest.authorized_commit -cnotmatch "^[0-9a-f]{40}$") { throw "STOP: manifest authorized_commit is not 40 lowercase hex characters." }
if ($manifest.execution_revision_id -cne $expectedRevisionId) { throw "STOP: manifest execution_revision_id does not match this runbook's expected revision." }
foreach ($hashField in @("probe_sha256", "test_sha256", "contract_sha256", "runbook_sha256")) {
    if ($manifest.$hashField -cnotmatch "^[0-9a-f]{64}$") { throw "STOP: manifest $hashField is not 64 lowercase hex characters." }
}
if ([string]::IsNullOrWhiteSpace([string]$manifest.resolve_product_version)) { throw "STOP: manifest resolve_product_version is empty." }
foreach ($ctxName in @("Control", "Production")) {
    $ctx = $manifest.contexts.$ctxName
    $expectedCtx = $expectedContextDefinitions[$ctxName]
    if ($ctx.project -cne $expectedCtx.Project -or $ctx.timeline -cne $expectedCtx.Timeline) {
        throw "STOP: manifest context '$ctxName' does not match the approved project/timeline for that context."
    }
}

$authorizedCommit     = [string]$manifest.authorized_commit
$expectedProbeHash    = ([string]$manifest.probe_sha256).ToLowerInvariant()
$expectedTestHash     = ([string]$manifest.test_sha256).ToLowerInvariant()
$expectedContractHash = ([string]$manifest.contract_sha256).ToLowerInvariant()
$expectedRunbookHash  = ([string]$manifest.runbook_sha256).ToLowerInvariant()
$expectedResolveVersion = [string]$manifest.resolve_product_version

Write-Host "Authorization manifest verified (single read, duplicate-key-safe): $AuthorizationManifest"
Write-Host "Authorized commit (from manifest): $authorizedCommit"

# ============================================================================
# Item 7 (self): bind this runbook to its own exact reviewed bytes.
# ============================================================================
$executedRunbookPath = (Resolve-Path -LiteralPath $PSCommandPath).Path
Assert-OrdinaryFile -Path $executedRunbookPath -Label "executing runbook"
$executedRunbookHash = Get-Sha256HexOfFile -Path $executedRunbookPath
if ($executedRunbookHash -ne $expectedRunbookHash) {
    throw "STOP: the runbook actually executing does not match the manifest's approved runbook_sha256."
}

$canonicalRunbookPath = Join-Path $repo "scripts\phase14_live_snapshot_runbook.ps1"
Assert-OrdinaryFile -Path $canonicalRunbookPath -Label "canonical repository runbook copy"
$canonicalRunbookHash = Get-Sha256HexOfFile -Path $canonicalRunbookPath
if ($canonicalRunbookHash -ne $expectedRunbookHash) {
    throw "STOP: the canonical repository runbook copy does not match the manifest's approved runbook_sha256."
}
$executedIsCanonicalPath = ($executedRunbookPath -ceq (Resolve-Path -LiteralPath $canonicalRunbookPath).Path)
Write-Host "Executing runbook self-hash verified against manifest: $executedRunbookHash"
Write-Host "Executing from canonical repository path: $executedIsCanonicalPath (byte-identical to canonical copy either way)"

# ============================================================================
# Item 6: exact repository and remote identity. Every local Git command is
# rooted with -C $repo; this script never depends on its own working
# directory.
# ============================================================================
function Assert-RepoCheckpoint {
    # Git's exit code is always checked before its output is passed to
    # anything that could itself throw (Resolve-Path, string comparisons on
    # a value that might be missing, etc.) -- a failed Git call now always
    # produces the intended, stable "STOP: ..." message instead of a
    # confusing downstream exception from consuming its (possibly empty)
    # output. Messages are deliberately static and do not interpolate raw
    # Git output.
    $reportedRootText = & git -C $repo rev-parse --show-toplevel
    $gitExitCode = $LASTEXITCODE
    if ($gitExitCode -ne 0) { throw "STOP: unable to resolve repository root." }
    if ($null -eq $reportedRootText -or [string]::IsNullOrWhiteSpace([string]$reportedRootText)) {
        throw "STOP: repository root output was empty."
    }
    $script:repoRootCheck = (Resolve-Path -LiteralPath ([string]$reportedRootText).Trim()).Path
    if ($repoRootCheck -cne (Resolve-Path -LiteralPath $repo).Path) { throw "STOP: repository root does not match the expected canonical path." }

    $branchText = & git -C $repo branch --show-current
    $branchExitCode = $LASTEXITCODE
    if ($branchExitCode -ne 0) { throw "STOP: unable to determine current branch." }
    $script:branch = [string]$branchText
    if ($branch -cne "master") { throw "STOP: branch is not master." }

    $originUrlText = & git -C $repo remote get-url origin
    $originUrlExitCode = $LASTEXITCODE
    if ($originUrlExitCode -ne 0) { throw "STOP: unable to determine origin remote URL." }
    if ([string]$originUrlText -cne $expectedOriginUrl) { throw "STOP: origin remote URL mismatch." }

    $headText = & git -C $repo rev-parse HEAD
    $headExitCode = $LASTEXITCODE
    if ($headExitCode -ne 0) { throw "STOP: unable to resolve HEAD." }
    $script:head = [string]$headText
    if ($head -cne $authorizedCommit) { throw "STOP: HEAD does not match the manifest's authorized_commit." }

    $originMasterText = & git -C $repo rev-parse origin/master
    $originMasterExitCode = $LASTEXITCODE
    if ($originMasterExitCode -ne 0) { throw "STOP: unable to resolve origin/master." }
    $script:originMaster = [string]$originMasterText
    if ($originMaster -cne $authorizedCommit) { throw "STOP: origin/master mismatch." }

    $remoteResult = @(git -C $repo ls-remote --exit-code origin refs/heads/master)
    $lsRemoteExitCode = $LASTEXITCODE
    if ($lsRemoteExitCode -ne 0 -or $remoteResult.Count -ne 1) { throw "STOP: unable to verify GitHub master." }
    $script:remoteMaster = ($remoteResult[0] -split "\s+")[0]
    if ($remoteMaster -cne $authorizedCommit) { throw "STOP: GitHub master mismatch." }

    $script:status = @(git -C $repo status --porcelain=v1)
    $statusExitCode = $LASTEXITCODE
    if ($statusExitCode -ne 0 -or $status.Count -ne 0) { throw "STOP: working tree is not fully clean (staged, unstaged, or untracked paths present)." }
}
Assert-RepoCheckpoint

# ============================================================================
# Probe/test/contract hashes against the manifest (repository copies).
# ============================================================================
$repoProbePath = Join-Path $repo "scripts\phase14_resolve_context_snapshot.py"
$repoTestPath = Join-Path $repo "tests\unit\test_phase14_resolve_context_snapshot.py"
$repoContractPath = Join-Path $repo "docs\PHASE14_READ_ONLY_COMPARISON_CONTRACT.md"

Assert-OrdinaryFile -Path $repoProbePath -Label "repository probe script"
Assert-OrdinaryFile -Path $repoTestPath -Label "repository test file"
Assert-OrdinaryFile -Path $repoContractPath -Label "repository contract doc"

if ((Get-Sha256HexOfFile -Path $repoTestPath) -ne $expectedTestHash) { throw "STOP: repository test file hash mismatch." }
if ((Get-Sha256HexOfFile -Path $repoContractPath) -ne $expectedContractHash) { throw "STOP: repository contract doc hash mismatch." }

if ($ExecutionAuthorization -cne $expectedRevisionId) {
    throw "STOP: -ExecutionAuthorization does not case-sensitively match the expected revision identifier."
}

# ============================================================================
# Resolve version (exact match) and Resolve.exe ordinary-file/reparse checks.
# ============================================================================
$resolveExe = "C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
Assert-OrdinaryFile -Path $resolveExe -Label "Resolve.exe"
$resolveVersionInfo = (Get-Item -LiteralPath $resolveExe).VersionInfo
$resolveProductVersion = ([string]$resolveVersionInfo.ProductVersion).Trim()
$resolveFileVersionRaw = ([string]$resolveVersionInfo.FileVersion).Trim()
if ($resolveProductVersion -cne $expectedResolveVersion) {
    throw "STOP: Resolve ProductVersion ($resolveProductVersion) does not exactly equal the manifest's resolve_product_version ($expectedResolveVersion)."
}
$resolveProcess = Get-Process -Name "Resolve" -ErrorAction SilentlyContinue
if (-not $resolveProcess) { throw "STOP: DaVinci Resolve does not appear to be running." }

foreach ($varName in @("RESOLVE_SCRIPT_API", "RESOLVE_SCRIPT_LIB")) {
    $value = [System.Environment]::GetEnvironmentVariable($varName)
    if ([string]::IsNullOrWhiteSpace($value)) { throw "STOP: $varName is not set." }
    if (-not (Test-Path -LiteralPath $value)) { throw "STOP: $varName path does not exist: $value" }
}
if ($env:PYTHONPATH -notmatch [regex]::Escape("DaVinci Resolve")) {
    throw "STOP: PYTHONPATH does not appear to include the Resolve Scripting Modules directory."
}

# ============================================================================
# Evidence root OUTSIDE the repository, create-only, true UTC timestamp+GUID.
# Preflight and live-capture evidence use distinct naming so they are never
# confused for one another.
# ============================================================================
$evidenceParent = Join-Path $env:USERPROFILE "Documents"
$utcStamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffffffZ")
$token = [Guid]::NewGuid().ToString("N")
$evidenceKind = if ($PreflightOnly) { "preflight" } else { "live" }
$evidenceDirCandidate = Join-Path $evidenceParent "phase14.1-$evidenceKind-evidence-$Context-$utcStamp-$token"
$evidenceZip = "$evidenceDirCandidate.zip"

if (Test-Path -LiteralPath $evidenceDirCandidate) { throw "STOP: evidence directory already exists: $evidenceDirCandidate" }
if (Test-Path -LiteralPath $evidenceZip) { throw "STOP: evidence zip already exists: $evidenceZip" }

New-Item -ItemType Directory -Path $evidenceDirCandidate -ErrorAction Stop | Out-Null
Assert-OrdinaryDirectoryNotReparsePoint -Path $evidenceDirCandidate -Label "newly created evidence directory"
$script:evidenceDir = $evidenceDirCandidate   # activates Save-Validation and Write-RunbookFailure from here on
Save-Validation
$outputPath = Join-Path $evidenceDir "${Context}_snapshot.json"

$probeSourceText = Get-Content -LiteralPath $repoProbePath -Raw
if ($probeSourceText -match "sqlite3|REDLINE_DB_PATH") {
    throw "STOP: probe source unexpectedly references SQLite; do not proceed."
}

# ============================================================================
# Copy approved artifacts into evidence; hash every copy; require equality.
# The manifest copy is the exact original bytes, written directly, never
# re-read from $AuthorizationManifest and never re-serialized.
# ============================================================================
# Checkpoint 1 of 6: repository probe hash, checked just before it is
# copied. The one intervening line below (computing $copiedProbePath) only
# constructs a destination path string; no operation capable of modifying
# or replacing the hashed source file sits between this check and Copy-Item.
Invoke-ValidationCheck -Key "repository_probe_hash_pre_copy" `
    -Check { (Get-Sha256HexOfFile -Path $repoProbePath) -eq $expectedProbeHash } `
    -FailureMessage "repository probe hash did not match immediately before copying into evidence."

$copiedProbePath = Join-Path $evidenceDir "phase14_resolve_context_snapshot.py"
Copy-Item -LiteralPath $repoProbePath -Destination $copiedProbePath -ErrorAction Stop
Assert-OrdinaryFile -Path $copiedProbePath -Label "copied probe"

# Checkpoint 2 of 6: evidence-directory probe copy hash, checked just after
# copying (an intervening Assert-OrdinaryFile guard call reads the copy's
# file attributes but does not modify or replace its bytes).
$copiedProbeHash = $null
Invoke-ValidationCheck -Key "evidence_probe_hash_post_copy" `
    -Check { $script:copiedProbeHash = Get-Sha256HexOfFile -Path $copiedProbePath; $copiedProbeHash -eq $expectedProbeHash } `
    -FailureMessage "copied probe hash did not match immediately after copying into evidence."

$copiedRunbookPath = Join-Path $evidenceDir "phase14_live_snapshot_runbook.ps1"
Copy-Item -LiteralPath $executedRunbookPath -Destination $copiedRunbookPath -ErrorAction Stop
Assert-OrdinaryFile -Path $copiedRunbookPath -Label "copied runbook"
$copiedRunbookHash = Get-Sha256HexOfFile -Path $copiedRunbookPath
if ($copiedRunbookHash -ne $expectedRunbookHash) { throw "STOP: copied runbook hash does not match the manifest's approved runbook_sha256." }

$copiedContractPath = Join-Path $evidenceDir "PHASE14_READ_ONLY_COMPARISON_CONTRACT.md"
Copy-Item -LiteralPath $repoContractPath -Destination $copiedContractPath -ErrorAction Stop
Assert-OrdinaryFile -Path $copiedContractPath -Label "copied contract"
$copiedContractHash = Get-Sha256HexOfFile -Path $copiedContractPath
if ($copiedContractHash -ne $expectedContractHash) { throw "STOP: copied contract hash does not match the manifest's approved contract_sha256." }

$copiedManifestPath = Join-Path $evidenceDir "authorization_manifest.json"
[System.IO.File]::WriteAllBytes($copiedManifestPath, $manifestBytes)   # exact original bytes, not a reread or re-serialization
Assert-OrdinaryFile -Path $copiedManifestPath -Label "copied manifest"
$copiedManifestHash = Get-Sha256HexOfFile -Path $copiedManifestPath
if ($copiedManifestHash -ne $manifestHash) { throw "STOP: copied manifest hash does not match the hash computed from the original single read." }

@{
    probeScriptSha256    = $copiedProbeHash
    testFileSha256       = $expectedTestHash
    contractDocSha256    = $copiedContractHash
    runbookSha256        = $copiedRunbookHash
    manifestSha256       = $copiedManifestHash
    executionRevisionId  = $expectedRevisionId
    authorizedCommit     = $authorizedCommit
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir "hash_manifest.json") -Encoding UTF8

if ([string]::IsNullOrWhiteSpace($expectedProject) -or [string]::IsNullOrWhiteSpace($expectedTimeline)) {
    throw "STOP: expected project/timeline resolved empty for context $Context."
}

# ============================================================================
# Baselines
# ============================================================================
Get-Process | Select-Object Id, ProcessName, StartTime -ErrorAction SilentlyContinue |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir "baseline_processes.json") -Encoding UTF8
@{
    context               = $Context
    mode                  = $modeLabel
    expectedProject       = $expectedProject
    expectedTimeline      = $expectedTimeline
    head                  = $head
    originMaster          = $originMaster
    remoteMaster          = $remoteMaster
    pythonExecutable      = $pyPath
    pythonVersion         = "3.$($versionInfo.minor)"
    resolveProductVersion = $resolveProductVersion
    resolveFileVersion    = $resolveFileVersionRaw
    resolveScriptApi      = $env:RESOLVE_SCRIPT_API
    resolveScriptLib      = $env:RESOLVE_SCRIPT_LIB
    copiedProbeSha256     = $copiedProbeHash
    manifestSha256        = $copiedManifestHash
    capturedAt            = (Get-Date).ToUniversalTime().ToString("o")
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir "baseline_repo_env.json") -Encoding UTF8

# ============================================================================
# Checkpoints 3 and 4 of 6: repository and evidence probe hashes, run
# immediately before the point where a typed confirmation would be
# requested. This runs in BOTH modes -- preflight verifies the system is in
# a state where confirmation *could* safely proceed, without ever actually
# prompting for it.
# ============================================================================
Invoke-ValidationCheck -Key "repository_probe_hash_pre_confirmation" `
    -Check { (Get-Sha256HexOfFile -Path $repoProbePath) -eq $expectedProbeHash } `
    -FailureMessage "repository probe hash did not match immediately before the confirmation point."
Invoke-ValidationCheck -Key "evidence_probe_hash_pre_confirmation" `
    -Check { (Get-Sha256HexOfFile -Path $copiedProbePath) -eq $expectedProbeHash } `
    -FailureMessage "evidence probe copy hash did not match immediately before the confirmation point."

# ============================================================================
# Item 2: PREFLIGHT branch -- every check above this point already ran and
# already required Resolve.exe's version/env config to be correct, but
# nothing above this point contacted Resolve's scripting bridge. No
# Read-Host, no snapshot launch, on this path, ever. The two pre-launch
# checkpoints stay "not_run" in execution_validation.json because this
# branch returns before either of them could be reached.
# ============================================================================
if ($PreflightOnly) {
    $preflightResult = [ordered]@{
        context            = $Context
        resolveContact     = $false
        snapshotExecution  = $false
        preflightComplete  = $true
        manifestSha256     = $copiedManifestHash
        copiedProbeSha256  = $copiedProbeHash
        authorizedCommit   = $authorizedCommit
        validationSnapshot = $validation
        capturedAt         = (Get-Date).ToUniversalTime().ToString("o")
    }
    $preflightResult | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $evidenceDir "preflight_result.json") -Encoding UTF8

    if (Test-Path -LiteralPath $evidenceZip) { throw "STOP: preflight evidence zip unexpectedly already exists: $evidenceZip" }
    Compress-Archive -Path $evidenceDir -DestinationPath $evidenceZip -ErrorAction Stop

    $sourceFileCount = @(Get-ChildItem -LiteralPath $evidenceDir -File -Recurse).Count
    $zipItem = Get-Item -LiteralPath $evidenceZip
    $zipHash = (Get-FileHash -LiteralPath $evidenceZip -Algorithm SHA256).Hash

    Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
    $archive = [System.IO.Compression.ZipFile]::OpenRead($evidenceZip)
    $integrityFailures = @()
    try {
        $zipEntries = @($archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
        foreach ($entry in $zipEntries) {
            $entryStream = $entry.Open()
            $buffer = New-Object byte[] 81920
            $totalRead = 0
            while (($read = $entryStream.Read($buffer, 0, $buffer.Length)) -gt 0) { $totalRead += $read }
            $entryStream.Close()
            if ($totalRead -ne $entry.Length) { $integrityFailures += "$($entry.FullName): size mismatch" }
        }
        $zipEntryCount = $zipEntries.Count
    }
    finally {
        $archive.Dispose()
    }
    if ($zipEntryCount -ne $sourceFileCount) { throw "STOP: preflight ZIP entry count does not match evidence source-file count." }
    if ($integrityFailures.Count -ne 0) { throw "STOP: preflight archive integrity check failed." }

    Write-Host ""
    Write-Host "Resolve contact: false"
    Write-Host "Snapshot execution: false"
    Write-Host "Preflight complete: true"
    Write-Host ""
    Write-Host "Pre-copy checks:         attempted (repository_probe_hash_pre_copy = $($validation['repository_probe_hash_pre_copy']))"
    Write-Host "Post-copy checks:        attempted (evidence_probe_hash_post_copy = $($validation['evidence_probe_hash_post_copy']))"
    Write-Host "Pre-confirmation checks: attempted (repository_probe_hash_pre_confirmation = $($validation['repository_probe_hash_pre_confirmation']), evidence_probe_hash_pre_confirmation = $($validation['evidence_probe_hash_pre_confirmation']))"
    Write-Host "Pre-launch checks:       not_run (repository_probe_hash_pre_launch = $($validation['repository_probe_hash_pre_launch']), evidence_probe_hash_pre_launch = $($validation['evidence_probe_hash_pre_launch']))"
    Write-Host "Read-Host:               not called"
    Write-Host "Probe launch:            not called"
    Write-Host ""
    Write-Host "Preflight evidence directory: $evidenceDir"
    Write-Host "Preflight evidence ZIP:       $evidenceZip ($($zipItem.Length) bytes, SHA-256 $zipHash)"
    Write-Host "Every non-Resolve-contacting check for the $Context context passed."
    Write-Host "This does not authorize a live capture; that still requires a separate, non-preflight invocation with the typed confirmation."

    return
}

# ============================================================================
# LIVE CAPTURE branch -- everything below this point can contact Resolve.
# ============================================================================
Write-Host ""
Write-Host "About to contact a live DaVinci Resolve session for the $Context context."
Write-Host "This does not authorize a second capture or any comparison, repair, or mutation."
$expectedConfirmation = "CONFIRM-$($Context.ToUpper())-SNAPSHOT"
$confirmation = Read-Host "Type $expectedConfirmation to proceed, anything else aborts"
if ($confirmation -cne $expectedConfirmation) { throw "STOP: founder confirmation not given (exact case required)." }

Assert-RepoCheckpoint

# Checkpoints 5 and 6 of 6: repository and evidence probe hashes, run again
# after the typed confirmation, immediately before the process launches --
# genuinely distinct from checkpoints 3/4 above, separated by the operator
# actually typing the confirmation phrase, not a duplicate of the same check.
Invoke-ValidationCheck -Key "repository_probe_hash_pre_launch" `
    -Check { (Get-Sha256HexOfFile -Path $repoProbePath) -eq $expectedProbeHash } `
    -FailureMessage "repository probe hash did not match immediately before process launch."
Invoke-ValidationCheck -Key "evidence_probe_hash_pre_launch" `
    -Check { (Get-Sha256HexOfFile -Path $copiedProbePath) -eq $expectedProbeHash } `
    -FailureMessage "evidence probe copy hash did not match immediately before process launch."

$stdoutPath = Join-Path $evidenceDir "stdout.txt"
$stderrPath = Join-Path $evidenceDir "stderr.txt"
$startedAt = (Get-Date).ToUniversalTime().ToString("o")
$processStarted = $false
$exitCode = $null
try {
    $processResult = Invoke-NativeProcessCapture `
        -FilePath $pyPath `
        -Arguments @(
            $copiedProbePath,
            "snapshot",
            "--expected-project", $expectedProject,
            "--expected-timeline", $expectedTimeline,
            "--output", $outputPath,
            "--execution-authorization", $ExecutionAuthorization
        )
    $processStarted = $true
    $exitCode = $processResult.ExitCode

    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($stdoutPath, $processResult.Stdout, $utf8NoBom)
    [System.IO.File]::WriteAllText($stderrPath, $processResult.Stderr, $utf8NoBom)
}
catch {
    $finishedAt = (Get-Date).ToUniversalTime().ToString("o")
    @{
        context        = $Context
        processStarted = $false
        errorType      = $_.Exception.GetType().Name
        startedAt      = $startedAt
        finishedAt     = $finishedAt
        stdoutPath     = if (Test-Path -LiteralPath $stdoutPath) { $stdoutPath } else { $null }
        stderrPath     = if (Test-Path -LiteralPath $stderrPath) { $stderrPath } else { $null }
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir "execution_record.json") -Encoding UTF8
    Invoke-ValidationCheck -Key "exit_code_zero" -Check { $false } -FailureMessage "process failed to start; no automatic retry is authorized."
}
$finishedAt = (Get-Date).ToUniversalTime().ToString("o")
$copiedProbeHashAfterExit = Get-Sha256HexOfFile -Path $copiedProbePath

$outputHashAtRun = $null
if (Test-Path -LiteralPath $outputPath) { $outputHashAtRun = Get-Sha256HexOfFile -Path $outputPath }
@{
    context                  = $Context
    processStarted           = $processStarted
    exitCode                 = $exitCode
    startedAt                = $startedAt
    finishedAt                = $finishedAt
    outputPath               = $outputPath
    outputHash               = $outputHashAtRun
    copiedProbeHashAtLaunch  = $copiedProbeHash
    copiedProbeHashAfterExit = $copiedProbeHashAfterExit
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidenceDir "execution_record.json") -Encoding UTF8

Write-Host ""
Write-Host "Exit code: $exitCode"
# Snapshot JSON body is never printed, on success or failure.

Invoke-ValidationCheck -Key "exit_code_zero" -Check { $exitCode -eq 0 } `
    -FailureMessage "probe did not complete successfully (exit $exitCode). Evidence preserved: $evidenceDir. No automatic retry is authorized."

Invoke-ValidationCheck -Key "output_exists_as_file" -Check { Test-Path -LiteralPath $outputPath -PathType Leaf } `
    -FailureMessage "output file does not exist as an ordinary file."

Invoke-ValidationCheck -Key "output_hash_computed" -Check { $null -ne $outputHashAtRun -and $outputHashAtRun.Length -eq 64 } `
    -FailureMessage "output SHA-256 was not computed."

$script:parsedSnapshot = $null
Invoke-ValidationCheck -Key "json_parses" -Check {
    $rawJsonText = Get-Content -LiteralPath $outputPath -Raw
    $script:parsedSnapshot = $rawJsonText | ConvertFrom-Json -ErrorAction Stop
    $true
} -FailureMessage "output JSON did not parse."

Invoke-ValidationCheck -Key "snapshot_complete_is_true" -Check { $parsedSnapshot.snapshot_complete -eq $true } `
    -FailureMessage "snapshot_complete is not literally true."

Invoke-ValidationCheck -Key "expected_project_matches" -Check { $parsedSnapshot.expected_context.project -ceq $expectedProject } `
    -FailureMessage "expected_context.project does not match the selected context."
Invoke-ValidationCheck -Key "expected_timeline_matches" -Check { $parsedSnapshot.expected_context.timeline -ceq $expectedTimeline } `
    -FailureMessage "expected_context.timeline does not match the selected context."

Invoke-ValidationCheck -Key "pre_post_guard_identity_matches" -Check {
    ($parsedSnapshot.pre_guard.project_name -ceq $parsedSnapshot.post_guard.project_name) -and
    ($parsedSnapshot.pre_guard.current_timeline_name -ceq $parsedSnapshot.post_guard.current_timeline_name) -and
    ($parsedSnapshot.pre_guard.target_timeline_name -ceq $parsedSnapshot.post_guard.target_timeline_name)
} -FailureMessage "pre/post guard project or timeline identity differs."

# The probe never prints to stdout on a successful `snapshot` invocation
# (only `--print-sha256` does); require both stdout and stderr empty.
Invoke-ValidationCheck -Key "success_stdout_empty" -Check { (Get-Item -LiteralPath $stdoutPath).Length -eq 0 } `
    -FailureMessage "probe reported success but stdout is not empty."
Invoke-ValidationCheck -Key "success_stderr_empty" -Check { (Get-Item -LiteralPath $stderrPath).Length -eq 0 } `
    -FailureMessage "probe reported success but stderr is not empty."

Invoke-ValidationCheck -Key "repository_checkpoint_unchanged" -Check { Assert-RepoCheckpoint; $true } `
    -FailureMessage "repository checkpoint changed during capture."

Invoke-ValidationCheck -Key "repository_probe_hash_unchanged" -Check { (Get-Sha256HexOfFile -Path $repoProbePath) -eq $expectedProbeHash } `
    -FailureMessage "repository probe source changed during capture."

Invoke-ValidationCheck -Key "copied_probe_hash_unchanged" -Check { $copiedProbeHashAfterExit -eq $expectedProbeHash } `
    -FailureMessage "evidence-directory probe copy changed during capture."

Write-Host "All success-evidence validations passed; see execution_validation.json."

if ($Context -eq "Control") {
    Write-Host ""
    Write-Host "=== Control capture complete. Independent review required before the Production capture. ==="
    Write-Host "Re-run this script with -Context Production only after that review, as a separate confirmed invocation."
}

# ============================================================================
# Package evidence create-only, then verify and print integrity facts.
# ============================================================================
if (Test-Path -LiteralPath $evidenceZip) { throw "STOP: evidence zip unexpectedly already exists: $evidenceZip" }
Compress-Archive -Path $evidenceDir -DestinationPath $evidenceZip -ErrorAction Stop

$sourceFileCount = @(Get-ChildItem -LiteralPath $evidenceDir -File -Recurse).Count
$zipItem = Get-Item -LiteralPath $evidenceZip
$zipHash = (Get-FileHash -LiteralPath $evidenceZip -Algorithm SHA256).Hash

Add-Type -AssemblyName System.IO.Compression.FileSystem -ErrorAction Stop
$archive = [System.IO.Compression.ZipFile]::OpenRead($evidenceZip)
$integrityFailures = @()
try {
    $zipEntries = @($archive.Entries | Where-Object { -not [string]::IsNullOrEmpty($_.Name) })
    foreach ($entry in $zipEntries) {
        try {
            $entryStream = $entry.Open()
            $buffer = New-Object byte[] 81920
            $totalRead = 0
            while (($read = $entryStream.Read($buffer, 0, $buffer.Length)) -gt 0) { $totalRead += $read }
            $entryStream.Close()
            if ($totalRead -ne $entry.Length) {
                $integrityFailures += "$($entry.FullName): read $totalRead bytes, expected $($entry.Length)"
            }
        }
        catch {
            $integrityFailures += "$($entry.FullName): $($_.Exception.Message)"
        }
    }
    $zipEntryCount = $zipEntries.Count
}
finally {
    $archive.Dispose()
}
$integrityResult = if ($integrityFailures.Count -eq 0) { "PASS (full-read verification, $zipEntryCount entries)" } else { "FAIL: " + ($integrityFailures -join "; ") }

Write-Host ""
Write-Host "Evidence source-file count: $sourceFileCount"
Write-Host "ZIP file-entry count:       $zipEntryCount"
Write-Host "ZIP size bytes:             $($zipItem.Length)"
Write-Host "ZIP SHA-256:                $zipHash"
Write-Host "Archive integrity result:   $integrityResult"

if ($zipEntryCount -ne $sourceFileCount) { throw "STOP: ZIP entry count does not match evidence source-file count." }
if ($integrityFailures.Count -ne 0) { throw "STOP: archive integrity check failed." }

Write-Host ""
Write-Host "=== $Context capture complete. Evidence directory and ZIP are retained; neither is deleted or uploaded. ==="
Write-Host "Evidence directory: $evidenceDir"
Write-Host "Evidence ZIP:       $evidenceZip"
Write-Host "Successful capture does not authorize comparison, mutation, or a second capture."
Write-Host "Evidence must be reviewed by Paul before any further step."

}
catch {
    Write-RunbookFailure -ErrorRecord $_
    throw
}
