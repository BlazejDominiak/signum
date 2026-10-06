param([Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
# DXGI reports dedicated memory as UInt64. WMI AdapterRAM truncates above 4 GB.
$source = @'
using System;
using System.Runtime.InteropServices;
public static class SignumGpu {
  [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)]
  public struct Desc {
    [MarshalAs(UnmanagedType.ByValTStr, SizeConst=128)] public string Name;
    public uint Vendor, Device, Subsystem, Revision;
    public UIntPtr Video, System, Shared;
    public long Luid; public uint Flags;
  }
  [DllImport("dxgi.dll")] static extern int CreateDXGIFactory1(ref Guid id, out IntPtr factory);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)]
  delegate int EnumAdapter(IntPtr self, uint index, out IntPtr adapter);
  [UnmanagedFunctionPointer(CallingConvention.StdCall)]
  delegate int GetDesc(IntPtr self, out Desc desc);
  static T Method<T>(IntPtr obj, int index) {
    return (T)(object)Marshal.GetDelegateForFunctionPointer(
      Marshal.ReadIntPtr(Marshal.ReadIntPtr(obj), index*IntPtr.Size), typeof(T));
  }
  public static string[] Read() {
    Guid id = new Guid("770aae78-f26f-4dba-a829-253c83d1b387");
    IntPtr factory; Marshal.ThrowExceptionForHR(CreateDXGIFactory1(ref id, out factory));
    ulong largest=0; uint vendor=0; string name="GPU not detected";
    try {
      var enumerate=Method<EnumAdapter>(factory,12);
      for(uint i=0;i<32;i++) {
        IntPtr adapter; if(enumerate(factory,i,out adapter)<0) break;
        try {
          Desc desc; Marshal.ThrowExceptionForHR(Method<GetDesc>(adapter,10)(adapter,out desc));
          ulong bytes=desc.Video.ToUInt64();
          if((desc.Flags&2)==0 && bytes>largest) {largest=bytes; vendor=desc.Vendor; name=desc.Name;}
        } finally {Marshal.Release(adapter);}
      }
    } finally {Marshal.Release(factory);}
    return new[]{(largest/1048576).ToString(),vendor.ToString(),name};
  }
}
'@
try {
  Add-Type -TypeDefinition $source
  $result = [SignumGpu]::Read()
} catch {
  $result = @('0','0','GPU detection failed')
}
[System.IO.File]::WriteAllLines($OutputPath,$result,[System.Text.UTF8Encoding]::new($true))
