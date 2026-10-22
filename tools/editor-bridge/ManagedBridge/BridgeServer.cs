using System;
using System.Buffers;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.IO.Pipes;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;

namespace Miliastra.EditorBridge
{
    internal sealed class ProcessFacts
    {
        internal int Pid { get; init; }
        internal long StartUtcTicks { get; init; }
        internal string ExePath { get; init; } = string.Empty;
    }

    /// <summary>
    /// Request/response bridge over one current-user-only named pipe.
    ///
    /// Lifecycle: created synchronously by <see cref="Entry.Start(string)"/> (so a bad pipe name
    /// fails immediately), then served on a background task. The total lease is five minutes;
    /// the lease cancellation token disposes the listener. Nothing here ever unloads the host
    /// AppDomain, terminates the host process, or invokes a reflected method.
    /// </summary>
    internal sealed class BridgeServer : IDisposable
    {
        internal const int MaxLineBytes = 16 * 1024;
        internal const int MaxDescribeTypes = 16;
        internal const int MaxTypeNameLength = 200;
        internal static readonly TimeSpan Lease = TimeSpan.FromMinutes(5);

        private static readonly string[] DefaultDescribeTypes =
        {
            "Miliastra.EditorBridge.Entry",
            "Miliastra.EditorBridge.BridgeSettings",
            "Miliastra.EditorBridge.BridgeServer",
        };

        private static readonly Regex TypeNamePattern = new Regex(
            @"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*(\+[A-Za-z_][A-Za-z0-9_]*)?$",
            RegexOptions.CultureInvariant,
            TimeSpan.FromSeconds(1));

        private readonly BridgeSettings _settings;
        private readonly ProcessFacts _facts;
        private readonly byte[] _nonceBytes;
        private readonly byte[] _zeroNonce = new byte[BridgeSettings.NonceBytes];
        private readonly CancellationTokenSource _lease;
        private readonly NamedPipeServerStream _pipe;
        private int _pipeDisposed;

        private readonly EditorAdapter _adapter=new();
        private readonly string _directory;
        private int _completed;
        internal bool IsCompleted => Volatile.Read(ref _completed)==1;

        internal BridgeServer(BridgeSettings settings, ProcessFacts facts, NamedPipeServerStream pipe, string directory)
        {
            _settings = settings;
            _directory = directory;
            _facts = facts;
            _pipe = pipe;
            _nonceBytes = DecodeHex(settings.Nonce);
            var remaining = settings.ExpiresAtUtc - DateTimeOffset.UtcNow;
            if (remaining <= TimeSpan.Zero) throw new InvalidOperationException("LEASE_EXPIRED");
            if (remaining > Lease) remaining = Lease;
            _lease = new CancellationTokenSource(remaining);
            _lease.Token.Register(DisposePipe);
            LeaseDeadlineUtc = DateTimeOffset.UtcNow.Add(remaining);
        }

        internal DateTimeOffset LeaseDeadlineUtc { get; }

        internal void StartWorker()
        {
            _ = Task.Run(RunAsync);
        }

        private async Task RunAsync()
        {
            var token = _lease.Token;
            try
            {
                for (int clients = 0; clients < 32 && !token.IsCancellationRequested; clients++)
                {
                    BridgeLog.Write("listener waiting for connection");
                    await _pipe.WaitForConnectionAsync(token).ConfigureAwait(false);
                    await ServeAsync(token).ConfigureAwait(false);
                    // A client can close before IsConnected is queried. The server still
                    // needs Disconnect to reset the native pipe before the next accept.
                    if (!token.IsCancellationRequested) _pipe.Disconnect();
                }
            }
            catch (OperationCanceledException)
            {
                BridgeLog.Write("listener cancelled (lease expiry or stop)");
            }
            catch (ObjectDisposedException)
            {
                BridgeLog.Write("listener pipe disposed");
            }
            catch (IOException ex)
            {
                BridgeLog.Write("listener io error: " + ex.GetType().Name);
            }
            catch (Exception ex)
            {
                BridgeLog.Write("listener unhandled: " + ex.GetType().Name + ": " + ex.Message);
            }
            finally
            {
                DisposePipe();
                bool cleaned=false;
                string? cleanupError=null;
                object? cleanupEvidence=null;
                try
                {
                    var dispatcher=System.Windows.Application.Current?.Dispatcher
                        ?? throw new InvalidOperationException("NO_CLEANUP_DISPATCHER");
                    cleanupEvidence=await dispatcher.InvokeAsync(()=>_adapter.CleanupForLease()).Task.ConfigureAwait(false);
                    // Removing our callback does not cancel the game's export.
                    // Preserve its bounded observation window across leases.
                    var quietDelay=_adapter.ExportQuiescenceUtc-DateTime.UtcNow;
                    if(quietDelay>TimeSpan.Zero)await Task.Delay(quietDelay).ConfigureAwait(false);
                    cleaned=true;
                }
                catch(Exception ex){cleanupError=ex.GetType().Name;BridgeLog.Write("lease cleanup failed: "+cleanupError);}
                BridgeLog.Write("listener closed; cleanup="+cleaned);
                try {File.WriteAllText(Path.Combine(_directory,"lease-closed.json"),JsonSerializer.Serialize(new {
                    pid=_facts.Pid,closedUtc=DateTime.UtcNow,cleanupSucceeded=cleaned,cleanupError,cleanupEvidence,hostProcessTerminated=false}));}
                catch(Exception ex){BridgeLog.Write("lease closure evidence failed: "+ex.GetType().Name);}
                if(cleaned)Volatile.Write(ref _completed,1);
                try
                {
                    _lease.Dispose();
                }
                catch (Exception)
                {
                    // Nothing useful to do; the lease only guards the listener.
                }
            }
        }

