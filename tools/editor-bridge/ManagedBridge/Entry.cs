using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Text;
using System.Text.Json;
using System.Threading;

namespace Miliastra.EditorBridge
{
    /// <summary>
    /// Snoop <c>ExecuteInDefaultAppDomain</c> entry point.
    ///
    /// Contract: <c>public static int Miliastra.EditorBridge.Entry.Start(string settingsPath)</c>
    /// Returns 0 when the listener was accepted, or a positive rejection code (see the Code*
    /// constants). Every rejection path performs no operation and never touches another process.
    ///
    /// The interlocked flag excludes concurrent Start calls and is reset in finally. An
    /// accepted worker excludes another scope until its cleanup and quiescence complete.
    /// The same loaded revision can then accept a fresh settings path, pipe and nonce;
    /// accepted scope identities are never reused. Changed implementation bytes still
    /// require a new assembly identity to avoid Assembly.LoadFrom's cached old code.
    /// </summary>
    public static class Entry
    {
        public const int CodeStarted = 0;
        public const int CodeAlreadyStarted = 1;
        public const int CodeSettingsPathRejected = 2;
        public const int CodeSettingsInvalid = 3;
        public const int CodePidMismatch = 4;
        public const int CodeStartTimeMismatch = 5;
        public const int CodeLeaseExpired = 6;
        public const int CodeTargetExeRejected = 7;
        public const int CodePipeUnavailable = 8;
        public const int CodeInternalError = 9;
        public const int CodeScopeReplay = 10;
        public const int CodeScopeLimit = 11;

        public const string SettingsFileName = "bridge-settings.json";
        public const string ReadyFileName = "bridge-ready.json";
        public const string LogFileName = "bridge.log";

        /// <summary>Settings must live under the project runtime folder: .runtime/editor-bridge/.</summary>
        private const string RuntimeSegment = @"\.runtime\editor-bridge\";

        private const int MaxSettingsBytes = 64 * 1024;

        private static readonly string[] AllowedExeNames = { "BeyondEditor.exe", "TestHost.exe" };
        private static readonly string[] ForbiddenExeFragments = { "yuanshen", "genshinimpact", "yuanshenlauncher" };

        private static int _startAttempted;
        private static BridgeServer? _server;
        private static readonly HashSet<string> UsedScopes=new(StringComparer.OrdinalIgnoreCase);
        private static ProcessFacts? _facts;

        /// <summary>Diagnostic accessor for the in-process test host. Never returns secrets.</summary>
        internal static ProcessFacts? Facts => _facts;

