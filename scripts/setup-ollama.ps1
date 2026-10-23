<#
.SYNOPSIS
    Pulls the Ollama models DocQA needs and checks that they work.
.DESCRIPTION
    Reads LLM_MODEL, EMBEDDING_MODEL and EMBEDDING_DIM from .env (or .env.example if
    there is no .env yet), pulls both models, checks the embedding size matches
    EMBEDDING_DIM, and loads the LLM once to prove it fits in memory.
    Safe to re-run: models you already have are only updated.
.EXAMPLE
    .\scripts\setup-ollama.ps1
#>
param(
    # The script runs on the host, so it talks to Ollama on localhost
    [string]$OllamaUrl = 'http://localhost:11434'
)

$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $repoRoot '.env'
if (-not (Test-Path $envFile)) {
    $envFile = Join-Path $repoRoot '.env.example'
}

# Read KEY=value lines; comments and blank lines don't match
$config = @{}
foreach ($line in Get-Content $envFile) {
    if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$') {
        $config[$Matches[1]] = $Matches[2]
    }
}
foreach ($key in 'LLM_MODEL', 'EMBEDDING_MODEL', 'EMBEDDING_DIM') {
    if (-not $config[$key]) { throw "$key is missing from $envFile" }
}
$llm = $config['LLM_MODEL']
$embedder = $config['EMBEDDING_MODEL']
$expectedDim = [int]$config['EMBEDDING_DIM']

if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
    throw 'ollama is not on PATH. Install it from https://ollama.com/download, then open a new terminal.'
}
try {
    $version = Invoke-RestMethod "$OllamaUrl/api/version" -TimeoutSec 5
} catch {
    throw "Ollama is not answering at $OllamaUrl. Start the Ollama app (or run 'ollama serve') and try again."
}
Write-Host "Ollama $($version.version) at $OllamaUrl (settings from $envFile)"

foreach ($model in $llm, $embedder) {
    Write-Host "`nPulling $model ..."
    ollama pull $model
    if ($LASTEXITCODE -ne 0) { throw "ollama pull $model failed" }
}

Write-Host "`nChecking $embedder ..."
$body = @{ model = $embedder; input = 'hello' } | ConvertTo-Json
$result = Invoke-RestMethod "$OllamaUrl/api/embed" -Method Post -Body $body -ContentType 'application/json'
$dim = @($result.embeddings[0]).Count
if ($dim -ne $expectedDim) {
    throw "$embedder returns $dim dimensions but EMBEDDING_DIM is $expectedDim. Make them match in .env."
}
Write-Host "Embeddings OK: $dim dimensions"

# A request with no prompt only loads the model, which proves it fits in memory
Write-Host "`nLoading $llm (the first load can take a minute) ..."
$body = @{ model = $llm } | ConvertTo-Json
Invoke-RestMethod "$OllamaUrl/api/generate" -Method Post -Body $body -ContentType 'application/json' -TimeoutSec 600 | Out-Null
Write-Host "LLM OK: $llm loaded"

Write-Host "`nDone. Try it: ollama run $llm"
