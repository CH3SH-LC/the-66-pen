using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Windows;
using System.Windows.Threading;

namespace Miliastra.EditorBridge.TestHost
{
    /// <summary>
    /// Minimal WPF host with process name TestHost. It is never auto-started: the operator (or
    /// the test script) launches it. It only opens a window when --show is passed; otherwise the
    /// window exists but stays hidden so the process can run headless.
    ///
    /// Sequence:
    ///   1. create the WPF Application + a minimal Window (dispatcher is live before injection)
    ///   2. write host-info.json  { pid, startUtcTicks, exePath, ... }
    ///   3. wait for the bridge settings file to appear
    ///   4. Assembly.LoadFrom(bridge dll) -> Miliastra.EditorBridge.Entry.Start(settingsPath)
    ///   5. write result.json { code, ... } and keep the dispatcher alive until the timeout
    /// </summary>
    internal static class Program
    {
        [STAThread]
        private static int Main(string[] args)
        {
            HostOptions options;
            try
            {
                options = HostOptions.Parse(args);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("bad arguments: " + ex.Message);
                Console.Error.WriteLine(HostOptions.Usage);
                return 2;
            }

            if (options.ShowHelp)
            {
                Console.WriteLine(HostOptions.Usage);
                return 2;
            }

            try
            {
                return Run(options);
            }
            catch (Exception ex)
            {
                Console.Error.WriteLine("fatal: " + ex.GetType().Name + ": " + ex.Message);
                return 3;
            }
        }

