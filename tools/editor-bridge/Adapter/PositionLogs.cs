using System;
using System.Collections.Generic;
using System.Linq;

namespace Miliastra.EditorBridge;

internal sealed partial class EditorAdapter
{
    readonly List<object> positionPrints=new();
    int ownPositionRecordCount;
    int positionTextRejectedCount;
    readonly Dictionary<string,int> positionBodyTypes=new();
    object PositionCaptureEvidence()=>new {ownPositionRecordCount,positionTextRejectedCount,
        bodyTypes=positionBodyTypes,retainedPrints=positionPrints.Count,runtimePositionParsed=false};
    void CapturePositionPrint(object value)
    {
        if(positionPrints.Count>=32 || value.GetType().FullName!=B("HWUYakaS2uEVNVbKRrtc.fRTMHcaSSKjG5j3IhYLD"))return;
        // Same native record shape as the audit capture: require an explicit
        // PositionGraphName in one of the three known name fields, then the body.
        var type=value.GetType();
        if(!new[]{B("evca2Fc2YBM"),B("Dsva2frS2bQ"),B("IZYa2chZI6A")}.Any(f=>(type.GetField(f,Fields)?.GetValue(value) as string)==PositionGraphName))return;
        ownPositionRecordCount++;
        var body=type.GetField(B("vqqa2GmktMW"),Fields)?.GetValue(value);
        var bodyType=body?.GetType().FullName??"null";
        if(positionBodyTypes.Count<16 || positionBodyTypes.ContainsKey(bodyType))
            positionBodyTypes[bodyType]=positionBodyTypes.GetValueOrDefault(bodyType)+1;
        if(body?.GetType().FullName!=B("L0sGe2atmKXS2diGMArU.wihQ1xataDGHleutr4mB"))return;
        var text=body.GetType().GetField(B("wmmat7vdE8l"),Fields)?.GetValue(body) as string;
        if(text==PositionMarker || IsBoundedNumericVector(text))
            positionPrints.Add(new {observedUtc=DateTime.UtcNow,printedText=text,graphName=PositionGraphName,runtimePositionParsed=false});
        else positionTextRejectedCount++;
    }
    static bool IsBoundedNumericVector(string? text)
    {
        // Shape gate only. The printed format is unverified, so this admits digits
        // and vector punctuation while rejecting every other letter (NaN, Infinity,
        // NUL and any other text) and requiring at least one digit.
        if(string.IsNullOrEmpty(text) || text.Length>128)return false;
        var digit=false;
        foreach(var c in text)
        {
            if(c>='0' && c<='9'){digit=true;continue;}
            if(c=='+' || c=='-' || c=='.' || c==',' || c==';' || c=='(' || c==')' || c=='[' || c==']' || c=='e' || c=='E' || char.IsWhiteSpace(c))continue;
            return false;
        }
        return digit;
    }
}
