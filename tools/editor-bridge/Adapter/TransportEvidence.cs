using System;
using System.Net;
using System.Net.Sockets;

namespace Miliastra.EditorBridge;
internal sealed partial class EditorAdapter
{
    // A private one-time recovery authorization cannot be transferred to this release.
    public object RepairAuthorizedSelfConnection(bool execute) =>
        throw new InvalidOperationException("PRIVATE_SESSION_RECOVERY_NOT_DISTRIBUTED");

    // Source-pinned 7.1 fields; no connection, callback, send or receive operation.
    static object ReadTransportSocket(object producer)
    {
        object ExactField(object value, string type, string name)
        {
            if(value.GetType().FullName!=type) throw new InvalidOperationException("TRANSPORT_TYPE_MISMATCH");
            var field=value.GetType().GetField(name,Fields) ?? throw new InvalidOperationException("TRANSPORT_FIELD_MISSING");
            return field.GetValue(value) ?? throw new InvalidOperationException("TRANSPORT_FIELD_NULL");
        }
        try
        {
            var connection=ExactField(producer,"x52KBmLggSIIWl2daSoU.lWk544LgWMa3fpb52XXU","pSOLbmc4VDX");
            var client=ExactField(connection,"fkRMW9LJfc3vB2lWsVBT.ObGe2ALJTlRR6A7SODdg","UIjLJgisgxj");
            var socket=ExactField(client,"V7eyUyLJ04dZOgDxBRVE.f9QwinLJYfKcdCQIZW9i","JeVLJKTAcD8") as Socket
                ?? throw new InvalidOperationException("TRANSPORT_NOT_SOCKET");
            var local=socket.LocalEndPoint as IPEndPoint;
            var remote=socket.RemoteEndPoint as IPEndPoint;
            bool loopback=local!=null && remote!=null && IPAddress.IsLoopback(local.Address) && IPAddress.IsLoopback(remote.Address);
            return new {observed=true,scope="existing-producer-socket-read-only",connectedFlag=socket.Connected,
                loopbackEndpoints=loopback,localPort=loopback?(int?)local!.Port:null,
                remotePort=loopback?(int?)remote!.Port:null,selfConnection=loopback && local!.Equals(remote),
                gamePeerVerified=false,protocolHandshakeVerified=false,currentLevelVerified=false};
        }
        catch(Exception ex) when(ex is InvalidOperationException || ex is SocketException || ex is ObjectDisposedException)
        {
            return new {observed=false,scope="existing-producer-socket-read-only",reason=ex.GetType().Name,
                gamePeerVerified=false,protocolHandshakeVerified=false,currentLevelVerified=false};
        }
    }
}
