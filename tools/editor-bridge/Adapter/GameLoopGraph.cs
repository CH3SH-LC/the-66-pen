using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

// Playable demo graph: "Miliastra Platform Challenge".
//
// The existing course already had three pieces: static platforms, a launch-time spawn
// graphic and a finish trigger. What it did not have was a loop a player can actually
// play: a start, a running challenge, a way to recover from falling, a scored result and
// a settlement screen. This graph adds exactly those, using only native nodes.
//
// Design constraints taken from the project's own offline contracts, not invented here:
//   * Global timers are refused. CONTRACT-V16-LOOP.md records that a global timer name
//     must already exist in the level's timer manager, which this project cannot write.
//     The ordinary timer (node 79) has no such dependency and is already proven here.
//   * The timer period is 1.0 s so that the tick event's "循环次数" output IS the elapsed
//     second count. That removes the whole multiply/convert chain and one class of
//     generic type error.
//   * "传送玩家" carries a documented internal cooldown and must not be used for
//     high-frequency movement. It is therefore used only for the occasional fall
//     recovery, never every tick per player.
//   * The scoreboard accepts at most three rows, so exactly one row is written.
//
// Same fixed native mechanics as FinishGraph.cs: one native create, one Build that
// mutates the empty unbound graph only, one export, one bind. Nothing here sends to the
// game, and nothing here is called until the caller has approved a graph build.
internal sealed partial class EditorAdapter
{
    const string GameLoopGraphName = "MW_Game_Loop_20260917";
    const string GameLoopTimerName = "MW_GL_TICK_20260917";
    const string GameLoopStartMarker = "MW_GL_STARTED_20260917";
    const string GameLoopFinishMarker = "MW_GL_FINISHED_20260917";
    const string GameLoopFallMarker = "MW_GL_FELL_20260917";
    const string GameLoopScoreName = "用时(秒)";
    // Native BeyondGlobal enum map 34: Undefined=4100, Victory=4101, Defeat=4102.
    // This is an enum identifier, NOT the second item's ordinal or a boolean.
    const uint GameLoopVictory = 4101u;
    const int GameLoopNodeTarget = 29;
    const float GameLoopTickSeconds = 1.0f;
    const float GameLoopFallBelowY = -5.0f;
    const float GameLoopRespawnX = 0f, GameLoopRespawnY = 1.5f, GameLoopRespawnZ = 0f;

    // Course geometry is a property of the level, not of the loop. Two courses exist:
    // the 20260917 course, whose numbers were inlined here until now, and the MVP course
    // placed by tools/game-executor/plans/mw-mvp-platform.json on the lab level. Inlining
    // them meant a builder reused for a second course would silently move the finish line,
    // so both are named. The 20260917 values are unchanged -- this only gives them a name.
    const float Course17GoalX = 17f, Course17GoalY = 2.5f, Course17GoalZ = 0f;
    const float Course17MinHeight = 2.4f;
    const float Course17RespawnX = 0f, Course17RespawnY = 1.5f, Course17RespawnZ = 0f;

    // MVP course geometry.
    //
    // This is deliberately IDENTICAL to the 20260917 course, because that course is the
    // only layout on this machine with a successful playtest behind it: it is the one the
    // user confirmed ("确实能正常游玩", "现在能看见 6 个平台"), persisted as the 34 static
    // tiles in newdemo (1073741831), spanning x in [-1, 18], z in [-1, 1], with top faces
    // 0.5 / 0.9 / 1.3 / 1.7 / 2.1 / 2.5.
    //
    // An earlier MVP attempt invented its own course at z = -50 and ran x out to 43. The
    // game rejected it at playtest with "布设位置超出场景生效范围: {0,0,-50}". The lesson is
    // not just that -50 was too far: the whole design sat outside the one footprint this
    // machine has evidence the game accepts. Inventing a larger course bought nothing and
    // cost a playtest cycle, so this uses the proven footprint -- including the 2.0-unit
    // pad sizes and the 1.2-unit edge gaps that are known to be jumpable.
    const float MvpGoalX = 17f, MvpGoalY = 2.5f, MvpGoalZ = 0f;
    const float MvpMinHeight = 2.4f;
    const float MvpRespawnX = 0f, MvpRespawnY = 1.5f, MvpRespawnZ = 0f;
    const string MvpCourseGraphName = "MW_MVP_Course_20260922";
    // Scoreboard + settlement status are both present, so this is the 29-node shape.
    const int MvpCourseNodes = 29;

    bool gameLoopBuildAttempted;

    public object CreateGameLoopGraph()
    {
        // An earlier attempt may have created the graph and then failed before any node was
        // added (a pin-layout assertion, for example). That leaves an empty unbound graph
        // which is harmless but would otherwise block every retry. Treat "exists and still
        // empty" as satisfiable; anything non-empty is a real conflict and is refused.
        var existing = Resources().Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (existing.Length != 0)
        {
            // Create only guarantees "a graph of this name exists". Whether its current
            // node state is buildable is BuildGameLoopGraph's business, which knows about
            // resuming a half-built graph. Refusing here made a resumable graph unreachable.
            if (existing.Length != 1)
                throw new InvalidOperationException("GAMELOOP_CREATE_AMBIGUOUS:" + existing.Length);
            return new
            {
                ok = true,
                name = GameLoopGraphName,
                graphId = existing[0].Id,
                nodeCount = GraphNodes(existing[0].Model).Count,
                status = "gameloop-already-present"
            };
        }
        if (Spent("create",GameLoopGraphName)) throw new InvalidOperationException("GAMELOOP_CREATE_ALREADY_ATTEMPTED");
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var method = manager.GetType().GetMethod(B("yBnirE4YONq"), Fields)!;
        Spend("create",GameLoopGraphName);
        method.Invoke(manager, new object?[] { Enum.ToObject(method.GetParameters()[0].ParameterType, 20000), GameLoopGraphName, 0u, null });
        return new { ok = true, name = GameLoopGraphName, status = "gameloop-created-unbound" };
    }

    // Definition-side pin lookup. The definition pin objects expose the name through the
    // proven FinishNodeCatalog accessors; an INSTANCE pin does not carry that getter, which
    // is why naming has to be checked against the node definition rather than the node.
    int? DefinitionPinKeyPart(object pinDefinition, string field)
    {
        var key = Stored(pinDefinition, B("quGKmYyTPnA"));
        return key == null ? null : (int?)Convert.ToInt32(Field(key, field));
    }

