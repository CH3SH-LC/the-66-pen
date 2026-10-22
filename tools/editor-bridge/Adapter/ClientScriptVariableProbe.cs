using System;
using System.Collections;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    bool clientVariableAddSpent, clientVariableDeleteSpent, clientVariableResetSpent;
    object? clientVariableTarget;
    string? clientVariableExpected;

    object? ClientVariableRaw(object model, string field)
    {
        for (var type = model.GetType(); type != null; type = type.BaseType)
        {
            var member = type.GetField(field, Fields | BindingFlags.DeclaredOnly);
            if (member != null) return member.GetValue(model);
        }
        throw new InvalidOperationException("CLIENT_VARIABLE_FIELD_MISSING:" + field);
    }

    object? ClientVariableStored(object model, string field)
    {
        var wrapper = ClientVariableRaw(model, field);
        return wrapper == null ? null : ClientVariableRaw(wrapper, B("VpIiRZgdEln"));
    }

    object[] ClientVariableList(object model, string field)
    {
        var wrapper = ClientVariableRaw(model, field);
        if (wrapper == null) return Array.Empty<object>();
        var raw = ClientVariableRaw(wrapper, B("o26XLglnP6U"));
        if (raw is not IList list) throw new InvalidOperationException("CLIENT_VARIABLE_LIST_TYPE");
        if (list.Count > 2) throw new InvalidOperationException("CLIENT_VARIABLE_LIST_LIMIT");
        var rows = list.Cast<object>().ToArray();
        if (rows.Any(row => row == null || row.GetType().FullName != B("nmx7p5X19mallXS9F0gW.qjIcTlX1VHGqpFVYE3xA")))
            throw new InvalidOperationException("CLIENT_VARIABLE_MODEL_TYPE");
        return rows;
    }

    object ClientVariableView(object model)
    {
        object? Read(string field) => ClientVariableStored(model, field);
        var name = Read(B("MyhXSfcDunk"));
        if (name != null && (name is not string text || text.Length > 256))
            throw new InvalidOperationException("CLIENT_VARIABLE_NAME_TYPE_OR_LIMIT");
        var holder = ClientVariableRaw(model, B("IpxXSuDsn1C"));
        var value = holder == null ? null : ClientVariableRaw(holder, B("t9gXZ38FrdQ"));
        object? Value(string field) => value == null ? null : ClientVariableStored(value, field);
        var content = Value(B("u0HXrD9kTAg"));
        if (content != null && (content is not string textValue || textValue.Length > 512))
            throw new InvalidOperationException("CLIENT_VARIABLE_STRING_TYPE_OR_LIMIT");
        return new
        {
            variableId = Read(B("JaKXSlYOGFw")), clientParamType = Read(B("UH5X1FwNVD4")), name,
            serverParamType = Read(B("q2RXSWL8d21")), structId = Read(B("HYEXSgVvK72")),
            valuePresent = value != null,
            valueType = Value(B("ph4XkcdWi6y")), stringValue = content,
            intValue = Value(B("xhyXky634Kl")), boolValue = Value(B("mgbXk3PAHxj")),
            floatValue = Value(B("F2xXkzqKsxa")),
            storage = "existing-wrapper-fields;null-means-unmaterialized"
        };
    }

    (ClientScriptRow Script, object[] Editable, object[] Snapshot, object Manager) CheckClientVariableProbe()
    {
        var (probe, rows, manager) = CheckClientScriptProbe();
        if (!probe.CreateSpent || probe.DeleteSpent || rows.Count != 1 || probe.Target == null ||
            rows[0].Id != probe.Target.Id || !ReferenceEquals(rows[0].Model, probe.Target.Model))
            throw new InvalidOperationException("CLIENT_VARIABLE_SCRIPT_NOT_OWNED");
        return (rows[0], ClientVariableList(rows[0].Model, B("UfeX1gd57Hm")),
            ClientVariableList(rows[0].Model, B("A75X1Wi945U")), manager);
    }

    void RequireClientVariableSync(object manager)
    {
        var check = manager.GetType().GetMethod(B("xguXq4Coquc"), Fields)
            ?? throw new InvalidOperationException("CLIENT_VARIABLE_SYNC_GUARD_MISSING");
        if (check.Invoke(manager, new object[] { false }) is not true)
            throw new InvalidOperationException("CLIENT_VARIABLE_SYNC_NOT_READY");
    }

    public object InspectClientScriptVariablesProbe()
    {
        var (script, editable, snapshot, _) = CheckClientVariableProbe();
        return new
        {
            ok = true, status = "client-script-variable-editor-observation",
            resourceId = script.Id, addInvoked = clientVariableAddSpent,
            deleteInvoked = clientVariableDeleteSpent, count = editable.Length,
            items = editable.Select(ClientVariableView).ToArray(),
            snapshotCount = snapshot.Length, snapshotItems = snapshot.Select(ClientVariableView).ToArray(),
            ownCreatedReferencePresent = clientVariableTarget != null && editable.Any(x => ReferenceEquals(x, clientVariableTarget)),
            gameConfirmed = false, saved = false
        };
    }

    public object AddClientScriptVariableProbe() => AddClientScriptVariableWithTypeProbe(9);
    public object AddClientScriptIntVariableProbe() => AddClientScriptVariableWithTypeProbe(3);

    object AddClientScriptVariableWithTypeProbe(int clientType)
    {
        if (clientType != 3 && clientType != 9) throw new InvalidOperationException("CLIENT_VARIABLE_TYPE_NOT_ALLOWED");
        var (script, editable, snapshot, manager) = CheckClientVariableProbe();
        if (clientVariableAddSpent || clientVariableDeleteSpent || editable.Length != 0 || snapshot.Length != 0)
            throw new InvalidOperationException("CLIENT_VARIABLE_ADD_REFUSED");
        RequireClientVariableSync(manager);
        var enumType = Editor().GetType(B("pla638ZlJEYJ8MDaT8Rn.EOWvASZlCDk3Q1lb3hbD"), true)!;
        var method = script.Model.GetType().GetMethod(B("MAGX1QT9xWK"), Fields)
            ?? throw new InvalidOperationException("CLIENT_VARIABLE_CREATE_METHOD_MISSING");
        // Official dropdown: Int32=3; its first/default entry is String=9.
        var selectedType = Enum.ToObject(enumType, clientType);
        clientVariableAddSpent = true;
        method.Invoke(script.Model, new object?[] { selectedType, 1, null });
        var after = ClientVariableList(script.Model, B("UfeX1gd57Hm"));
        if (after.Length != 1) throw new InvalidOperationException("CLIENT_VARIABLE_CREATE_NOT_OBSERVED");
        if (Convert.ToInt32(ClientVariableStored(after[0], B("UH5X1FwNVD4"))) != clientType)
            throw new InvalidOperationException("CLIENT_VARIABLE_CREATED_TYPE_MISMATCH");
        clientVariableTarget = after[0];
        clientVariableExpected = JsonSerializer.Serialize(ClientVariableView(after[0]));
        return new
        {
            ok = true, status = "client-script-variable-add-invoked-not-game-confirmed",
            resourceId = script.Id, editorObserved = true,
            item = ClientVariableView(after[0]), gameConfirmed = false, saved = false
        };
    }

    public object ResetClientScriptVariableTypeProbe()
    {
        var (script, editable, _, manager) = CheckClientVariableProbe();
        if (!clientVariableAddSpent || clientVariableDeleteSpent || clientVariableResetSpent ||
            clientVariableTarget == null || editable.Length != 1 || !ReferenceEquals(editable[0], clientVariableTarget) ||
            JsonSerializer.Serialize(ClientVariableView(editable[0])) != clientVariableExpected ||
            Convert.ToInt32(ClientVariableStored(editable[0], B("UH5X1FwNVD4"))) != 3)
            throw new InvalidOperationException("CLIENT_VARIABLE_RESET_REFUSED");
        RequireClientVariableSync(manager);
        var clipboard = script.Model.GetType().GetField(B("g4UX1bRivIH"), BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new InvalidOperationException("CLIENT_VARIABLE_CLIPBOARD_FIELD_MISSING");
        if (clipboard.GetValue(null) != null) throw new InvalidOperationException("CLIENT_VARIABLE_FOREIGN_CLIPBOARD");
        var beforeId = ClientVariableStored(editable[0], B("JaKXSlYOGFw"));
        var beforeName = ClientVariableStored(editable[0], B("MyhXSfcDunk"));
        var method = script.Model.GetType().GetMethod(B("lt4X1GTI1j3"), Fields)
            ?? throw new InvalidOperationException("CLIENT_VARIABLE_RESET_METHOD_MISSING");
        clientVariableResetSpent = true;
        method.Invoke(script.Model, new object?[] { 0, null });
        var after = ClientVariableList(script.Model, B("UfeX1gd57Hm"));
        if (after.Length != 1 || !ReferenceEquals(after[0], clientVariableTarget) ||
            !Equals(beforeId, ClientVariableStored(after[0], B("JaKXSlYOGFw"))) ||
            !Equals(beforeName, ClientVariableStored(after[0], B("MyhXSfcDunk"))) ||
            Convert.ToInt32(ClientVariableStored(after[0], B("UH5X1FwNVD4"))) != 9)
            throw new InvalidOperationException("CLIENT_VARIABLE_RESET_NOT_OBSERVED");
        clientVariableExpected = JsonSerializer.Serialize(ClientVariableView(after[0]));
        return new { ok = true, status = "client-script-variable-type-reset-invoked-not-game-confirmed",
            resourceId = script.Id, editorObserved = true, item = ClientVariableView(after[0]), gameConfirmed = false, saved = false };
    }

    public object DeleteClientScriptVariableProbe()
    {
        var (script, editable, _, manager) = CheckClientVariableProbe();
        if (!clientVariableAddSpent || clientVariableDeleteSpent || clientVariableTarget == null ||
            editable.Length != 1 || !ReferenceEquals(editable[0], clientVariableTarget) ||
            JsonSerializer.Serialize(ClientVariableView(editable[0])) != clientVariableExpected)
            throw new InvalidOperationException("CLIENT_VARIABLE_DELETE_REFUSED");
        RequireClientVariableSync(manager);
        var method = script.Model.GetType().GetMethod(B("DppX1qo953h"), Fields)
            ?? throw new InvalidOperationException("CLIENT_VARIABLE_DELETE_METHOD_MISSING");
        clientVariableDeleteSpent = true;
        method.Invoke(script.Model, new object?[] { 0, null });
        var after = ClientVariableList(script.Model, B("UfeX1gd57Hm"));
        return new
        {
            ok = true, status = "client-script-variable-delete-invoked-not-game-confirmed",
            resourceId = script.Id, editorObserved = after.Length == 0, count = after.Length,
            gameConfirmed = false, saved = false
        };
    }
}