        public static int Start(string settingsPath)
        {
            if (Interlocked.CompareExchange(ref _startAttempted, 1, 0) != 0)
            {
                return CodeAlreadyStarted;
            }

            string? settingsDirectory = null;
            string? rejectionReason = null;
            var code = CodeInternalError;

            try
            {
                if(_server!=null && !_server.IsCompleted)return CodeAlreadyStarted;
                if (string.IsNullOrWhiteSpace(settingsPath))
                {
                    return Record(null, CodeSettingsPathRejected, "settings_path_empty", null);
                }

                string fullPath;
                try
                {
                    fullPath = Path.GetFullPath(settingsPath);
                }
                catch (Exception ex)
                {
                    return Record(null, CodeSettingsPathRejected, "settings_path_malformed:" + ex.GetType().Name, null);
                }

                if (!Path.IsPathFullyQualified(fullPath)
                    || fullPath.IndexOf(RuntimeSegment, StringComparison.OrdinalIgnoreCase) < 0
                    || !string.Equals(Path.GetFileName(fullPath), SettingsFileName, StringComparison.OrdinalIgnoreCase))
                {
                    return Record(null, CodeSettingsPathRejected, "settings_path_not_in_runtime_dir", null);
                }

                settingsDirectory = Path.GetDirectoryName(fullPath);
                BridgeLog.Init(Path.Combine(settingsDirectory!, LogFileName));

                if (!File.Exists(fullPath))
                {
                    return Record(settingsDirectory, CodeSettingsPathRejected, "settings_file_missing", null);
                }

                var info = new FileInfo(fullPath);
                if (info.Length > MaxSettingsBytes)
                {
                    return Record(settingsDirectory, CodeSettingsPathRejected, "settings_file_too_large", null);
                }

                BridgeSettings settings;
                try
                {
                    var json = File.ReadAllText(fullPath, new UTF8Encoding(false));
                    settings = JsonSerializer.Deserialize<BridgeSettings>(json, BridgeJson.Read)
                               ?? throw new JsonException("settings document is null");
                }
                catch (Exception ex) when (ex is JsonException || ex is NotSupportedException || ex is DecoderFallbackException)
                {
                    return Record(settingsDirectory, CodeSettingsInvalid, "settings_json_invalid:" + ex.GetType().Name, null);
                }

                var invalid = settings.Validate();
                if (invalid != null)
                {
                    return Record(settingsDirectory, CodeSettingsInvalid, invalid, null);
                }

                var facts = ReadProcessFacts();
                if (facts == null)
                {
                    return Record(settingsDirectory, CodeTargetExeRejected, "process_facts_unavailable", settings);
                }
                _facts = facts;

                // Target allowlist: exact file name, absolute path, and never the game client.
                var expectedName = Path.GetFileName(settings.ExpectedExe);
                var allowedName = false;
                foreach (var candidate in AllowedExeNames)
                {
                    if (string.Equals(expectedName, candidate, StringComparison.OrdinalIgnoreCase))
                    {
                        allowedName = true;
                        break;
                    }
                }
                if (!allowedName || ContainsForbiddenFragment(settings.ExpectedExe))
                {
                    return Record(settingsDirectory, CodeTargetExeRejected, "expected_exe_not_allowed", settings);
                }
                if (ContainsForbiddenFragment(facts.ExePath))
                {
                    return Record(settingsDirectory, CodeTargetExeRejected, "host_process_forbidden", settings);
                }

                string expectedFullPath;
                try
                {
                    expectedFullPath = Path.GetFullPath(settings.ExpectedExe);
                }
                catch (Exception ex)
                {
                    return Record(settingsDirectory, CodeTargetExeRejected, "expected_exe_malformed:" + ex.GetType().Name, settings);
                }

                if (!string.Equals(expectedFullPath, facts.ExePath, StringComparison.OrdinalIgnoreCase))
                {
                    return Record(settingsDirectory, CodeTargetExeRejected, "expected_exe_mismatch", settings);
                }

                if (settings.Pid != facts.Pid)
                {
                    return Record(settingsDirectory, CodePidMismatch, "pid_mismatch", settings);
                }

                if (settings.StartUtcTicks != facts.StartUtcTicks)
                {
                    return Record(settingsDirectory, CodeStartTimeMismatch, "start_utc_ticks_mismatch", settings);
                }

                var nowUtc = DateTimeOffset.UtcNow;
                if (nowUtc > settings.ExpiresAtUtc)
                {
                    return Record(settingsDirectory, CodeLeaseExpired, "settings_expired", settings);
                }

                var scopeKeys=new[]{"path:"+fullPath,"pipe:"+settings.PipeName,"nonce:"+settings.Nonce};
                foreach(var key in scopeKeys)if(UsedScopes.Contains(key))
                    return Record(settingsDirectory,CodeScopeReplay,"scope_already_used",settings);
                if(UsedScopes.Count>=768)return Record(settingsDirectory,CodeScopeLimit,"scope_limit_reached",settings);
                NamedPipeServerStream pipe;
                try
                {
                    pipe = new NamedPipeServerStream(
                        settings.PipeName,
                        PipeDirection.InOut,
                        maxNumberOfServerInstances: 1,
                        PipeTransmissionMode.Byte,
                        PipeOptions.Asynchronous | PipeOptions.CurrentUserOnly,
                        inBufferSize: 64 * 1024,
                        outBufferSize: 64 * 1024);
                }
                catch (Exception ex) when (ex is IOException || ex is UnauthorizedAccessException || ex is ArgumentException)
                {
                    return Record(settingsDirectory, CodePipeUnavailable, "pipe_create_failed:" + ex.GetType().Name, settings);
                }

                BridgeServer server;
                try{server=new BridgeServer(settings,facts,pipe,settingsDirectory!);}
                catch{pipe.Dispose();throw;}
                foreach(var key in scopeKeys)UsedScopes.Add(key);
                _server = server;
                server.StartWorker();

                code = CodeStarted;
                rejectionReason = null;
                BridgeLog.Write("bridge accepted for pid " + facts.Pid.ToString(CultureInfo.InvariantCulture));
                return Record(settingsDirectory, code, rejectionReason, settings);
            }
            catch (Exception ex)
            {
                code = CodeInternalError;
                rejectionReason = "unhandled:" + ex.GetType().Name;
                try
                {
                    BridgeLog.Write("entry unhandled: " + ex.GetType().Name + ": " + ex.Message);
                }
                catch (Exception)
                {
                    // Nothing else to do.
                }
                return Record(settingsDirectory, code, rejectionReason, null);
            }
            finally {Volatile.Write(ref _startAttempted,0);}
        }