    // Fails the build before any link is made when an assumed pin index does not carry the
    // name the official parameter table gives it. Used for the two nodes whose pins were
    // never read from this build of the editor.
    void AssertDefinitionPinName(List<Resource> resources, uint nodeDefinitionId, int kind, int index, string expected)
    {
        var definition = resources.First(r => r.Kind == 6 && r.Id == nodeDefinitionId
            && r.Category.SequenceEqual(new uint[] { 10001, 20000, 22000, 0 }));
        var pins = ((IEnumerable)definition.Model).Cast<object>().ToArray();
        var match = pins.FirstOrDefault(p => DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) == kind
                                          && DefinitionPinKeyPart(p, B("hWTK5MSRidQ")) == index);
        if (match == null)
            throw new InvalidOperationException("GAMELOOP_PIN_MISSING:" + nodeDefinitionId + ":" + kind + ":" + index
                + ":observed=" + string.Join("|", pins.Select(p =>
                    (Stored(p, B("T5GKmPxKaWk")) as string ?? "<null>") + "@"
                    + DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) + ":" + DefinitionPinKeyPart(p, B("hWTK5MSRidQ")))));
        var actual = Stored(match, B("T5GKmPxKaWk")) as string ?? string.Empty;
        if (!string.Equals(actual, expected, StringComparison.Ordinal))
            throw new InvalidOperationException("GAMELOOP_PIN_NAME_MISMATCH:" + nodeDefinitionId + ":" + kind + ":" + index
                + ":expected=" + expected + ":actual=" + actual);
    }

    public object BuildGameLoopGraph()
    {
        if (gameLoopBuildAttempted) throw new InvalidOperationException("GAMELOOP_BUILD_ALREADY_ATTEMPTED");
        var resources = Resources();
        // Diagnosis over guesswork: a bare Single() says only "no elements", which cannot
        // distinguish "the create did not land" from "the name field reads differently".
        // Every lookup below reports what it actually saw.
        // The registry walk reaches the same graph through several paths: this build
        // returns every kind-9 resource three times, so a raw name filter matches three
        // copies of one graph. Deduplicate by id before counting, exactly as the finish
        // graph does, and report both the raw and deduplicated counts if it still fails.
        var byId = resources.Where(r => r.Kind == 9)
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var matches = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("GAMELOOP_LOOKUP:expected=1:actual=" + matches.Length
                + ":rawKind9=" + resources.Count(r => r.Kind == 9)
                + ":distinctKind9=" + byId.Length
                + ":names=" + string.Join("|", byId.Select(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) ?? "<null>")));
        var graph = matches[0];
        if (entityModels.Any(e => EntityBindings(e).Any(k => (uint)Field(k, B("namiwGPRyPS")) == graph.Id)))
            throw new InvalidOperationException("GAMELOOP_MUST_BE_UNBOUND");
        gameLoopBuildAttempted = true;

        object Add(uint id, int order)
        {
            var def = resources.First(r => r.Kind == 6 && r.Id == id && r.Category.SequenceEqual(new uint[] { 10001, 20000, 22000, 0 }));
            return graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"), Fields)!.Invoke(graph.Model,
                new object?[] { Stored(def.Model, B("U0oKESVcL9L")), (double)((order % 5) * 400), (double)((order / 5) * 400), null, null })!;
        }
        void Link(object from, int fk, int fi, object to, int tk, int ti)
        {
            object Address(object n, int k, int i) => Pin(n, k, i).GetType().GetMethod(B("SrvK5eKUmbB"), Fields)!.Invoke(Pin(n, k, i), null)!;
            var ctor = Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"), true)!.GetConstructors().Single(c => c.GetParameters().Length == 2);
            var link = ctor.Invoke(new[] { Address(from, fk, fi), Address(to, tk, ti) });
            if (!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(graph.Model, new object?[] { link, null, -1 })!)
                throw new InvalidOperationException("GAMELOOP_LINK_REJECTED:" + fk + ":" + fi + "->" + tk + ":" + ti);
        }
        object Value(object n, int i) { var p = Pin(n, 3, i); var w = p.GetType().GetProperty("value")!.GetValue(p)!; return w.GetType().GetProperty("Value")!.GetValue(w)!; }
        void Set(object n, int i, string method, object data) { var v = Value(n, i); if (v.GetType().GetMethod(B("KiPKKaQUNLS"), Fields)!.Invoke(v, null)!.ToString() == "Generics") v = v.GetType().GetMethod(B("eUgKKLsg3Lw"), Fields)!.Invoke(v, null)!; v.GetType().GetMethod(method, Fields)!.Invoke(v, new object?[] { data, null }); }

        // --- pin-layout assertions, before ANY mutation ----------------------
        // Node 805 is the native Classic teleport; 288 is Beyond-only. Parameter
        // names and types were checked against the decoded native definitions. Asserting here, ahead of the first Add,
        // means a wrong index costs nothing: no half-built graph is left behind. Getting
        // this order wrong once already produced a 29-node orphan with no connections.
        AssertDefinitionPinName(resources, 647, 3, 0, "设置实体");
        AssertDefinitionPinName(resources, 647, 3, 1, "数据顺序");
        AssertDefinitionPinName(resources, 647, 3, 2, "数据名称");
        AssertDefinitionPinName(resources, 647, 3, 3, "数据值");
        AssertDefinitionPinName(resources, 805, 3, 0, "玩家实体");
        AssertDefinitionPinName(resources, 805, 3, 1, "目标位置");
        AssertDefinitionPinName(resources, 805, 3, 2, "目标旋转");

        // --- nodes: resume a half-built graph, otherwise add them -------------
        // There is no delete-graph operation in this project's surface, so a build that
        // died after adding nodes would otherwise strand the graph name forever. A graph
        // holding exactly the expected nodes and no links is the state an earlier Add-only
        // pass leaves; finish that one instead of refusing it. The independent export
        // verifier is what proves the resumed nodes really are the designed ones.
        // The node map is keyed by node index, and a dictionary does not promise
        // enumeration order, so sort by key rather than trusting insertion order.
        // Enumerated through IDictionary explicitly: this build's map is a generic
        // Dictionary<uint, node>, so Cast<DictionaryEntry>() yields KeyValuePair and
        // throws on the cast.
        var nodeMap = GraphNodes(graph.Model);
        var nodeKeys = new List<uint>(nodeMap.Count);
        foreach (var key in nodeMap.Keys) nodeKeys.Add(Convert.ToUInt32(key));
        nodeKeys.Sort();
        var existing = new object[nodeKeys.Count];
        for (var i = 0; i < nodeKeys.Count; i++) existing[i] = nodeMap[nodeKeys[i]]!;
        if (existing.Length != 0 && existing.Length != GameLoopNodeTarget)
            throw new InvalidOperationException("GAMELOOP_PARTIAL_BUILD_UNEXPECTED:" + existing.Length
                + ":expected=0-or-" + GameLoopNodeTarget);
        var resume = existing.Length == GameLoopNodeTarget;
        var handles = resume ? existing : new object[GameLoopNodeTarget];
        if (!resume)
        {
            handles[0] = Add(71, 0); handles[1] = Add(73, 1); handles[2] = Add(14, 2); handles[3] = Add(2, 3); handles[4] = Add(1, 4);
            handles[5] = Add(79, 5); handles[6] = Add(83, 6); handles[7] = Add(14, 7); handles[8] = Add(2, 8); handles[9] = Add(248, 9);
            handles[10] = Add(509, 10); handles[11] = Add(804, 11); handles[12] = Add(99, 12); handles[13] = Add(225, 13); handles[14] = Add(244, 14);
            handles[15] = Add(231, 15); handles[16] = Add(9, 16); handles[17] = Add(233, 17); handles[18] = Add(226, 18); handles[19] = Add(2, 19);
            handles[20] = Add(82, 20); handles[21] = Add(1, 21); handles[22] = Add(652, 22); handles[23] = Add(647, 23); handles[24] = Add(77, 24);
            handles[25] = Add(230, 25); handles[26] = Add(2, 26); handles[27] = Add(225, 27); handles[28] = Add(805, 28);
        }
        var created = handles[0]; var self = handles[1]; var ownerEqual = handles[2]; var ownerBranch = handles[3]; var startPrint = handles[4];
        var timer = handles[5]; var tick = handles[6]; var nameEqual = handles[7]; var nameBranch = handles[8]; var players = handles[9];
        var playerLoop = handles[10]; var activeRole = handles[11]; var position = handles[12]; var goalVec = handles[13]; var distance = handles[14];
        var nearPad = handles[15]; var split = handles[16]; var aboveGround = handles[17]; var both = handles[18]; var reachBranch = handles[19];
        var stopTimer = handles[20]; var finishPrint = handles[21]; var settleStatus = handles[22]; var scoreboard = handles[23]; var settleStage = handles[24];
        var fellBelow = handles[25]; var fallBranch = handles[26]; var respawnVec = handles[27]; var teleport = handles[28];

        // --- flow ----------------------------------------------------------
        Link(created, 2, 0, ownerBranch, 1, 0);
        Link(ownerBranch, 2, 0, startPrint, 1, 0);
        Link(startPrint, 2, 0, timer, 1, 0);
        Link(tick, 2, 0, nameBranch, 1, 0);
        Link(nameBranch, 2, 0, playerLoop, 1, 0);
        Link(playerLoop, 2, 0, reachBranch, 1, 0);
        // Reaching the goal ends the run: stop the clock, score it, settle the level.
        Link(reachBranch, 2, 0, stopTimer, 1, 0);
        Link(stopTimer, 2, 0, finishPrint, 1, 0);
        Link(finishPrint, 2, 0, settleStatus, 1, 0);
        Link(settleStatus, 2, 0, scoreboard, 1, 0);
        Link(scoreboard, 2, 0, settleStage, 1, 0);
        // Not at the goal: check for a fall, and recover if so. The false path of the reach
        // branch is what keeps this from teleporting a player who is still on the course.
        Link(reachBranch, 2, 1, fallBranch, 1, 0);
        Link(fallBranch, 2, 0, teleport, 1, 0);

        // --- data: run start ----------------------------------------------
        Link(created, 4, 0, ownerEqual, 3, 0);
        Link(self, 4, 0, ownerEqual, 3, 1);
        Link(ownerEqual, 4, 0, ownerBranch, 3, 0);
        Link(self, 4, 0, timer, 3, 0);
        Set(startPrint, 0, B("MfLKK0bLIju"), GameLoopStartMarker);
        Set(timer, 1, B("MfLKK0bLIju"), GameLoopTimerName);
        Set(timer, 2, B("X8oKKHB87Ue"), 1u);

        // One-second repeating sequence. Same proven native float-list construction the
        // finish graph uses, with a single element instead of a guessed enum.
        var timerDef = resources.First(r => r.Kind == 6 && r.Id == 79 && r.Category.SequenceEqual(new uint[] { 10001, 20000, 22000, 0 }));
        var timerPins = ((IEnumerable)timerDef.Model).Cast<object>().ToArray();
        // Locate the sequence pin by index first (the value this build reports), then fall
        // back to its definition name. A bare Single() would report only "no elements".
        var sequenceConfig = timerPins.FirstOrDefault(p => DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) == 3
                                                        && DefinitionPinKeyPart(p, B("hWTK5MSRidQ")) == 3)
            ?? timerPins.FirstOrDefault(p => (Stored(p, B("T5GKmPxKaWk")) as string) == "定时器序列");
        if (sequenceConfig == null)
            throw new InvalidOperationException("GAMELOOP_TIMER_SEQUENCE_PIN_NOT_FOUND:pins=" + timerPins.Length
                + ":observed=" + string.Join("|", timerPins.Select(p =>
                    (Stored(p, B("T5GKmPxKaWk")) as string ?? "<null>") + "@"
                    + DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) + ":" + DefinitionPinKeyPart(p, B("hWTK5MSRidQ")))));
        var wrapper = sequenceConfig.GetType().GetMethod(B("l6uKazVUo9s"), Fields)!.Invoke(sequenceConfig, null)!;
        var sequenceDef = wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        var elementDef = sequenceDef.GetType().GetMethod(B("Ov2K7oYGvHi"), Fields)!.Invoke(sequenceDef, null)!;
        var sequence = Value(timer, 3);
        var element = sequence.GetType().GetMethod(B("KRQKKuygfFk"), Fields)!.Invoke(sequence, new object?[] { elementDef, null })!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"), Fields)!.Invoke(element, new object?[] { GameLoopTickSeconds, null });

        // --- data: tick identity ------------------------------------------
        Link(tick, 4, 2, nameEqual, 3, 0);
        Set(nameEqual, 1, B("MfLKK0bLIju"), GameLoopTimerName);
        Link(nameEqual, 4, 0, nameBranch, 3, 0);

        // --- data: per-player goal and fall test ---------------------------
        Link(players, 4, 0, playerLoop, 3, 0);
        Link(playerLoop, 4, 0, activeRole, 3, 0);
        Link(activeRole, 4, 0, position, 3, 0);
        Set(goalVec, 0, B("SH7KKvk8cxe"), 17f); Set(goalVec, 1, B("SH7KKvk8cxe"), 2.5f); Set(goalVec, 2, B("SH7KKvk8cxe"), 0f);
        Link(position, 4, 0, distance, 3, 0);
        Link(goalVec, 4, 0, distance, 3, 1);
        Link(distance, 4, 0, nearPad, 3, 0); Set(nearPad, 1, B("SH7KKvk8cxe"), 2f);
        Link(position, 4, 0, split, 3, 0);
        Link(split, 4, 1, aboveGround, 3, 0); Set(aboveGround, 1, B("SH7KKvk8cxe"), 2.4f);
        Link(nearPad, 4, 0, both, 3, 0); Link(aboveGround, 4, 0, both, 3, 1);
        Link(both, 4, 0, reachBranch, 3, 0);

        // --- data: finish side --------------------------------------------
        Link(self, 4, 0, stopTimer, 3, 0);
        Set(stopTimer, 1, B("MfLKK0bLIju"), GameLoopTimerName);
        Set(finishPrint, 0, B("MfLKK0bLIju"), GameLoopFinishMarker);
        Link(playerLoop, 4, 0, settleStatus, 3, 0);
        Set(settleStatus, 1, B("X8oKKHB87Ue"), GameLoopVictory);
        Link(playerLoop, 4, 0, scoreboard, 3, 0);
        // Row order is S_INT, not an enum-backed bool: the enum setter X8oKKHB87Ue writes a
        // different storage slot and left this pin value-less. c84KKE8ihrN is the int
        // setter (value-instance.cs, paired with the ilqKKrw7dhN getter).
        Set(scoreboard, 1, B("c84KKE8ihrN"), 0);
        Set(scoreboard, 2, B("MfLKK0bLIju"), GameLoopScoreName); // row label
        // The tick counter IS the elapsed second count, because the period is 1.0 s.
        Link(tick, 4, 4, scoreboard, 3, 3);
        Set(settleStage, 0, B("X8oKKHB87Ue"), 1u);               // settle as success

        // --- data: fall recovery -------------------------------------------
        Link(split, 4, 1, fellBelow, 3, 0);
        Set(fellBelow, 1, B("SH7KKvk8cxe"), GameLoopFallBelowY);
        Link(fellBelow, 4, 0, fallBranch, 3, 0);
        Set(respawnVec, 0, B("SH7KKvk8cxe"), GameLoopRespawnX);
        Set(respawnVec, 1, B("SH7KKvk8cxe"), GameLoopRespawnY);
        Set(respawnVec, 2, B("SH7KKvk8cxe"), GameLoopRespawnZ);
        Link(playerLoop, 4, 0, teleport, 3, 0);
        Link(respawnVec, 4, 0, teleport, 3, 1);

        if (GraphNodes(graph.Model).Count != GameLoopNodeTarget)
            throw new InvalidOperationException("GAMELOOP_NODE_COUNT_MISMATCH");
        return new
        {
            ok = true,
            status = "gameloop-authored-unbound-export-required",
            resumedExistingNodes = resume,
            graphId = graph.Id,
            nodeCount = GraphNodes(graph.Model).Count,
            timer = GameLoopTimerName,
            tickSeconds = GameLoopTickSeconds,
            markers = new[] { GameLoopStartMarker, GameLoopFinishMarker, GameLoopFallMarker },
            goal = new[] { 17d, 2.5d, 0d },
            maxDistance = 2.0,
            minimumHeight = 2.4,
            fallBelowY = GameLoopFallBelowY,
            respawn = new[] { GameLoopRespawnX, GameLoopRespawnY, GameLoopRespawnZ },
            scoreRow = GameLoopScoreName,
            bound = false,
            runtimeVerified = false
        };
    }

    // Repair existing definitions, including unbound variants: upload may validate them
    // too. No graphs, nodes, links or bindings are created/deleted by this operation.
    public object RepairGameLoopSettlementStatus()
    {
        var resources = Resources();
        var definition = resources.First(r => r.Kind == 6 && r.Id == 652 && r.Category.SequenceEqual(FinishCategory));
        var definitionPin = ((IEnumerable)definition.Model).Cast<object>().Single(p =>
            DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) == 3 && DefinitionPinKeyPart(p, B("hWTK5MSRidQ")) == 1);
        var pinDefinition = FinishPinDefinition(definitionPin)!;
        if (Convert.ToUInt32(Stored(pinDefinition, B("eOjKYPILbRH"))) != 34u ||
            Convert.ToUInt32(Stored(pinDefinition, B("pR9KY126SEr"))) != 14u)
            throw new InvalidOperationException("SETTLEMENT_NATIVE_ENUM_CONTRACT_CHANGED");

        var allowed = new Dictionary<string, int> {
            { GameLoopGraphName, GameLoopNodeTarget },
            { GameLoopVariantNoScoreboardName, GameLoopVariantNoScoreboardNodes },
            { GameLoopVariantCoreName, GameLoopVariantCoreNodes }
        };
        var graphs = resources.Where(r => r.Kind == 9 && allowed.ContainsKey(Stored(r.Model, B("c1pKbESgr8S")) as string ?? ""))
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (graphs.Length == 0 || graphs.GroupBy(r => Stored(r.Model, B("c1pKbESgr8S")) as string).Any(g => g.Count() != 1))
            throw new InvalidOperationException("SETTLEMENT_OWN_GRAPH_IDENTITY_AMBIGUOUS");
        uint Read(object value) {
            var wrapper = value.GetType().GetMethod(B("cPOKKedklwd"), Fields)!.Invoke(value, null)!;
            return Convert.ToUInt32(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper));
        }
        var targets = new List<(uint graphId, string name, uint nodeId, object value, uint before)>();
        // Resolve every target and old value before any mutation, including unbound graphs.
        foreach (var graph in graphs)
        {
            var name = (string)Stored(graph.Model, B("c1pKbESgr8S"))!;
            var nodes = GraphNodes(graph.Model);
            if (nodes.Count != allowed[name]) throw new InvalidOperationException("SETTLEMENT_GRAPH_SHAPE_CHANGED:" + name);
            var matches = new List<(uint id, object node)>();
            foreach (var key in nodes.Keys) {
                var node = nodes[key]!;
                if ((uint)Field(Stored(node, B("tLtKHleyQAZ"))!, B("namiwGPRyPS")) == 652u)
                    matches.Add((Convert.ToUInt32(key), node));
            }
            if (matches.Count != (name == GameLoopVariantCoreName ? 0 : 1))
                throw new InvalidOperationException("SETTLEMENT_NODE_COUNT_CHANGED:" + name);
            foreach (var match in matches)
            {
                var pin = Pin(match.node, 3, 1);
                var wrapper = pin.GetType().GetProperty("value")!.GetValue(pin)!;
                var value = wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
                if (Convert.ToInt32(value.GetType().GetMethod(B("KiPKKaQUNLS"), Fields)!.Invoke(value, null)) != 6)
                    throw new InvalidOperationException("SETTLEMENT_VALUE_NOT_ENUM");
                var before = Read(value);
                if (before != 1u && before != GameLoopVictory)
                    throw new InvalidOperationException("SETTLEMENT_UNEXPECTED_VALUE:" + before);
                targets.Add((graph.Id, name, match.id, value, before));
            }
        }
        foreach (var target in targets)
            if (target.before != GameLoopVictory)
                target.value.GetType().GetMethod(B("X8oKKHB87Ue"), Fields)!.Invoke(target.value, new object?[] { GameLoopVictory, null });
        var results = targets.Select(t => new { graphId=t.graphId, name=t.name, nodeIndex=t.nodeId,
            before=t.before, after=Read(t.value), changed=t.before != GameLoopVictory }).ToArray();
        if (results.Any(r => r.after != GameLoopVictory)) throw new InvalidOperationException("SETTLEMENT_READBACK_FAILED");
        return new { ok=true, status="settlement-enum-repaired-readback-only", results,
            inspectedGraphs=graphs.Select(g=>g.Id).ToArray(),
            persistentSaveVerified=false, playtestVerified=false };
    }

    // Legacy zero-row normalization. Empty val_int is normal protobuf zero omission;
    // this operation is not a fix for upload validation failure.
    public object RepairGameLoopScoreOrder()
    {
        var resources = Resources();
        var byId = resources.Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var matches = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("GAMELOOP_REPAIR_LOOKUP:expected=1:actual=" + matches.Length);
        var graph = matches[0];
        if (entityModels.Any(e => EntityBindings(e).Any(k => (uint)Field(k, B("namiwGPRyPS")) == graph.Id)))
            throw new InvalidOperationException("GAMELOOP_REPAIR_REQUIRES_OWN_UNBOUND_GRAPH");
        var nodeMap = GraphNodes(graph.Model);
        var keys = new List<uint>(nodeMap.Count);
        foreach (var key in nodeMap.Keys) keys.Add(Convert.ToUInt32(key));
        keys.Sort();
        if (keys.Count != GameLoopNodeTarget)
            throw new InvalidOperationException("GAMELOOP_REPAIR_NODE_COUNT:" + keys.Count);
        var scoreboard = nodeMap[keys[23]]!;   // node index 24 in the 1-based design order
        var pin = Pin(scoreboard, 3, 1);
        var wrapper = pin.GetType().GetProperty("value")!.GetValue(pin)!;
        var value = wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)
            ?? throw new InvalidOperationException("GAMELOOP_REPAIR_VALUE_NULL");
        // NO generics unwrap here. The calibration graph writes its integer through exactly
        // this path (EditorAdapter.cs:603, proven by export bridge-export-d04d411289af49
        // reading val_int {'int': 1}), while this method previously took an extra
        // "unwrap if generic" step borrowed from the string/float setter. That extra step is
        // the only difference from the known-good path, and this pin is the only place in
        // the whole graph where an integer constant is written.
        value.GetType().GetMethod(B("c84KKE8ihrN"), Fields)!.Invoke(value, new object?[] { 0, null });
        var readWrapper = value.GetType().GetMethod(B("ilqKKrw7dhN"), Fields)!.Invoke(value, null)!;
        var readback = (int)readWrapper.GetType().GetProperty("Value")!.GetValue(readWrapper)!;
        if (readback != 0)
            throw new InvalidOperationException("GAMELOOP_SCORE_ORDER_READBACK:" + readback);
        return new
        {
            ok = true,
            status = "gameloop-score-order-repaired-unbound",
            graphId = graph.Id,
            nodeIndex = keys[23],
            readback,
            runtimeVerified = false
        };
    }

    // Removes ONLY this project's own demo graph from the level entity's binding list, and
    // nothing else. This exists to tell apart two explanations that look identical from the
    // outside: "this level stopped validating because of the demo graph" versus "it stopped
    // for an unrelated reason". Unbinding is reversible — the graph itself is untouched and
    // BindGameLoopGraph puts the binding back — which is what makes it a fair experiment on
    // a level that belongs to the user rather than to this project.
    //
    // The removal uses the entity's own binding collection API (value-set.cs):
    //   XpyJGKiNEBG3qlCFJJeg<T>.lUBiNLoXRl5(index, notify) removes one entry by index.
    // notify stays true so the editor's model and view stay consistent; suppressing it would
    // leave the removal half-applied.
    public object UnbindGameLoopGraph()
    {
        var resources = Resources();
        var byId = resources.Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var matches = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("GAMELOOP_UNBIND_LOOKUP:expected=1:actual=" + matches.Length);
        var graph = matches[0];
        var entity = entityModels.FirstOrDefault(e => (uint)Field(Stored(e, B("Qi8iCzKCkTt"))!, B("namiwGPRyPS")) == 1094713345u)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_LEVEL_ENTITY_NOT_FOUND");

        var collection = entity.GetType().GetMethod(B("t6ViSxlgnQ3"), Fields)!.Invoke(entity, null)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_COLLECTION_MISSING");
        var inner = Field(collection, B("VAfiNjPuW4e"))
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_INNER_LIST_MISSING");
        var entries = ((IEnumerable)inner).Cast<object>().ToArray();

        var index = -1;
        for (var i = 0; i < entries.Length; i++)
        {
            var boundId = (uint)Field(entries[i], B("namiwGPRyPS"));
            if (boundId == graph.Id) { index = i; break; }
        }
        if (index < 0)
            return new { ok = true, status = "gameloop-not-bound-nothing-to-do", graphId = graph.Id, bindingCount = entries.Length };

        var remove = collection.GetType().GetMethod(B("lUBiNLoXRl5"), Fields)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_REMOVE_METHOD_MISSING");
        remove.Invoke(collection, new object?[] { index, true });

        var remaining = ((IEnumerable)Field(collection, B("VAfiNjPuW4e"))!).Cast<object>()
            .Select(k => (uint)Field(k, B("namiwGPRyPS"))).OrderBy(x => x).ToArray();
        if (remaining.Contains(graph.Id))
            throw new InvalidOperationException("GAMELOOP_UNBIND_DID_NOT_TAKE");
        return new
        {
            ok = true,
            status = "gameloop-unbound",
            graphId = graph.Id,
            removedIndex = index,
            bindingCountBefore = entries.Length,
            remainingBindingIds = remaining,
            graphStillExists = true,
            reversible = true,
            persistentSaveVerified = false
        };
    }

    // Variant builder for bisecting a playtest-validation failure.
    //
    // The full demo graph is the existing finish graph plus exactly four node
    // definitions: 652 (settlement status), 647 (scoreboard row), 805 (Classic teleport) and
    // 230 (a plain numeric compare). The 2026-09-19 audit found an illegal enum value on
    // 652. The earlier suspicion of 647's zero row was disproved. Mode compatibility of
    // 288 was absent from the native Classic catalog; new builds use 805.
    // Existing graphs require a separate repair and real playtest acceptance.
    //
    // Dropping 647 also removes its link in the settle chain, so the chain becomes
    // 652 -> 77 directly. Everything else, including all 22 nodes shared with the existing
    // finish graph, is built identically. The graph is created unbound; binding and
    // unbinding the suspect graph is a separate, already-proven step.
    // Two fixed variants rather than an open parameter surface: the bridge's contract is a
    // fixed operation enum, and a caller-supplied graph name would be a free-form write.
    const string GameLoopVariantNoScoreboardName = "MW_Game_Loop_V2_20260917";
    const string GameLoopVariantCoreName = "MW_Game_Loop_V3_20260917";

    public object BuildGameLoopVariantNoScoreboard()
        => BuildGameLoopVariantGraph(GameLoopVariantNoScoreboardName, withScoreboard: false, withSettlementStatus: true);

    public object BuildGameLoopVariantCore()
        => BuildGameLoopVariantGraph(GameLoopVariantCoreName, withScoreboard: false, withSettlementStatus: false);

    // Node counts must match the builders above or BindOwnGraph refuses the bind.
    const int GameLoopVariantNoScoreboardNodes = 28;
    const int GameLoopVariantCoreNodes = 27;

    public object BindGameLoopVariantNoScoreboard()
        => BindOwnGraph(GameLoopVariantNoScoreboardName, null, GameLoopVariantNoScoreboardNodes);

    public object BindGameLoopVariantCore()
        => BindOwnGraph(GameLoopVariantCoreName, null, GameLoopVariantCoreNodes);

    // --- MVP course -------------------------------------------------------------------
    // The full loop (scoreboard AND settlement status) on the MVP course geometry, so the
    // same proven wiring is reused instead of a second copy that could drift.
    //
    // Bind is deliberately its own operation rather than BindGameLoopGraph. That one
    // requires the 20260917 course's calibration/route/position graphs to already exist and
    // be bound, because on THAT course the loop is the fifth of five graphs. The MVP course
    // is a single self-contained graph on a level whose userGraphs is empty, so requiring
    // three unrelated graphs would make the loop unbuildable there. The bind itself is the
    // same proven BindOwnGraph path the two variants already use.
    public object CreateMvpCourseGraph() => CreateGameLoopVariant(MvpCourseGraphName);
    public object BuildMvpCourseGraph()
        => BuildGameLoopVariantGraph(MvpCourseGraphName, withScoreboard: true, withSettlementStatus: true,
            MvpGoalX, MvpGoalY, MvpGoalZ, MvpMinHeight, MvpRespawnX, MvpRespawnY, MvpRespawnZ);
    public object BindMvpCourseGraph() => BindOwnGraph(MvpCourseGraphName, null, MvpCourseNodes);
    public object ExportMvpCourseGraph(string directory)
    {
        var graph = Resources().Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == MvpCourseGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).Single();
        return ExportResource(graph, directory);
    }

    // Removes the bindings of ALL of this project's demo graphs at once - the main graph and
    // both bisect variants. Swapping variants one at a time would otherwise leave the
    // previous variant bound, and a playtest against two demo graphs at once cannot tell
    // which one was refused. Removes bindings only; no graph is deleted.
    public object UnbindAllGameLoopGraphs()
    {
        var resources = Resources();
        var byId = resources.Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var ours = new[] { GameLoopGraphName, GameLoopVariantNoScoreboardName, GameLoopVariantCoreName };
        var ourIds = byId.Where(r => ours.Contains(Stored(r.Model, B("c1pKbESgr8S")) as string ?? ""))
            .Select(r => r.Id).ToHashSet();

        var entity = entityModels.FirstOrDefault(e => (uint)Field(Stored(e, B("Qi8iCzKCkTt"))!, B("namiwGPRyPS")) == 1094713345u)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_ALL_LEVEL_ENTITY_NOT_FOUND");
        var collection = entity.GetType().GetMethod(B("t6ViSxlgnQ3"), Fields)!.Invoke(entity, null)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_ALL_COLLECTION_MISSING");
        var remove = collection.GetType().GetMethod(B("lUBiNLoXRl5"), Fields)
            ?? throw new InvalidOperationException("GAMELOOP_UNBIND_ALL_REMOVE_METHOD_MISSING");

        // Walk downwards: removing an entry shifts every later index.
        var removed = new List<uint>();
        var entries = ((IEnumerable)Field(collection, B("VAfiNjPuW4e"))!).Cast<object>().ToArray();
        for (var i = entries.Length - 1; i >= 0; i--)
        {
            var boundId = (uint)Field(entries[i], B("namiwGPRyPS"));
            if (!ourIds.Contains(boundId)) continue;
            remove.Invoke(collection, new object?[] { i, true });
            removed.Add(boundId);
        }

        var remaining = ((IEnumerable)Field(collection, B("VAfiNjPuW4e"))!).Cast<object>()
            .Select(k => (uint)Field(k, B("namiwGPRyPS"))).OrderBy(x => x).ToArray();
        if (remaining.Any(ourIds.Contains))
            throw new InvalidOperationException("GAMELOOP_UNBIND_ALL_DID_NOT_TAKE");
        return new
        {
            ok = true,
            status = "gameloop-all-unbound",
            removedGraphIds = removed.OrderBy(x => x).ToArray(),
            remainingBindingIds = remaining,
            graphsStillExist = true,
            persistentSaveVerified = false
        };
    }

    public object CreateGameLoopVariantNoScoreboard() => CreateGameLoopVariant(GameLoopVariantNoScoreboardName);
    public object CreateGameLoopVariantCore() => CreateGameLoopVariant(GameLoopVariantCoreName);

    // Create and build MUST be separate bridge operations.
    //
    // The graph-create call queues work onto the WPF dispatcher. Doing the create and then
    // immediately re-reading the registry inside the SAME dispatcher invocation found zero
    // matches (GAMELOOP_VARIANT_LOOKUP:expected=1:actual=0): the queued create had not run,
    // because the dispatcher was busy executing the build. Splitting them lets the dispatcher
    // drain between calls, which is what the proven create-gameloop-graph /
    // build-gameloop-graph pair already relied on.
    object CreateGameLoopVariant(string graphName)
    {
        if (string.IsNullOrWhiteSpace(graphName) || graphName.Length > 64)
            throw new InvalidOperationException("GAMELOOP_VARIANT_NAME_INVALID");
        var byId = Resources().Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var existing = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == graphName).ToArray();
        if (existing.Length != 0)
        {
            // A previous attempt may have queued a create that landed only afterwards.
            if (existing.Length != 1)
                throw new InvalidOperationException("GAMELOOP_VARIANT_AMBIGUOUS:" + existing.Length);
            return new
            {
                ok = true,
                status = "gameloop-variant-already-present",
                graphId = existing[0].Id,
                nodeCount = GraphNodes(existing[0].Model).Count
            };
        }
        var manager = ExistingSingleton(Editor(), B("mguq19iVCTpK600r3YtZ.Oe5aspiVGooyp47o5s0q"));
        var create = manager.GetType().GetMethod(B("yBnirE4YONq"), Fields)!;
        create.Invoke(manager, new object?[] {
            Enum.ToObject(create.GetParameters()[0].ParameterType, 20000), graphName, 0u, null });
        return new { ok = true, status = "gameloop-variant-created-unbound", name = graphName };
    }

    public object BuildGameLoopVariantGraph(string graphName, bool withScoreboard, bool withSettlementStatus,
        float goalX = Course17GoalX, float goalY = Course17GoalY, float goalZ = Course17GoalZ,
        float minHeight = Course17MinHeight,
        float respawnX = Course17RespawnX, float respawnY = Course17RespawnY, float respawnZ = Course17RespawnZ)
    {
        if (string.IsNullOrWhiteSpace(graphName) || graphName.Length > 64)
            throw new InvalidOperationException("GAMELOOP_VARIANT_NAME_INVALID");
        var resources = Resources();
        var byId = resources.Where(r => r.Kind == 9).GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        var matches = byId.Where(r => (Stored(r.Model, B("c1pKbESgr8S")) as string) == graphName).ToArray();
        if (matches.Length != 1)
            throw new InvalidOperationException("GAMELOOP_VARIANT_LOOKUP:expected=1:actual=" + matches.Length
                + ":distinctKind9=" + byId.Length);
        var graph = matches[0];
        if (GraphNodes(graph.Model).Count != 0)
            throw new InvalidOperationException("GAMELOOP_VARIANT_NOT_EMPTY:" + GraphNodes(graph.Model).Count);
        var refreshed = resources;

        object Add(uint id, int order)
        {
            var def = refreshed.First(r => r.Kind == 6 && r.Id == id && r.Category.SequenceEqual(new uint[] { 10001, 20000, 22000, 0 }));
            return graph.Model.GetType().GetMethod(B("BWmKmyL3bM7"), Fields)!.Invoke(graph.Model,
                new object?[] { Stored(def.Model, B("U0oKESVcL9L")), (double)((order % 5) * 400), (double)((order / 5) * 400), null, null })!;
        }
        void Link(object from, int fk, int fi, object to, int tk, int ti)
        {
            object Address(object n, int k, int i) => Pin(n, k, i).GetType().GetMethod(B("SrvK5eKUmbB"), Fields)!.Invoke(Pin(n, k, i), null)!;
            var ctor = Editor().GetType(B("xxJifxizw14DsEQR9gpM.TqhjM0izByRR2VKP9EkP"), true)!.GetConstructors().Single(c => c.GetParameters().Length == 2);
            var link = ctor.Invoke(new[] { Address(from, fk, fi), Address(to, tk, ti) });
            if (!(bool)graph.Model.GetType().GetMethod(B("LapKOOcuGY1"), Fields)!.Invoke(graph.Model, new object?[] { link, null, -1 })!)
                throw new InvalidOperationException("GAMELOOP_VARIANT_LINK_REJECTED:" + fk + ":" + fi + "->" + tk + ":" + ti);
        }
        object Value(object n, int i) { var p = Pin(n, 3, i); var w = p.GetType().GetProperty("value")!.GetValue(p)!; return w.GetType().GetProperty("Value")!.GetValue(w)!; }
        void Set(object n, int i, string method, object data) { var v = Value(n, i); if (v.GetType().GetMethod(B("KiPKKaQUNLS"), Fields)!.Invoke(v, null)!.ToString() == "Generics") v = v.GetType().GetMethod(B("eUgKKLsg3Lw"), Fields)!.Invoke(v, null)!; v.GetType().GetMethod(method, Fields)!.Invoke(v, new object?[] { data, null }); }

        var timerName = graphName + "_TICK";
        var order = 0;
        object N(uint id) => Add(id, order++);

        var created = N(71); var self = N(73); var ownerEqual = N(14); var ownerBranch = N(2); var startPrint = N(1);
        var timer = N(79); var tick = N(83); var nameEqual = N(14); var nameBranch = N(2); var players = N(248);
        var playerLoop = N(509); var activeRole = N(804); var position = N(99); var goalVec = N(225); var distance = N(244);
        var nearPad = N(231); var split = N(9); var aboveGround = N(233); var both = N(226); var reachBranch = N(2);
        var stopTimer = N(82); var finishPrint = N(1);
        var settleStatus = withSettlementStatus ? N(652) : null;
        var scoreboard = withScoreboard ? N(647) : null;
        var settleStage = N(77);
        var fellBelow = N(230); var fallBranch = N(2); var respawnVec = N(225); var teleport = N(805);

        // Assert the two never-before-read definitions before wiring anything.
        AssertDefinitionPinName(refreshed, 805, 3, 0, "玩家实体");
        AssertDefinitionPinName(refreshed, 805, 3, 1, "目标位置");
        AssertDefinitionPinName(refreshed, 805, 3, 2, "目标旋转");
        if (withScoreboard)
        {
            AssertDefinitionPinName(refreshed, 647, 3, 0, "设置实体");
            AssertDefinitionPinName(refreshed, 647, 3, 1, "数据顺序");
            AssertDefinitionPinName(refreshed, 647, 3, 2, "数据名称");
            AssertDefinitionPinName(refreshed, 647, 3, 3, "数据值");
        }
        if (withSettlementStatus)
        {
            AssertDefinitionPinName(refreshed, 652, 3, 0, "玩家实体");
            AssertDefinitionPinName(refreshed, 652, 3, 1, "结算状态");
        }

        Link(created, 2, 0, ownerBranch, 1, 0);
        Link(ownerBranch, 2, 0, startPrint, 1, 0);
        Link(startPrint, 2, 0, timer, 1, 0);
        Link(tick, 2, 0, nameBranch, 1, 0);
        Link(nameBranch, 2, 0, playerLoop, 1, 0);
        Link(playerLoop, 2, 0, reachBranch, 1, 0);
        Link(reachBranch, 2, 0, stopTimer, 1, 0);
        Link(stopTimer, 2, 0, finishPrint, 1, 0);
        var tail = finishPrint;
        if (settleStatus != null) { Link(tail, 2, 0, settleStatus, 1, 0); tail = settleStatus; }
        if (scoreboard != null) { Link(tail, 2, 0, scoreboard, 1, 0); tail = scoreboard; }
        Link(tail, 2, 0, settleStage, 1, 0);
        Link(reachBranch, 2, 1, fallBranch, 1, 0);
        Link(fallBranch, 2, 0, teleport, 1, 0);

        Link(created, 4, 0, ownerEqual, 3, 0);
        Link(self, 4, 0, ownerEqual, 3, 1);
        Link(ownerEqual, 4, 0, ownerBranch, 3, 0);
        Link(self, 4, 0, timer, 3, 0);
        Set(startPrint, 0, B("MfLKK0bLIju"), graphName + "_STARTED");
        Set(timer, 1, B("MfLKK0bLIju"), timerName);
        Set(timer, 2, B("X8oKKHB87Ue"), 1u);
        var timerDef = refreshed.First(r => r.Kind == 6 && r.Id == 79 && r.Category.SequenceEqual(new uint[] { 10001, 20000, 22000, 0 }));
        var timerPins = ((IEnumerable)timerDef.Model).Cast<object>().ToArray();
        var sequenceConfig = timerPins.FirstOrDefault(p => DefinitionPinKeyPart(p, B("TqBK5Pk3Cw2")) == 3
                                                        && DefinitionPinKeyPart(p, B("hWTK5MSRidQ")) == 3)
            ?? throw new InvalidOperationException("GAMELOOP_VARIANT_TIMER_SEQUENCE_PIN_NOT_FOUND");
        var wrapper = sequenceConfig.GetType().GetMethod(B("l6uKazVUo9s"), Fields)!.Invoke(sequenceConfig, null)!;
        var sequenceDef = wrapper.GetType().GetProperty("Value")!.GetValue(wrapper)!;
        var elementDef = sequenceDef.GetType().GetMethod(B("Ov2K7oYGvHi"), Fields)!.Invoke(sequenceDef, null)!;
        var sequence = Value(timer, 3);
        var element = sequence.GetType().GetMethod(B("KRQKKuygfFk"), Fields)!.Invoke(sequence, new object?[] { elementDef, null })!;
        element.GetType().GetMethod(B("SH7KKvk8cxe"), Fields)!.Invoke(element, new object?[] { GameLoopTickSeconds, null });

        Link(tick, 4, 2, nameEqual, 3, 0);
        Set(nameEqual, 1, B("MfLKK0bLIju"), timerName);
        Link(nameEqual, 4, 0, nameBranch, 3, 0);
        Link(players, 4, 0, playerLoop, 3, 0);
        Link(playerLoop, 4, 0, activeRole, 3, 0);
        Link(activeRole, 4, 0, position, 3, 0);
        Set(goalVec, 0, B("SH7KKvk8cxe"), goalX); Set(goalVec, 1, B("SH7KKvk8cxe"), goalY); Set(goalVec, 2, B("SH7KKvk8cxe"), goalZ);
        Link(position, 4, 0, distance, 3, 0);
        Link(goalVec, 4, 0, distance, 3, 1);
        Link(distance, 4, 0, nearPad, 3, 0); Set(nearPad, 1, B("SH7KKvk8cxe"), 2f);
        Link(position, 4, 0, split, 3, 0);
        Link(split, 4, 1, aboveGround, 3, 0); Set(aboveGround, 1, B("SH7KKvk8cxe"), minHeight);
        Link(nearPad, 4, 0, both, 3, 0); Link(aboveGround, 4, 0, both, 3, 1);
        Link(both, 4, 0, reachBranch, 3, 0);
        Link(self, 4, 0, stopTimer, 3, 0);
        Set(stopTimer, 1, B("MfLKK0bLIju"), timerName);
        Set(finishPrint, 0, B("MfLKK0bLIju"), graphName + "_FINISHED");
        if (settleStatus != null) { Link(playerLoop, 4, 0, settleStatus, 3, 0); Set(settleStatus, 1, B("X8oKKHB87Ue"), GameLoopVictory); }
        if (scoreboard != null)
        {
            Link(playerLoop, 4, 0, scoreboard, 3, 0);
            Set(scoreboard, 1, B("c84KKE8ihrN"), 0);
            Set(scoreboard, 2, B("MfLKK0bLIju"), GameLoopScoreName);
            Link(tick, 4, 4, scoreboard, 3, 3);
        }
        Set(settleStage, 0, B("X8oKKHB87Ue"), 1u);
        Link(split, 4, 1, fellBelow, 3, 0);
        Set(fellBelow, 1, B("SH7KKvk8cxe"), GameLoopFallBelowY);
        Link(fellBelow, 4, 0, fallBranch, 3, 0);
        Set(respawnVec, 0, B("SH7KKvk8cxe"), respawnX);
        Set(respawnVec, 1, B("SH7KKvk8cxe"), respawnY);
        Set(respawnVec, 2, B("SH7KKvk8cxe"), respawnZ);
        Link(playerLoop, 4, 0, teleport, 3, 0);
        Link(respawnVec, 4, 0, teleport, 3, 1);

        return new
        {
            ok = true,
            status = "gameloop-variant-authored-unbound",
            graphId = graph.Id,
            graphName,
            nodeCount = GraphNodes(graph.Model).Count,
            withScoreboard,
            withSettlementStatus,
            withFallRecovery = true,
            bound = false,
            runtimeVerified = false
        };
    }

    public object ExportGameLoopGraph(string directory)
    {
        var graph = Resources().Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).Single();
        return ExportResource(graph, directory);
    }

    public object BindGameLoopGraph()
    {
        var resources = Resources();
        foreach (var requirement in new[] { (CalibrationGraphName, 7), (TiledRouteName, 39), (PositionGraphName, 16) })
        {
            var bound = resources.Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == requirement.Item1)
                .GroupBy(r => r.Id).Select(g => g.First()).Single();
            if (GraphNodes(bound.Model).Count != requirement.Item2 || !entityModels.Any(e => (uint)Field(Stored(e, B("Qi8iCzKCkTt"))!, B("namiwGPRyPS")) == 1094713345u && EntityBindings(e).Any(k => (uint)Field(k, B("namiwGPRyPS")) == bound.Id)))
                throw new InvalidOperationException("BOUND_COURSE_REQUIRED_FOR_GAMELOOP");
        }
        var matches = resources.Where(r => r.Kind == 9 && (Stored(r.Model, B("c1pKbESgr8S")) as string) == GameLoopGraphName)
            .GroupBy(r => r.Id).Select(g => g.First()).ToArray();
        if (matches.Length != 1 || GraphNodes(matches[0].Model).Count != GameLoopNodeTarget)
            throw new InvalidOperationException("GAMELOOP_GRAPH_NOT_READY");
        return BindOwnGraph(GameLoopGraphName, null, GameLoopNodeTarget);
    }
}
