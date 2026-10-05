<#
.SYNOPSIS
  Raphael — generate a FEMALE reference voice for Fish-Speech TTS (scripts/win/make-ref-voice.ps1).
.DESCRIPTION
  Synthesizes a natural first-person reference sample with Microsoft Zira
  (en-US Female) via SAPI5, then the orchestrator resamples it to 24 kHz mono
  s16le at assets/raphael_reference.wav (config voice.tts_voice). Fish picks
  it up as the in-context reference; assets/acks/*.wav (old-timbre phrase
  cache) must be cleared after replacing the reference.
  Re-run any time to change her voice (drop a hand-made .wav at
  %TEMP%\raphael_ref_raw.wav first to override with your own sample).
#>
param(
    [string]$OutRaw = "$env:TEMP\raphael_ref_raw.wav"
)
Add-Type -AssemblyName System.Speech

$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $synth.GetInstalledVoices() |
    Where-Object { $_.VoiceInfo.Gender -eq 'Female' -and $_.Enabled } |
    Select-Object -First 1
if (-not $voice) {
    Write-Output "ERROR: no female voice installed"
    exit 2
}
$synth.SelectVoice($voice.VoiceInfo.Name)
$synth.Rate = 0   # natural pace
$synth.Volume = 100

Write-Output ("using voice: " + $voice.VoiceInfo.Name + " (" + $voice.VoiceInfo.Culture + ")")

$text = @(
    "Hi there. I'm Raphael, your desktop assistant.",
    "I can open your programs, search the web, take screenshots, and answer questions out loud.",
    "Just say my name and tell me what you need, or we can simply chat for a while.",
    "I'll keep your files safe and your screen tidy. What's on your mind today?"
) -join " "

$synth.SetOutputToWaveFile($OutRaw)
$synth.Speak($text)
$synth.Dispose()

Write-Output ("wrote " + $OutRaw)
