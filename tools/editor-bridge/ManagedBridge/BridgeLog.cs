using System;
using System.Globalization;
using System.IO;
using System.Text;

namespace Miliastra.EditorBridge
{
    /// <summary>
    /// Project-local append-only log. Never receives secrets: callers must not pass the
    /// config nonce, and this type deliberately has no formatting helper that would echo
    /// arbitrary request payloads.
    /// </summary>
    internal static class BridgeLog
    {
        private const long MaxBytes = 1L * 1024 * 1024;
        private static readonly object Gate = new object();
        private static string? _path;

        internal static void Init(string path)
        {
            lock (Gate)
            {
                _path = path;
            }
        }

        internal static void Write(string message)
        {
            string? path;
            lock (Gate)
            {
                path = _path;
            }
            if (string.IsNullOrEmpty(path))
            {
                return;
            }
            try
            {
                var line = string.Format(
                    CultureInfo.InvariantCulture,
                    "{0:yyyy-MM-ddTHH:mm:ss.fffZ} {1}{2}",
                    DateTime.UtcNow,
                    message,
                    Environment.NewLine);
                lock (Gate)
                {
                    var info = new FileInfo(path);
                    if (info.Exists && info.Length > MaxBytes)
                    {
                        return;
                    }
                    File.AppendAllText(path, line, new UTF8Encoding(false));
                }
            }
            catch (Exception)
            {
                // Logging must never break the bridge.
            }
        }
    }
}
