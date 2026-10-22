using System;
using System.Collections;
using System.Linq;
using System.Reflection;

namespace Miliastra.EditorBridge;

// Read-only evidence about the editor's audio service, discovered on 2026-09-28 by resolving
// the unattributed 'operation' records PlayMusic / PlaySoundEffect against the 7.1 assembly
// metadata and then reading the decompiled source.
//
// Everything here is a READ. It finds the type, reads its one static instance field, and
// reports the instance's own fields and delegates as types and values. It never calls
// PlayMusic, PlaySoundEffect or Stop. That separation is deliberate: a discovery should be
// able to be checked before anything is asked to make a sound.
//
// KNOWN SIDE EFFECT, stated rather than hidden: reading a static field runs the type's static
// constructor if it has not run yet. This type has one, and it calls a single registration
// helper. That is an editor-internal registration, not a level write and not a game call, but
// it is not nothing, and the reply says whether the field was already populated so a reader
// can judge whether the type was already live.
internal sealed partial class EditorAdapter
{
    // Type and member names are taken verbatim from the decompiled 7.1 source, which preserves
    // parameter names as well: the two public play methods carry volume, playbackSpeed, isLoop,
    // loopInterval, enableAttenuation, attenuationMaxDistance, attenuationType, beginMs, endMs
    // and enableFading. Nothing here has to infer what an argument means.
    const string AudioServiceType = "X5uvRfQTGYih6DgKn6gp.hXZ8d1QTaWJ3qNq8XOSK";
    const string AudioServiceStaticField = "rnsrAtCR0inHQJJo3fGT";
    const BindingFlags AnyStatic = BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic;

    object AudioServiceEvidence()
    {
        var report = new System.Collections.Generic.Dictionary<string, object?>
        {
            ["scope"] = "read-only type and instance inspection; no play or stop method is invoked",
            ["typeName"] = AudioServiceType,
            ["resolvedType"] = null,
            ["instanceFieldPresent"] = null,
            ["instancePresent"] = null,
            ["staticConstructorRunsOnFieldRead"] = true,
            ["delegateFields"] = null,
            ["scalarFields"] = null,
            ["playMethodsPresent"] = null,
            ["notice"] = "Absence here means the type or field was not found BY THIS NAME; it is not proof the "
                       + "editor has no audio service."
        };
        try
        {
            var type = Editor().GetType(AudioServiceType, false);
            if (type == null) { report["error"] = "AUDIO_TYPE_NOT_FOUND"; return report; }
            report["resolvedType"] = type.FullName;

            var field = type.GetField(AudioServiceStaticField, AnyStatic);
            report["instanceFieldPresent"] = field != null;
            if (field == null) { report["error"] = "AUDIO_INSTANCE_FIELD_NOT_FOUND"; return report; }

            var instance = field.GetValue(null);
            report["instancePresent"] = instance != null;
            if (instance == null)
            {
                report["notice"] = "the static instance field is null, so the editor's audio service has not been "
                                 + "constructed in this session; the type and the field both exist.";
                return report;
            }

            // Report what the instance HOLDS, as types and values only.
            var delegates = instance.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(f => typeof(Delegate).IsAssignableFrom(f.FieldType))
                .Select(f => new
                {
                    field = f.Name,
                    delegateType = f.FieldType.Name,
                    subscribed = f.GetValue(instance) != null
                }).ToArray();
            var scalars = instance.GetType().GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(f => f.FieldType.IsPrimitive || f.FieldType.IsEnum)
                .Select(f => new
                {
                    field = f.Name,
                    type = f.FieldType.Name,
                    value = f.GetValue(instance)?.ToString()
                }).ToArray();
            var plays = instance.GetType().GetMethods(BindingFlags.Instance | BindingFlags.Public)
                .Where(m => m.Name == "PlayMusic" || m.Name == "PlaySoundEffect" || m.Name == "Stop")
                .Select(m => new
                {
                    name = m.Name,
                    parameters = m.GetParameters().Select(p => p.ParameterType.Name + " " + p.Name).ToArray(),
                    returns = m.ReturnType.Name
                }).ToArray();

            report["delegateFields"] = delegates;
            report["scalarFields"] = scalars;
            report["playMethodsPresent"] = plays;
            report["notice"] = "Type, instance and method signatures were read. No play or stop method was invoked. "
                             + "Presence is not proof the editor will produce an audible result.";
        }
        catch (Exception ex)
        {
            report["error"] = "AUDIO_READ:" + ex.GetType().Name + ":" + ex.Message;
        }
        return report;
    }
}
