using System;
using System.Collections;
using System.Collections.Generic;
using System.Linq;
using System.Reflection;
using System.Text.Json;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    // Native 7.1 evidence: YMt9KPX9... IsAXkEIL1c9 initializes storage 7 with
    // exactly three storage-4 children in `values`. fPp/q6c/HXc select 0/1/2;
    // XqO/TPX/Xhc return each child's float wrapper. The existing registered
    // QkpX9zVTwV4/RlFXkWDa66t pair is the actual native setter/getter. We use
    // those setters, never mutate private backing fields or imported protobuf.
    // Declared server type 12 and editable storage 7 are different domains.
    static float[] AuthorVectorPayload(JsonElement payload)
    {
        if(payload.ValueKind!=JsonValueKind.Object || payload.EnumerateObject().Count()!=1 ||
           !payload.TryGetProperty("vector3",out var v) || v.ValueKind!=JsonValueKind.Array || v.GetArrayLength()!=3)
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_INVALID");
        var result=new float[3];
        for(int i=0;i<3;i++) {
            if(v[i].ValueKind!=JsonValueKind.Number || !v[i].TryGetDouble(out var n) ||
               !double.IsFinite(n) || Math.Abs(n)>1e9)
                throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_INVALID:"+i);
            result[i]=(float)n;
        }
        return result;
    }

    void AuthorRequireVectorDeclaration(List<Resource> resources,uint definitionId,uint[] category,int kind,int index)
    {
        var declared=AuthorDeclaredPins(resources,definitionId,category);
        if(kind!=3 || !declared.TryGetValue((kind,index),out var pin))
            throw new InvalidOperationException("AUTHOR_VALUE_PORT_UNKNOWN:"+kind+":"+index);
        if(pin.TypeId!=0 && pin.TypeId!=12)
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_DECLARATION_MISMATCH:"+pin.TypeId);
    }

    object[] AuthorVectorChildren(object vector)
    {
        if(AuthorStorageKind(vector)!=7)
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_STORAGE_MISMATCH");
        var property=vector.GetType().GetProperty("values",Fields);
        if(property==null || !property.CanRead || property.GetIndexParameters().Length!=0 ||
           property.GetValue(vector) is not IEnumerable collection)
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_CHILDREN_UNAVAILABLE");
        // Bound enumeration even on an unexpected native implementation. No
        // constructor/append/clear runs during preflight or read-only slots.
        var children=collection.Cast<object>().Take(4).ToArray();
        if(children.Length!=3 || children.Any(c=>c==null) ||
           ReferenceEquals(children[0],children[1]) || ReferenceEquals(children[0],children[2]) ||
           ReferenceEquals(children[1],children[2]))
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_CHILDREN_INVALID");
        foreach(var child in children) {
            if(child.GetType()!=vector.GetType() || AuthorStorageKind(child)!=4)
                throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_AXIS_STORAGE_MISMATCH");
            AuthorPreflightLeaf(child.GetType(),4,JsonSerializer.SerializeToElement(new { @float=0f }),"float");
            var getter=child.GetType().GetMethod(B("ngMKKCVBuMA"),Fields)!;
            if(getter.ReturnType.GetProperty("Value")?.PropertyType!=typeof(float))
                throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_AXIS_GETTER_SIGNATURE");
        }
        return children;
    }

    float AuthorReadVectorAxis(object axis)
    {
        var wrapper=axis.GetType().GetMethod(B("ngMKKCVBuMA"),Fields)!.Invoke(axis,null)
            ?? throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_AXIS_NULL");
        if(wrapper.GetType().GetProperty("Value")!.GetValue(wrapper) is not float value || !float.IsFinite(value))
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_AXIS_NONFINITE");
        return value;
    }

    object AuthorReadVector3(object vector)
    {
        var children=AuthorVectorChildren(vector);
        var axes=children.Select(AuthorReadVectorAxis).ToArray();
        return new {xyz=axes,float32Bits=axes.Select(BitConverter.SingleToUInt32Bits).ToArray()};
    }

    // This production algorithm is also used by isolated tests with delegates.
    // All three native accessors are preflighted before entry. A later failure
    // is not rolled back/retried: the outer single-use mutation claim remains.
    static float[] AuthorRunVectorWrite(float[] wanted,Action<int,float> write,Func<int,float> read)
    {
        if(wanted.Length!=3 || wanted.Any(x=>!float.IsFinite(x) || Math.Abs(x)>1e9f))
            throw new InvalidOperationException("AUTHOR_VALUE_VECTOR3_INVALID");
        for(int i=0;i<3;i++) write(i,wanted[i]);
        var result=new float[3];
        for(int i=0;i<3;i++) {
            result[i]=read(i);
            if(BitConverter.SingleToInt32Bits(result[i])!=BitConverter.SingleToInt32Bits(wanted[i]))
                throw new InvalidOperationException("AUTHOR_VALUE_READBACK_MISMATCH:vector3:"+i);
        }
        return result;
    }

    object AuthorWriteVector3(object vector,JsonElement payload)
    {
        var wanted=AuthorVectorPayload(payload);
        var children=AuthorVectorChildren(vector);
        var setter=children[0].GetType().GetMethod(B("SH7KKvk8cxe"),Fields)!;
        var axes=AuthorRunVectorWrite(wanted,
            (i,value)=>setter.Invoke(children[i],new object?[]{value,null}),
            i=>AuthorReadVectorAxis(children[i]));
        return new {xyz=axes,float32Bits=axes.Select(BitConverter.SingleToUInt32Bits).ToArray()};
    }
}