        private static bool ContainsForbiddenFragment(string path)
        {
            foreach (var fragment in ForbiddenExeFragments)
            {
                if (path.IndexOf(fragment, StringComparison.OrdinalIgnoreCase) >= 0)
                {
                    return true;
                }
            }
            return false;
        }

        private static ProcessFacts? ReadProcessFacts()
        {
            try
            {
                using var process = Process.GetCurrentProcess();
                var startUtc = process.StartTime.ToUniversalTime();
                var exePath = process.MainModule?.FileName;
                if (string.IsNullOrEmpty(exePath))
                {
                    exePath = Environment.ProcessPath;
                }
                if (string.IsNullOrEmpty(exePath))
                {
                    return null;
                }
                return new ProcessFacts
                {
                    Pid = process.Id,
                    StartUtcTicks = startUtc.Ticks,
                    ExePath = Path.GetFullPath(exePath!),
                };
            }
            catch (Exception ex)
            {
                BridgeLog.Write("process facts unavailable: " + ex.GetType().Name);
                return null;
            }
        }

        /// <summary>
        /// Writes the first startup record for this settings directory. An existing ready
        /// file is never overwritten; record-write failures are logged, not rewritten.
        /// Secrets (the nonce) are never included.
        /// </summary>
        private static int Record(string? settingsDirectory, int code, string? reason, BridgeSettings? settings)
        {
            if (string.IsNullOrEmpty(settingsDirectory))
            {
                return code;
            }

            try
            {
                var payload = new Dictionary<string, object?>
                {
                    ["recordedUtc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                    ["code"] = code,
                    ["accepted"] = code == CodeStarted,
                    ["reason"] = reason,
                    ["hostPid"] = _facts?.Pid,
                    ["hostStartUtcTicks"] = _facts?.StartUtcTicks.ToString(CultureInfo.InvariantCulture),
                    ["hostExePath"] = _facts?.ExePath,
                    ["settingsPid"] = settings?.Pid,
                    ["settingsStartUtcTicks"] = settings?.StartUtcTicks.ToString(CultureInfo.InvariantCulture),
                    ["settingsExpectedExe"] = settings?.ExpectedExe,
                    ["settingsExpiresUtc"] = settings?.ExpiresUtc,
                    ["pipeName"] = settings?.PipeName,
                    ["leaseSeconds"] = (int)BridgeServer.Lease.TotalSeconds,
                    ["framework"] = RuntimeInformation.FrameworkDescription,
                    ["bridgeVersion"] = typeof(Entry).Assembly.GetName().Version?.ToString() ?? "unknown",
                    ["bridgeAssembly"] = BuildIdentity.Snapshot(),
                    ["readyWritten"] = true,
                    ["readyWriteFailure"] = null,
                };

                var path = Path.Combine(settingsDirectory, ReadyFileName);
                var json = JsonSerializer.Serialize(payload, BridgeJson.Write);
                using (var stream = new FileStream(path, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false)))
                {
                    writer.Write(json);
                    writer.Write('\n');
                }
            }
            catch (IOException)
            {
                // Almost always "already exists": the first record is the one we keep.
                BridgeLog.Write("ready file not written (exists or io error); code=" + code.ToString(CultureInfo.InvariantCulture));
            }
            catch (Exception ex)
            {
                BridgeLog.Write("ready file not written: " + ex.GetType().Name);
            }

            return code;
        }
    }
}