        private static int Run(HostOptions options)
        {
            var application = new Application
            {
                ShutdownMode = ShutdownMode.OnExplicitShutdown,
            };

            var window = new Window
            {
                Title = "TestHost",
                Width = 320,
                Height = 200,
                WindowStartupLocation = WindowStartupLocation.CenterScreen,
                ShowInTaskbar = options.Show,
                Visibility = Visibility.Hidden,
            };
            window.Closed += (_, _) => application.Shutdown();

            using var process = Process.GetCurrentProcess();
            var startUtcTicks = process.StartTime.ToUniversalTime().Ticks;
            var hostExe = process.MainModule?.FileName ?? Environment.ProcessPath ?? string.Empty;
            var hostPid = process.Id;

            WriteJsonAtomically(options.HostInfoPath, new Dictionary<string, object?>
            {
                ["pid"] = hostPid,
                ["startUtcTicks"] = startUtcTicks.ToString(CultureInfo.InvariantCulture),
                ["exePath"] = hostExe,
                ["recordedUtc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["framework"] = System.Runtime.InteropServices.RuntimeInformation.FrameworkDescription,
                ["bridgeDll"] = options.BridgeDllPath,
                ["settingsPath"] = options.SettingsPath,
            });
            Console.WriteLine("host-info written: pid=" + hostPid.ToString(CultureInfo.InvariantCulture));

            if (options.Show)
            {
                window.Show();
            }

            if (!options.NoAutoload)
            {
            if (!WaitForFile(options.SettingsPath, options.WaitSettingsSeconds))
            {
                WriteResult(options, -1, "settings_file_did_not_appear");
                Console.WriteLine("result: -1 settings_file_did_not_appear");
                return 4;
            }

            var code = InvokeBridgeEntry(options.SettingsPath, options.BridgeDllPath, out var invokeError);
            WriteResult(options, code, invokeError);
            Console.WriteLine(
                "result: "
                + code.ToString(CultureInfo.InvariantCulture)
                + (invokeError == null ? string.Empty : " " + invokeError));

            }

            var timer = new DispatcherTimer(DispatcherPriority.Background)
            {
                Interval = TimeSpan.FromSeconds(options.TimeoutSeconds),
            };
            timer.Tick += (_, _) =>
            {
                timer.Stop();
                Console.WriteLine("timeout reached; exiting");
                application.Shutdown();
            };
            timer.Start();

            application.Run();
            return 0;
        }

        /// <summary>Reflection call into the injected-assembly entry point; no compile-time link.</summary>
        private static int InvokeBridgeEntry(string settingsPath, string bridgeDllPath, out string? error)
        {
            error = null;
            try
            {
                if (!File.Exists(bridgeDllPath))
                {
                    error = "bridge_dll_missing";
                    return -1;
                }

                var assembly = Assembly.LoadFrom(bridgeDllPath);
                var entryType = assembly.GetType("Miliastra.EditorBridge.Entry", throwOnError: true, ignoreCase: false);
                var start = entryType!.GetMethod(
                    "Start",
                    BindingFlags.Public | BindingFlags.Static,
                    binder: null,
                    types: new[] { typeof(string) },
                    modifiers: null);
                if (start == null)
                {
                    error = "entry_method_missing";
                    return -1;
                }

                var value = start.Invoke(null, new object?[] { settingsPath });
                return value is int result ? result : -1;
            }
            catch (TargetInvocationException ex)
            {
                error = "entry_threw:" + (ex.InnerException?.GetType().Name ?? ex.GetType().Name);
                return -1;
            }
            catch (Exception ex)
            {
                error = "entry_load_failed:" + ex.GetType().Name;
                return -1;
            }
        }

        private static bool WaitForFile(string path, int seconds)
        {
            var deadline = DateTime.UtcNow.AddSeconds(seconds);
            while (DateTime.UtcNow < deadline)
            {
                if (File.Exists(path))
                {
                    // Guard against observing a partially written file.
                    try
                    {
                        using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
                        if (stream.Length > 0)
                        {
                            return true;
                        }
                    }
                    catch (IOException)
                    {
                        // Still being written; retry.
                    }
                }
                Thread.Sleep(100);
            }
            return false;
        }

        private static void WriteResult(HostOptions options, int code, string? error)
        {
            WriteJsonAtomically(options.ResultPath, new Dictionary<string, object?>
            {
                ["code"] = code,
                ["error"] = error,
                ["calledUtc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["settingsPath"] = options.SettingsPath,
                ["bridgeDll"] = options.BridgeDllPath,
            });
        }

        private static void WriteJsonAtomically(string path, Dictionary<string, object?> payload)
        {
            var directory = Path.GetDirectoryName(path);
            if (!string.IsNullOrEmpty(directory))
            {
                Directory.CreateDirectory(directory);
            }

            var json = JsonSerializer.Serialize(payload);
            var temp = path + ".tmp";
            File.WriteAllText(temp, json + "\n", new UTF8Encoding(false));
            File.Move(temp, path, overwrite: true);
        }
    }

    internal sealed class HostOptions
    {
        internal const string Usage =
            "TestHost --settings <json> --bridge <dll> [--host-info <json>] [--result <json>]\n"
            + "         [--show] [--timeout <seconds>] [--wait-settings <seconds>]\n"
            + "Defaults derive from the project root (nearest ancestor containing .runtime).";

        internal string SettingsPath { get; private set; } = string.Empty;
        internal string BridgeDllPath { get; private set; } = string.Empty;
        internal string HostInfoPath { get; private set; } = string.Empty;
        internal string ResultPath { get; private set; } = string.Empty;
        internal bool Show { get; private set; }
        internal bool ShowHelp { get; private set; }
        internal bool NoAutoload { get; private set; }
        internal int TimeoutSeconds { get; private set; } = 300;
        internal int WaitSettingsSeconds { get; private set; } = 30;

        internal static HostOptions Parse(string[] args)
        {
            var options = new HostOptions();
            var root = FindProjectRoot();
            var runtimeDir = root == null ? null : Path.Combine(root, ".runtime", "editor-bridge");
            var testsDir = runtimeDir == null ? null : Path.Combine(runtimeDir, "tests");

            for (var i = 0; i < args.Length; i++)
            {
                var key = args[i];
                string Next()
                {
                    if (i + 1 >= args.Length)
                    {
                        throw new ArgumentException("missing value for " + key);
                    }
                    return args[++i];
                }

                switch (key)
                {
                    case "--settings":
                        options.SettingsPath = Path.GetFullPath(Next());
                        break;
                    case "--bridge":
                        options.BridgeDllPath = Path.GetFullPath(Next());
                        break;
                    case "--host-info":
                        options.HostInfoPath = Path.GetFullPath(Next());
                        break;
                    case "--result":
                        options.ResultPath = Path.GetFullPath(Next());
                        break;
                    case "--no-autoload":
                        options.NoAutoload = true;
                        break;
                    case "--show":
                        options.Show = true;
                        break;
                    case "--timeout":
                        options.TimeoutSeconds = int.Parse(Next(), CultureInfo.InvariantCulture);
                        break;
                    case "--wait-settings":
                        options.WaitSettingsSeconds = int.Parse(Next(), CultureInfo.InvariantCulture);
                        break;
                    case "--help":
                    case "-h":
                        options.ShowHelp = true;
                        break;
                    default:
                        throw new ArgumentException("unknown argument " + key);
                }
            }

            if (options.SettingsPath.Length == 0 && runtimeDir != null)
            {
                options.SettingsPath = Path.Combine(runtimeDir, "bridge-settings.json");
            }
            if (options.HostInfoPath.Length == 0)
            {
                options.HostInfoPath = Path.Combine(testsDir ?? Path.GetTempPath(), "host-info.json");
            }
            if (options.ResultPath.Length == 0)
            {
                options.ResultPath = Path.Combine(testsDir ?? Path.GetTempPath(), "host-result.json");
            }

            if (options.SettingsPath.Length == 0 || options.BridgeDllPath.Length == 0)
            {
                throw new ArgumentException("--settings and --bridge are required");
            }

            return options;
        }

        private static string? FindProjectRoot()
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory != null)
            {
                if (Directory.Exists(Path.Combine(directory.FullName, ".runtime")))
                {
                    return directory.FullName;
                }
                directory = directory.Parent;
            }
            return null;
        }
    }
}
