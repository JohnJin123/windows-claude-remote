using System;

// tailscale.exe shim for xEdge (Ganjiang Interconnect).
//
// MobileCLI's daemon calls `tailscale status --json` inside check_tailscale()
// (setup.rs) and reads three fields: BackendState, Self, TailscaleIPs[0].
// xEdge does not ship a `tailscale` CLI, so this shim reports a healthy
// "Tailscale-like" backend pointing at the machine's xEdge virtual IP, which
// makes the daemon bind its mobile listener to 100.64.0.1:9847.
class TailscaleShim
{
    static int Main(string[] args)
    {
        Console.Out.Write(
            "{\"BackendState\":\"Running\"," +
            "\"Self\":{\"ID\":\"xedge-shim\",\"HostName\":\"<YOUR-HOSTNAME>\"}," +
            "\"TailscaleIPs\":[\"100.64.0.1\"]}"
        );
        return 0;
    }
}