        private async Task ServeAsync(CancellationToken token)
        {
            var readBuffer = new byte[4096];
            var lineBuffer = new ArrayBufferWriter<byte>(1024);

            while (!token.IsCancellationRequested)
            {
                int read;
                try
                {
                    read = await _pipe.ReadAsync(readBuffer.AsMemory(), token).ConfigureAwait(false);
                }
                catch (OperationCanceledException)
                {
                    return;
                }
                catch (ObjectDisposedException)
                {
                    return;
                }
                catch (IOException)
                {
                    return;
                }

                if (read <= 0)
                {
                    BridgeLog.Write("client closed the connection");
                    return;
                }

                for (var i = 0; i < read; i++)
                {
                    var b = readBuffer[i];
                    if (b == (byte)'\n')
                    {
                        var line = lineBuffer.WrittenSpan;
                        if (line.Length > 0 && line[line.Length - 1] == (byte)'\r')
                        {
                            line = line.Slice(0, line.Length - 1);
                        }
                        var text = Encoding.UTF8.GetString(line);
                        lineBuffer.Clear();
                        if (text.Trim().Length == 0)
                        {
                            continue;
                        }
                        if (!await HandleLineAsync(text, token).ConfigureAwait(false))
                        {
                            return;
                        }
                        continue;
                    }

                    if (lineBuffer.WrittenCount >= MaxLineBytes)
                    {
                        BridgeLog.Write("request line exceeded the 16 KiB cap; failing closed");
                        await TryWriteAsync(new Dictionary<string, object?>
                        {
                            ["id"] = null,
                            ["ok"] = false,
                            ["error"] = "line_too_long",
                            ["limitBytes"] = MaxLineBytes,
                        }).ConfigureAwait(false);
                        return;
                    }

                    lineBuffer.GetSpan(1)[0] = b;
                    lineBuffer.Advance(1);
                }
            }
        }

