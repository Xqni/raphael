<#
.SYNOPSIS
  Raphael — master endpoint mute with roundtrip verification (scripts/win/mute.ps1).

.DESCRIPTION
  Used by E2E tests so TTS playback never blares while the user sleeps.
  Core Audio IAudioEndpointVolume COM interop; every action is VERIFIED by a
  GetMute roundtrip — if the vtable layout were wrong, GetMute would not echo
  the set state and this script throws (fail-closed: no silent mismatches).

  Vtable layout: EXACT endpointvolume.h IDL order (verified against the
  real SDK header — first attempt used a wrong memory layout and landed on
  VolumeStepUp/VolumeStepDown; net volume change was zero by luck).

.PARAMETER Action
  Query | On | Off

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -File scripts\win\mute.ps1 -Action On
#>
param(
    [ValidateSet('Query', 'On', 'Off')]
    [string]$Action = 'Query'
)

Add-Type -ErrorAction Stop -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

[Guid("5CDF2C82-841E-4546-9722-0CF74078229A"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IAudioEndpointVolume {
    // EXACT endpointvolume.h IDL vtable order (fetched from the real SDK
    // header after my memory-based layout landed on VolumeStepUp/Down).
    int RegisterControlChangeNotify(IntPtr pNotify);
    int UnregisterControlChangeNotify(IntPtr pNotify);
    int GetChannelCount(out uint pnChannelCount);
    int SetMasterVolumeLevel(float fLevelDB, ref Guid pguidEventContext);
    int SetMasterVolumeLevelScalar(float fLevel, ref Guid pguidEventContext);   // slot5: Scalar BEFORE Get
    int GetMasterVolumeLevel(out float pfLevelDB);
    int GetMasterVolumeLevelScalar(out float pfLevel);
    int SetChannelVolumeLevel(uint nChannel, float fLevelDB, ref Guid pguidEventContext);
    int SetChannelVolumeLevelScalar(uint nChannel, float fLevel, ref Guid pguidEventContext);
    int GetChannelVolumeLevel(uint nChannel, out float pfLevelDB);
    int GetChannelVolumeLevelScalar(uint nChannel, out float pfLevel);
    int SetMute([MarshalAs(UnmanagedType.Bool)] bool bMute, ref Guid pguidEventContext);   // slot12
    int GetMute([MarshalAs(UnmanagedType.Bool)] out bool pbMute);                          // slot13
    int GetVolumeStepInfo(out uint pnStep, out uint pnStepCount);
    int VolumeStepUp(ref Guid pguidEventContext);
    int VolumeStepDown(ref Guid pguidEventContext);
    int QueryHardwareSupport(out uint pdwHardwareSupportMask);
    int GetVolumeRange(out float pflVolumeMindB, out float pflVolumeMaxdB, out float pflVolumeIncrementdB);
}

[Guid("D666063F-1587-4E43-81F1-B948E807363F"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDevice {
    int Activate(ref Guid iid, uint clsCtx, IntPtr activationParams, [MarshalAs(UnmanagedType.Interface)] out object iface);
}

[Guid("A95664D2-9614-4F35-A746-DE8DB63617E6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
interface IMMDeviceEnumerator {
    int EnumAudioEndpoints(int dataFlow, uint stateMask, out IntPtr devices);
    int GetDefaultAudioEndpoint(int dataFlow, int role, out IMMDevice endpoint);
}

[ComImport, Guid("BCDE0395-E52F-467C-8E3D-C4579291692E")]
class MMDeviceEnumeratorComObject { }

public static class CoreAudio {
    static IAudioEndpointVolume Vol() {
        var enumr = new MMDeviceEnumeratorComObject() as IMMDeviceEnumerator;
        IMMDevice dev;
        enumr.GetDefaultAudioEndpoint(0 /*eRender*/, 1 /*eMultimedia*/, out dev);
        Guid iid = typeof(IAudioEndpointVolume).GUID;
        object o;
        dev.Activate(ref iid, 0x17 /*CLSCTX_ALL*/, IntPtr.Zero, out o);
        return o as IAudioEndpointVolume;
    }
    public static bool GetMute() {
        bool m;
        int hr = Vol().GetMute(out m);
        if (hr != 0) throw new COMException("GetMute hr=0x" + hr.ToString("X8"), hr);
        return m;
    }
    public static void SetMute(bool mute) {
        Guid g = Guid.Empty;
        int hr = Vol().SetMute(mute, ref g);
        if (hr != 0) throw new COMException("SetMute hr=0x" + hr.ToString("X8"), hr);
    }
}
'@

if (-not ('CoreAudio' -as [type])) {
    throw 'Add-Type did not produce CoreAudio — aborting (never claim success on a missing type)'
}

switch ($Action) {
    'Query' {
        Write-Output ("mute=" + [CoreAudio]::GetMute())
    }
    'On' {
        [CoreAudio]::SetMute($true)
        $m = [CoreAudio]::GetMute()
        if (-not $m) { throw "roundtrip failed: SetMute(true) but GetMute()=false" }
        Write-Output "muted (roundtrip OK)"
    }
    'Off' {
        [CoreAudio]::SetMute($false)
        $m = [CoreAudio]::GetMute()
        if ($m) { throw "roundtrip failed: SetMute(false) but GetMute()=true" }
        Write-Output "unmuted (roundtrip OK)"
    }
}