        /// <summary>Returns false when the current client must disconnect.</summary>
        private async Task<bool> HandleLineAsync(string text, CancellationToken token)
        {
            JsonElement root;
            try
            {
                using var document = JsonDocument.Parse(text);
                root = document.RootElement.Clone();
            }
            catch (JsonException)
            {
                await TryWriteAsync(Error(null, "bad_json")).ConfigureAwait(false);
                return false;
            }

            if (root.ValueKind != JsonValueKind.Object)
            {
                await TryWriteAsync(Error(null, "bad_json_object")).ConfigureAwait(false);
                return false;
            }

            JsonElement? id = root.TryGetProperty("id", out var idElement) ? idElement.Clone() : null;

            if (!NonceMatches(ReadString(root, "nonce")))
            {
                BridgeLog.Write("nonce mismatch; failing closed");
                await TryWriteAsync(Error(id, "nonce_mismatch")).ConfigureAwait(false);
                return false;
            }

            var op = ReadString(root, "op");
            switch (op)
            {
                case "ping":
                    await TryWriteAsync(BuildPing(id)).ConfigureAwait(false);
                    return true;

                case "describe":
                    await TryWriteAsync(BuildDescribe(id, root)).ConfigureAwait(false);
                    return true;

                case "audio-runtime-node-catalog":
                    // Fixed no-parameter read over the real graph registry.
                    try
                    {
                        foreach (var audioProperty in root.EnumerateObject())
                            if (audioProperty.Name != "id" && audioProperty.Name != "op" && audioProperty.Name != "nonce")
                                throw new InvalidOperationException("AUDIO_NODE_CATALOG_FIELDS");
                        var audioDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var audioWork = audioDispatcher.InvokeAsync(() => _adapter.AudioRuntimeNodeCatalog(),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await audioWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "inspect-entity-faction-probe":
                case "set-entity-faction-probe":
                case "restore-entity-faction-probe":
                    try
                    {
                        var factionFields = new HashSet<string>();
                        foreach (var property in root.EnumerateObject())
                            if (!factionFields.Add(property.Name) || (property.Name != "id" && property.Name != "op" && property.Name != "nonce"))
                                throw new InvalidOperationException("FACTION_PROBE_FIELDS");
                        var factionDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var factionAction = op == "inspect-entity-faction-probe" ? "inspect" : op == "set-entity-faction-probe" ? "set" : "restore";
                        var factionWork = factionDispatcher.InvokeAsync(() => _adapter.EntityFactionProbe(factionAction),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await factionWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "inspect-entity-components":
                    // Read-only: one entity by registry id -> its component rows. Field
                    // validation runs (and can refuse) before any editor reflection.
                    try
                    {
                        EditorAdapter.ValidateEntityComponentProbe(root);
                        var componentDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var componentWork = componentDispatcher.InvokeAsync(() => _adapter.EntityComponentProbe(root),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await componentWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "delete-entity-component":
                    // MUTATION (bounded): one component off ONE self-owned CRUD-probe entity,
                    // over the front-end command DeleteComponentForEditObj. The adapter's own
                    // owned-target gate refuses any entity this run did not create; while the
                    // component reader is unbound it fails closed before any dispatch. Field
                    // validation runs (and can refuse) before any editor reflection.
                    try
                    {
                        EditorAdapter.ValidateEntityComponentDelete(root);
                        var delDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var delWork = delDispatcher.InvokeAsync(() => _adapter.EntityComponentDelete(root),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await delWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "add-entity-component":
                    // LOCAL-MODEL WRITE (bounded): one component onto ONE self-owned CRUD-probe
                    // entity, over the editor's own entity-model loader path. No native command
                    // is dispatched (nativeMutationInvoked=false): the add lands on the entity's
                    // DERIVED component mirror, which is rebuilt from the data side on the next
                    // load, so it neither survives a reload nor reaches the game/save. The
                    // adapter's own owned-target gate refuses any entity this run did not create;
                    // while the component reader is unbound it fails closed before any write.
                    // Field validation runs (and can refuse) before any editor reflection.
                    try
                    {
                        EditorAdapter.ValidateEntityComponentAdd(root);
                        var addDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var addWork = addDispatcher.InvokeAsync(() => _adapter.EntityComponentAdd(root),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await addWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "reflection-probe":
                    // Read-only: names of the types/methods the LIVE assembly actually has.
                    // This is the one op that does NOT resolve a statically-harvested symbol,
                    // so it is immune to a gap in the decompiled corpus. Field validation runs
                    // (and can refuse a short/oversize needle) before any reflection.
                    try
                    {
                        EditorAdapter.ValidateReflectionProbe(root);
                        var reflectionDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var reflectionWork = reflectionDispatcher.InvokeAsync(() => _adapter.ReflectionProbe(root),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await reflectionWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "reflection-probe-component":
                case "reflection-probe-template":
                case "reflection-probe-service":
                    // Fixed-needle siblings of reflection-probe. The needle is a COMPILE-TIME
                    // constant and the wire request carries NO field, so the request passes a
                    // resident helper whose in-memory field allowlist predates these ops (its
                    // op whitelist is re-read from call-bridge.ps1 per request; its field list
                    // is not). Same read-only reflection as reflection-probe, sharing its core.
                    // The member filter: "Add" for the component hunt -- the decisive verb there
                    // IS "add". Left unset for the template hunt, where the decisive verb is
                    // "create"; an "Add" filter there would not be free, it would hide
                    // Create*/New*/Insert* from the very reply meant to disprove them.
                    try
                    {
                        var fixedNeedle = op switch
                        {
                            "reflection-probe-component" => "Component",
                            "reflection-probe-template" => "Template",
                            _ => "Service",
                        };
                        string? fixedMember = op == "reflection-probe-component" ? "Add" : null;
                        var fixedDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var fixedWork = fixedDispatcher.InvokeAsync(
                            () => _adapter.ReflectionProbeFixed(root, fixedNeedle, fixedMember),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await fixedWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "reflection-editor-add":
                case "reflection-editor-create":
                case "reflection-editor-services":
                case "reflection-editor-types":
                    // The ASSEMBLY-SCOPED, MEMBER-NAME-FILTERED siblings of the probes above.
                    // The needle that matters for the editor assembly is a MEMBER name, not a
                    // type name: the editor's TYPE names are obfuscated (LhusWLXd5NUZ7IineV1x),
                    // so a type-name filter like "Component" can never match one, while its
                    // METHOD names are plain text (AddInstructionGraphForEditObj) and its
                    // service names are plain too. Each op scopes to the ONE assembly whose
                    // simple name is "BeyondEditor" and filters by a COMPILE-TIME member needle,
                    // carrying NO request field, so the resident helper's stale in-memory field
                    // allowlist still admits them -- exactly like the trio above. Same read-only
                    // reflection (GetTypes + GetMethods only; nothing invoked).
                    //   add      -> types with a method whose name contains "Add"
                    //   create   -> types with a method whose name contains "Create" or "New"
                    //   services -> types whose name contains "Service", ALL method names
                    //   types    -> the COUNT of types in the assembly
                    try
                    {
                        var editorDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var editorWork = editorDispatcher.InvokeAsync(() => op switch
                        {
                            "reflection-editor-add"      => _adapter.ReflectionEditorAdd(root),
                            "reflection-editor-create"   => _adapter.ReflectionEditorCreate(root),
                            "reflection-editor-services" => _adapter.ReflectionEditorServices(root),
                            _                            => _adapter.ReflectionEditorTypes(root),
                        }, System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await editorWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "mine-process-strings":
                    // Read-only self-scan of the editor's OWN address space for decrypted
                    // command strings. The editor binary is ConfuserEx-protected (every
                    // string literal is stripped from the metadata #US heap), so the
                    // plaintext exists only at runtime and can only be read from the live
                    // process. No WPF dispatcher hop is needed: raw page reads are
                    // thread-agnostic and touch no WPF object.
                    try
                    {
                        await TryWriteAsync(_adapter.MineProcessStrings()).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "node-definitions":
                case "node-definition-variants":
                    // Bounded read-only definition query. The id list is validated here so a
                    // malformed request never reaches the adapter.
                    try
                    {
                        var ids = ReadUintArray(root, "ids");
                        var dispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var work = dispatcher.InvokeAsync(() => op == "node-definition-variants"
                            ? _adapter.NodeDefinitionVariants(ids) : _adapter.NodeDefinitions(ids),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await work.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "delete-owned-entity-ids-dry-run":
                case "delete-owned-entity-ids":
                    // Bounded delete of EXPLICIT ids only. The list is validated here; the
                    // adapter refuses the WHOLE list if any id does not resolve to exactly one
                    // resource node, so an ambiguous list deletes nothing. The -dry-run form
                    // maps ids to frontend paths and invokes no delete at all.
                    try
                    {
                        var deleteIds = ReadUintArray(root, "ids");
                        bool deleteDryRun = op == "delete-owned-entity-ids-dry-run";
                        var deleteDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var deleteWork = deleteDispatcher.InvokeAsync(
                            () => _adapter.DeleteOwnedEntityIds(deleteIds, deleteDryRun),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await deleteWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "delete-owned-graph-ids-dry-run":
                case "delete-owned-graph-ids":
                    // Bounded delete of GRAPH resources named by explicit id. Kind must be 9
                    // AND the stored name must start with "MW_", so the operation cannot reach
                    // a built-in node definition or a graph this project did not create, even
                    // if such an id is supplied. An unresolved id refuses the whole list.
                    try
                    {
                        var graphIds = ReadUintArray(root, "ids");
                        bool graphDryRun = op == "delete-owned-graph-ids-dry-run";
                        var graphDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var graphWork = graphDispatcher.InvokeAsync(
                            () => _adapter.DeleteOwnedGraphIds(graphIds, graphDryRun),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await graphWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "delete-instruction-graph":
                case "delete-instruction-graph-force":
                case "delete-instruction-graph-dry-run":
                    // MUTATION (bounded): ONE instruction graph, over the native command
                    // DeleteInstructionGraphForEditObj -- the symmetric sibling of the
                    // AddInstructionGraphForEditObj the bridge already fires to BIND a graph.
                    // The command NAME is a tier-2 (FNV preimage) fact and its PAYLOAD SHAPE is
                    // tier-3 (unrecovered), so the adapter fails closed at
                    // INSTRUCTION_GRAPH_EDIT_OBJ_REQUIRED rather than inventing an argument.
                    // The ownership gate is the SAME Resources() Kind-9 identity the rest of the
                    // bridge uses, plus the MW_ name prefix, plus empty+unbound; a graph this
                    // project did not create is refused by name and never dispatched.
                    // Field validation runs (and can refuse) before any editor reflection.
                    try
                    {
                        EditorAdapter.ValidateInstructionGraphDelete(root);
                        var igDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var igWork = igDispatcher.InvokeAsync(() => op switch
                        {
                            "delete-instruction-graph-dry-run" => _adapter.DeleteInstructionGraphDryRun(root),
                            "delete-instruction-graph-force"   => _adapter.DeleteInstructionGraph(root, true),
                            _                                  => _adapter.DeleteInstructionGraph(root, false),
                        }, System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await igWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "author-entity-tag":
                    try
                    {
                        EditorAdapter.ValidateAuthorEntityTag(root);
                        var tagDispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var tagWork = tagDispatcher.InvokeAsync(() => _adapter.AuthorEntityTag(root),
                            System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await tagWork.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "author-graph":
                case "create-calibration-graph":
                case "build-calibration-graph":
                case "export-calibration-graph":
                case "create-audit-graph":
                case "build-audit-graph":
                case "bind-audit-graph":
                case "export-audit-graph":
                case "repair-finish-booleans":
                case "create-finish-graph":
                case "build-finish-graph":
                case "export-finish-graph":
                case "bind-finish-graph":
                case "unbind-finish-graph":
                case "strip-finish-classic-node":
                case "create-gameloop-graph":
                case "build-gameloop-graph":
                case "export-gameloop-graph":
                case "bind-gameloop-graph":
                case "repair-gameloop-score-order":
                case "repair-gameloop-settlement-status":
                case "repair-gameloop-classic-teleport":
                case "begin-finish-minimal-diagnostic":
                case "restore-finish-minimal-diagnostic":
                case "begin-finish-settlement-diagnostic":
                case "restore-finish-settlement-diagnostic":
                case "unbind-gameloop-graph":
                case "unbind-all-gameloop-graphs":
                case "create-gameloop-variant-no-scoreboard":
                case "create-gameloop-variant-core":
                case "build-gameloop-variant-no-scoreboard":
                case "build-gameloop-variant-core":
                case "bind-gameloop-variant-no-scoreboard":
                case "bind-gameloop-variant-core":
                case "create-mvp-course-graph":
                case "build-mvp-course-graph":
                case "bind-mvp-course-graph":
                case "export-mvp-course-graph":
                case "create-position-graph":
                case "build-position-graph":
                case "export-position-graph":
                case "bind-position-graph":
                case "runtime-evidence":
                case "inspect-reopen-content":
                case "profile-reopen-content-sample":
                case "inspect-sync-graphs":
                case "request-debug-logs":
                case "enable-debug-logging":
                case "enable-own-graph-logging":
                case "set-calibration-origin":
                case "rename-realtime-lab-tree":
                case "restore-realtime-lab-tree-name":
                case "begin-entity-crud-probe":
                case "inspect-entity-crud-probe":
                case "rename-entity-crud-probe":
                case "restore-entity-crud-probe-name":
                case "delete-entity-crud-probe":
                case "request-realtime-tree-prefab":
                case "request-realtime-lab-prefab":
                case "request-calibration-prefab":
                case "recover-client-script-probe":
                case "inspect-client-script-file-probe":
                case "create-client-script-file-probe":
                case "set-client-script-file-probe-path":
                case "begin-client-script-batch-probe":
                case "create-client-script-batch-probe":
                case "inspect-client-script-batch-probe":
                case "delete-client-script-batch-probe":
                case "export-client-script-probe":
                case "inspect-client-script-variables-probe":
                case "add-client-script-variable-probe":
                case "delete-client-script-variable-probe":
                case "add-client-script-int-variable-probe":
                case "reset-client-script-variable-type-probe":
                case "begin-client-script-probe":
                case "create-client-script-probe":
                case "inspect-client-script-probe":
                case "rename-client-script-probe":
                case "delete-client-script-probe":
                case "client-script-root":
                case "client-script-catalog":
                case "prefab-fields-page":
                case "prefab-fields":
                case "prefab-catalog":
                case "inspect-self-connection-repair":
                case "repair-self-connection":
                case "begin-owned-entity-cleanup":
                case "inspect-owned-entity-cleanup":
                case "delete-owned-entity-cleanup":
                case "catalog":
                case "verify-interfaces":
                case "verify-channels":
                case "create-test-graph":
                case "add-test-print":
                case "wire-test-event":
                case "bind-calibration-graph":
                case "bind-test-graph":
                case "export-first":
                case "start-external-asset-observer":
                case "retire-runtime-spawns":
                case "external-asset-evidence":
                case "start-log-observer":
                case "log-observer-evidence":
                case "stop-log-observer":
                case "import-tiled-route":
                case "export-tiled-route":
                case "bind-tiled-route":
                case "import-route-placement":
                case "export-route-placement":
                case "sync-editor-changes":
                case "import-calibration-graph":
                case "import-verified-graph":
                case "export-imported-graph":
                case "command-probe":
                case "probe-archive-model":
                case "open-editor-panel":
                case "focus-lab-cube-from-frontend":
                case "load-lab-cube-resource-model":
                case "load-scene-resource-model":
                case "open-resource-manager":
                case "open-scene-resource-folder":
                case "inspect-frontend-commands":
                    try
                    {
                        // enable-own-graph-logging names the graph(s) to log in the request
                        // (ids and/or graphName). Validate the closed field schema here so a
                        // malformed request is refused by name before anything is dispatched.
                        if (op == "enable-own-graph-logging") EditorAdapter.ValidateOwnGraphLogging(root);
                        var dispatcher = System.Windows.Application.Current?.Dispatcher
                            ?? throw new InvalidOperationException("NO_WPF_DISPATCHER");
                        var work = dispatcher.InvokeAsync(() => op == "inspect-client-script-file-probe" ? _adapter.InspectClientScriptFileProbe() : op == "recover-client-script-probe" ? _adapter.RecoverClientScriptProbe() : op == "create-client-script-file-probe" ? _adapter.CreateClientScriptFileProbe(EditorAdapter.ReadClientScriptRelativePath(root)) : op == "set-client-script-file-probe-path" ? _adapter.SetClientScriptFileProbePath(EditorAdapter.ReadClientScriptRelativePath(root)) : op == "begin-client-script-batch-probe" ? _adapter.BeginClientScriptBatchProbe() : op == "create-client-script-batch-probe" ? _adapter.CreateClientScriptBatchProbe() : op == "inspect-client-script-batch-probe" ? _adapter.InspectClientScriptBatchProbe() : op == "delete-client-script-batch-probe" ? _adapter.DeleteClientScriptBatchProbe() : op == "export-client-script-probe" ? _adapter.ExportClientScriptProbe(Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName)) : op == "inspect-client-script-variables-probe" ? _adapter.InspectClientScriptVariablesProbe() : op == "add-client-script-variable-probe" ? _adapter.AddClientScriptVariableProbe() : op == "delete-client-script-variable-probe" ? _adapter.DeleteClientScriptVariableProbe() : op == "add-client-script-int-variable-probe" ? _adapter.AddClientScriptIntVariableProbe() : op == "reset-client-script-variable-type-probe" ? _adapter.ResetClientScriptVariableTypeProbe() : op == "begin-client-script-probe" ? _adapter.BeginClientScriptProbe() : op == "create-client-script-probe" ? _adapter.CreateClientScriptProbe() : op == "inspect-client-script-probe" ? _adapter.InspectClientScriptProbe() : op == "rename-client-script-probe" ? _adapter.RenameClientScriptProbe() : op == "delete-client-script-probe" ? _adapter.DeleteClientScriptProbe() : op == "client-script-root"
                            ? _adapter.ClientScriptRootReadOnly()
                            : op == "client-script-catalog"
                            ? _adapter.ClientScriptsReadOnly()
                            : op == "prefab-fields-page"
                            ? _adapter.PrefabFieldsNext(Path.Combine(_directory, "prefab-resume.json"))
                            : op == "prefab-fields"
                            ? _adapter.PrefabFields()
                            : op == "prefab-catalog"
                            ? _adapter.PrefabCatalog()
                            : op == "inspect-self-connection-repair" ? _adapter.RepairAuthorizedSelfConnection(false)
                            : op == "repair-self-connection" ? _adapter.RepairAuthorizedSelfConnection(true)
                            : op == "begin-owned-entity-cleanup" ? _adapter.BeginOwnedEntityCleanup()
                            : op == "inspect-owned-entity-cleanup" ? _adapter.InspectOwnedEntityCleanup()
                            : op == "delete-owned-entity-cleanup" ? _adapter.DeleteOwnedEntityCleanup()
                            : op == "catalog"
                            ? _adapter.Catalog()
                            : op == "author-graph" ? _adapter.AuthorGraph(root, Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports", _settings.PipeName))
                            : op == "verify-interfaces" ? _adapter.VerifyInterfaces()
                            : op == "verify-channels" ? _adapter.VerifyChannels()
                            : op == "create-calibration-graph" ? _adapter.CreateCalibrationGraph()
                            : op == "build-calibration-graph" ? _adapter.BuildCalibrationGraph()
                            : op == "export-calibration-graph" ? _adapter.ExportCalibrationGraph(Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "create-audit-graph" ? _adapter.CreateAuditGraph()
                            : op == "build-audit-graph" ? _adapter.BuildAuditGraph()
                            : op == "bind-audit-graph" ? _adapter.BindAuditGraph()
                            : op == "export-audit-graph" ? _adapter.ExportAuditGraph(Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "repair-finish-booleans" ? _adapter.RepairFinishBooleans()
                            : op == "create-finish-graph" ? _adapter.CreateFinishGraph()
                            : op == "build-finish-graph" ? _adapter.BuildFinishGraph()
                            : op == "bind-finish-graph" ? _adapter.BindFinishGraph()
                            : op == "unbind-finish-graph" ? _adapter.UnbindFinishGraph()
                            : op == "strip-finish-classic-node" ? _adapter.StripFinishClassicNode()
                            : op == "export-finish-graph" ? _adapter.ExportFinishGraph(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "unbind-gameloop-graph" ? _adapter.UnbindGameLoopGraph()
                            : op == "unbind-all-gameloop-graphs" ? _adapter.UnbindAllGameLoopGraphs()
                            : op == "create-gameloop-variant-no-scoreboard" ? _adapter.CreateGameLoopVariantNoScoreboard()
                            : op == "create-gameloop-variant-core" ? _adapter.CreateGameLoopVariantCore()
                            : op == "build-gameloop-variant-no-scoreboard" ? _adapter.BuildGameLoopVariantNoScoreboard()
                            : op == "build-gameloop-variant-core" ? _adapter.BuildGameLoopVariantCore()
                            : op == "bind-gameloop-variant-no-scoreboard" ? _adapter.BindGameLoopVariantNoScoreboard()
                            : op == "bind-gameloop-variant-core" ? _adapter.BindGameLoopVariantCore()
                            : op == "create-mvp-course-graph" ? _adapter.CreateMvpCourseGraph()
                            : op == "build-mvp-course-graph" ? _adapter.BuildMvpCourseGraph()
                            : op == "bind-mvp-course-graph" ? _adapter.BindMvpCourseGraph()
                            : op == "export-mvp-course-graph" ? _adapter.ExportMvpCourseGraph(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "repair-gameloop-score-order" ? _adapter.RepairGameLoopScoreOrder()
                            : op == "repair-gameloop-settlement-status" ? _adapter.RepairGameLoopSettlementStatus()
                            : op == "repair-gameloop-classic-teleport" ? _adapter.RepairGameLoopClassicTeleport()
                            : op == "begin-finish-minimal-diagnostic" ? _adapter.BeginFinishMinimalDiagnostic()
                            : op == "restore-finish-minimal-diagnostic" ? _adapter.RestoreFinishMinimalDiagnostic()
                            : op == "begin-finish-settlement-diagnostic" ? _adapter.BeginFinishSettlementDiagnostic()
                            : op == "restore-finish-settlement-diagnostic" ? _adapter.RestoreFinishSettlementDiagnostic()
                            : op == "create-gameloop-graph" ? _adapter.CreateGameLoopGraph()
                            : op == "build-gameloop-graph" ? _adapter.BuildGameLoopGraph()
                            : op == "bind-gameloop-graph" ? _adapter.BindGameLoopGraph()
                            : op == "export-gameloop-graph" ? _adapter.ExportGameLoopGraph(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "create-position-graph" ? _adapter.CreatePositionGraph()
                            : op == "build-position-graph" ? _adapter.BuildPositionGraph()
                            : op == "bind-position-graph" ? _adapter.BindPositionGraph()
                            : op == "export-position-graph" ? _adapter.ExportPositionGraph(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "command-probe" ? _adapter.CommandProbe()
                            : op == "probe-archive-model" ? _adapter.ProbeArchiveModel()
                            : op == "open-editor-panel" ? _adapter.OpenEditorPanel()
                            : op == "focus-lab-cube-from-frontend" ? _adapter.FocusLabCubeFromFrontend()
                            : op == "load-lab-cube-resource-model" ? _adapter.LoadSceneResourceModel(labCube: true)
                            : op == "load-scene-resource-model" ? _adapter.LoadSceneResourceModel()
                            : op == "open-resource-manager" ? _adapter.OpenEditorPanel(resourceManager: true)
                            : op == "open-scene-resource-folder" ? _adapter.OpenSceneResourceFolder()
                            : op == "inspect-frontend-commands" ? _adapter.InspectFrontendCommands()
                            : op == "runtime-evidence" ? _adapter.RuntimeEvidence()
                            : op == "inspect-reopen-content" ? _adapter.InspectReopenContent()
                            : op == "profile-reopen-content-sample" ? _adapter.ProfileReopenContentSingleCapture()
                            : op == "inspect-sync-graphs" ? _adapter.InspectSyncGraphs()
                            : op == "request-debug-logs" ? _adapter.RequestDebugLogs()
                            : op == "enable-debug-logging" ? _adapter.EnableDebugLogging()
                            : op == "enable-own-graph-logging" ? _adapter.EnableOwnGraphLogging(root)
                            : op == "set-calibration-origin" ? _adapter.SetCalibrationOrigin()
                            : op == "rename-realtime-lab-tree" ? _adapter.RenameRealtimeLabTree(false)
                            : op == "restore-realtime-lab-tree-name" ? _adapter.RenameRealtimeLabTree(true)
                            : op == "begin-entity-crud-probe" ? _adapter.BeginEntityCrudProbe()
                            : op == "inspect-entity-crud-probe" ? _adapter.InspectEntityCrudProbe()
                            : op == "rename-entity-crud-probe" ? _adapter.RenameEntityCrudProbe(false)
                            : op == "restore-entity-crud-probe-name" ? _adapter.RenameEntityCrudProbe(true)
                            : op == "delete-entity-crud-probe" ? _adapter.DeleteEntityCrudProbe()
                            : op == "request-realtime-tree-prefab" ? _adapter.RequestRealtimeTreePrefab()
                            : op == "request-realtime-lab-prefab" ? _adapter.RequestRealtimeLabPrefab()
                            : op == "request-calibration-prefab" ? _adapter.RequestCalibrationPrefab()
                            : op == "create-test-graph" ? _adapter.CreateTestGraph()
                            : op == "add-test-print" ? _adapter.AddTestPrint()
                            : op == "wire-test-event" ? _adapter.WireTestEvent()
                            : op == "bind-calibration-graph" ? _adapter.BindCalibrationGraph()
                            : op == "bind-test-graph" ? _adapter.BindTestGraph()
                            : op == "start-external-asset-observer" ? _adapter.StartExternalAssetObserver()
                            : op == "retire-runtime-spawns" ? _adapter.RetireRuntimeSpawns()
                            : op == "external-asset-evidence" ? _adapter.ExternalAssetEvidence()
                            : op == "start-log-observer" ? _adapter.StartLogObserver()
                            : op == "log-observer-evidence" ? _adapter.LogObserverEvidence()
                            : op == "stop-log-observer" ? _adapter.StopLogObserver()
                            : op == "import-tiled-route" ? _adapter.ImportTiledRoute()
                            : op == "bind-tiled-route" ? _adapter.BindTiledRoute()
                            : op == "export-tiled-route" ? _adapter.ExportTiledRoute(Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "import-route-placement" ? _adapter.ImportRoutePlacement()
                            : op == "export-route-placement" ? _adapter.ExportRoutePlacement(Path.Combine(@"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : op == "sync-editor-changes" ? _adapter.SyncEditorChanges()
                            : op == "import-calibration-graph" ? _adapter.ImportCalibrationGraph()
                            : op == "import-verified-graph" ? _adapter.ImportVerifiedGraph()
                            : op == "export-imported-graph" ? _adapter.ExportImportedGraph(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",_settings.PipeName))
                            : _adapter.ExportFirst(Path.Combine(
                                @"<SOURCE_ROOT>\.runtime\editor-bridge\exports",
                                _settings.PipeName)), System.Windows.Threading.DispatcherPriority.Background, token);
                        await TryWriteAsync(await work.Task.ConfigureAwait(false)).ConfigureAwait(false);
                    }
                    catch (Exception ex)
                    {
                        await TryWriteAsync(Error(id, "adapter:" + ex.GetType().Name + ":" + ex.Message)).ConfigureAwait(false);
                    }
                    return true;

                case "stop":
                    BridgeLog.Write("stop requested; closing listener only");
                    await TryWriteAsync(new Dictionary<string, object?>
                    {
                        ["id"] = id,
                        ["ok"] = true,
                        ["op"] = "stop",
                        ["stopped"] = true,
                        ["cleanupComplete"] = false,
                        ["status"] = "listener-stop-requested",
                        ["hostProcessTerminated"] = false,
                    }).ConfigureAwait(false);
                    _lease.Cancel();
                    return false;

                default:
                    await TryWriteAsync(Error(id, "unknown_op")).ConfigureAwait(false);
                    return true;
            }
        }

        private object BuildPing(JsonElement? id)
        {
            var wpf = ProbeWpf();
            var beyond = ProbeBeyondEditorAssemblies();

            return new Dictionary<string, object?>
            {
                ["id"] = id,
                ["ok"] = true,
                ["op"] = "ping",
                ["pid"] = _facts.Pid,
                // Emitted as a string: it exceeds 2^53 and a JSON number would round-trip lossily.
                ["startUtcTicks"] = _facts.StartUtcTicks.ToString(CultureInfo.InvariantCulture),
                ["framework"] = RuntimeInformation.FrameworkDescription,
                ["processArchitecture"] = RuntimeInformation.ProcessArchitecture.ToString(),
                ["bridgeVersion"] = typeof(BridgeServer).Assembly.GetName().Version?.ToString() ?? "unknown",
                ["bridgeAssembly"] = BuildIdentity.Snapshot(),
                ["isWpfDispatcher"] = wpf.Available,
                ["wpf"] = new Dictionary<string, object?>
                {
                    ["applicationCurrent"] = wpf.ApplicationCurrent,
                    ["dispatcherAvailable"] = wpf.Available,
                    ["dispatcherThreadId"] = wpf.DispatcherThreadId,
                    ["dispatcherShutdownStarted"] = wpf.ShutdownStarted,
                    ["bridgeThreadIsDispatcherThread"] = wpf.CurrentThreadIsDispatcherThread,
                },
                ["beyondEditorAssemblyLoaded"] = beyond.Names.Count > 0,
                ["beyondEditorAssemblyNames"] = beyond.Names,
                ["loadedAssemblyCount"] = beyond.LoadedCount,
                ["leaseDeadlineUtc"] = LeaseDeadlineUtc.ToString("O", CultureInfo.InvariantCulture),
            };
        }

        private object BuildDescribe(JsonElement? id, JsonElement root)
        {
            List<string> names;
            if (root.TryGetProperty("types", out var typesElement) && typesElement.ValueKind == JsonValueKind.Array)
            {
                if (typesElement.GetArrayLength() > MaxDescribeTypes)
                {
                    return Error(id, "too_many_types");
                }
                names = new List<string>();
                foreach (var element in typesElement.EnumerateArray())
                {
                    if (element.ValueKind != JsonValueKind.String)
                    {
                        return Error(id, "bad_type_name");
                    }
                    var name = element.GetString() ?? string.Empty;
                    if (name.Length == 0 || name.Length > MaxTypeNameLength || !TypeNamePattern.IsMatch(name))
                    {
                        return Error(id, "bad_type_name");
                    }
                    names.Add(name);
                }
            }
            else
            {
                names = new List<string>(DefaultDescribeTypes);
            }

            var results = new List<object?>(names.Count);
            foreach (var name in names)
            {
                results.Add(LookupType(name));
            }

            return new Dictionary<string, object?>
            {
                ["id"] = id,
                ["ok"] = true,
                ["op"] = "describe",
                ["count"] = results.Count,
                ["types"] = results,
                ["note"] = "type identity and metadata only; no members, instances or property values are read",
            };
        }

        /// <summary>Existence and static metadata only. Never enumerates members or reads values.</summary>
        private static Dictionary<string, object?> LookupType(string name)
        {
            Type? found = null;
            string? assemblyName = null;

            foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                try
                {
                    var candidate = assembly.GetType(name, throwOnError: false, ignoreCase: false);
                    if (candidate != null)
                    {
                        found = candidate;
                        assemblyName = assembly.GetName().Name;
                        break;
                    }
                }
                catch (Exception)
                {
                    // A dynamic or partially loaded assembly can throw here; skip it.
                }
            }

            if (found == null)
            {
                try
                {
                    found = Type.GetType(name, throwOnError: false, ignoreCase: false);
                }
                catch (Exception)
                {
                    found = null;
                }
            }

            if (found == null)
            {
                return new Dictionary<string, object?>
                {
                    ["name"] = name,
                    ["found"] = false,
                    ["assembly"] = null,
                };
            }

            return new Dictionary<string, object?>
            {
                ["name"] = name,
                ["found"] = true,
                ["assembly"] = assemblyName ?? found.Assembly.GetName().Name,
                ["namespace"] = found.Namespace,
                ["isPublic"] = found.IsPublic,
                ["isClass"] = found.IsClass,
                ["isEnum"] = found.IsEnum,
                ["isValueType"] = found.IsValueType,
                ["isInterface"] = found.IsInterface,
                ["isAbstract"] = found.IsAbstract,
                ["isGenericType"] = found.IsGenericType,
            };
        }

        private (bool ApplicationCurrent, bool Available, int? DispatcherThreadId, bool ShutdownStarted, bool CurrentThreadIsDispatcherThread) ProbeWpf()
        {
            try
            {
                var currentThreadIsDispatcher =
                    System.Windows.Threading.Dispatcher.FromThread(Thread.CurrentThread) != null;

                var application = System.Windows.Application.Current;
                if (application == null)
                {
                    return (false, false, null, false, currentThreadIsDispatcher);
                }

                var dispatcher = application.Dispatcher;
                if (dispatcher == null)
                {
                    return (true, false, null, false, currentThreadIsDispatcher);
                }

                return (true, true, dispatcher.Thread?.ManagedThreadId, dispatcher.HasShutdownStarted, currentThreadIsDispatcher);
            }
            catch (Exception ex)
            {
                BridgeLog.Write("wpf probe unavailable: " + ex.GetType().Name);
                return (false, false, null, false, false);
            }
        }

        private static (List<string> Names, int LoadedCount) ProbeBeyondEditorAssemblies()
        {
            var names = new List<string>();
            var count = 0;
            try
            {
                foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies())
                {
                    count++;
                    string? simpleName;
                    try
                    {
                        simpleName = assembly.GetName().Name;
                    }
                    catch (Exception)
                    {
                        continue;
                    }
                    if (simpleName == null)
                    {
                        continue;
                    }
                    if (simpleName == "BeyondEditor"
                        || simpleName.StartsWith("BeyondEditor.", StringComparison.Ordinal))
                    {
                        names.Add(simpleName);
                    }
                }
            }
            catch (Exception)
            {
                // Assembly enumeration is best effort; report what we have.
            }
            return (names, count);
        }

        private bool NonceMatches(string? candidate)
        {
            if (candidate == null || candidate.Length != BridgeSettings.NonceHexLength)
            {
                // Keep the comparison constant-time even for malformed input.
                CryptographicOperations.FixedTimeEquals(_zeroNonce, _nonceBytes);
                return false;
            }

            var decoded = new byte[BridgeSettings.NonceBytes];
            for (var i = 0; i < decoded.Length; i++)
            {
                var high = BridgeSettings.HexValue(candidate[i * 2]);
                var low = BridgeSettings.HexValue(candidate[(i * 2) + 1]);
                if (high < 0 || low < 0)
                {
                    CryptographicOperations.FixedTimeEquals(_zeroNonce, _nonceBytes);
                    return false;
                }
                decoded[i] = (byte)((high << 4) | low);
            }

            return CryptographicOperations.FixedTimeEquals(decoded, _nonceBytes);
        }

        /// <summary>Reads an unsigned-integer array. Any malformed element yields an empty array,
        /// which the adapter rejects as NODE_QUERY_EMPTY rather than acting on partial input.</summary>
        private static uint[] ReadUintArray(JsonElement root, string propertyName)
        {
            if (!root.TryGetProperty(propertyName, out var element) || element.ValueKind != JsonValueKind.Array)
            {
                return Array.Empty<uint>();
            }
            var values = new List<uint>();
            foreach (var item in element.EnumerateArray())
            {
                if (item.ValueKind != JsonValueKind.Number || !item.TryGetUInt32(out var value))
                {
                    return Array.Empty<uint>();
                }
                values.Add(value);
            }
            return values.ToArray();
        }

        private static uint ReadUint(JsonElement root, string propertyName)
        {
            if (root.TryGetProperty(propertyName, out var element) && element.ValueKind == JsonValueKind.Number
                && element.TryGetUInt32(out var value))
            {
                return value;
            }
            throw new InvalidOperationException("MISSING_OR_INVALID:" + propertyName);
        }

        private static string? ReadString(JsonElement root, string propertyName)
        {
            if (root.TryGetProperty(propertyName, out var element) && element.ValueKind == JsonValueKind.String)
            {
                return element.GetString();
            }
            return null;
        }

        private static Dictionary<string, object?> Error(JsonElement? id, string code)
        {
            return new Dictionary<string, object?>
            {
                ["id"] = id,
                ["ok"] = false,
                ["error"] = code,
            };
        }

        private async Task TryWriteAsync(object payload)
        {
            try
            {
                await WriteAsync(payload).ConfigureAwait(false);
            }
            catch (Exception ex)
            {
                BridgeLog.Write("response write failed: " + ex.GetType().Name);
            }
        }

        private async Task WriteAsync(object payload)
        {
            var json = JsonSerializer.Serialize(payload, BridgeJson.Write);
            var bytes = Encoding.UTF8.GetBytes(json + "\n");
            await _pipe.WriteAsync(bytes.AsMemory()).ConfigureAwait(false);
            await _pipe.FlushAsync().ConfigureAwait(false);
        }

        private static byte[] DecodeHex(string hex)
        {
            var bytes = new byte[BridgeSettings.NonceBytes];
            for (var i = 0; i < bytes.Length; i++)
            {
                var high = BridgeSettings.HexValue(hex[i * 2]);
                var low = BridgeSettings.HexValue((i * 2) + 1 < hex.Length ? hex[(i * 2) + 1] : '0');
                bytes[i] = (byte)((high << 4) | low);
            }
            return bytes;
        }

        private void DisposePipe()
        {
            if (Interlocked.Exchange(ref _pipeDisposed, 1) != 0)
            {
                return;
            }
            try
            {
                _pipe.Dispose();
            }
            catch (Exception)
            {
                // Disposal is best effort; the lease already bounds the listener lifetime.
            }
        }

        public void Dispose()
        {
            DisposePipe();
            try
            {
                _lease.Cancel();
            }
            catch (Exception)
            {
                // Ignore: cancellation only shortens the listener lifetime.
            }
        }
    }
}


