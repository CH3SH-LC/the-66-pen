"""Fixed reopen-current dispatch classification. No business acceptance and no process access."""
import re

def require(value,reason):
    if not value:raise ValueError(reason)

def dispatch_result(*,request_id,native_receipt_sha256,preflight_passed,call_attempted,call_returned,
                    call_exception_code,hook_cleanup_verified):
    require(type(request_id) is str and re.fullmatch('[0-9a-f]{32}',request_id),'REOPEN_REQUEST_ID')
    require(type(native_receipt_sha256) is str and re.fullmatch('[0-9a-f]{64}',native_receipt_sha256),'REOPEN_RECEIPT_HASH')
    for value in (preflight_passed,call_attempted,call_returned,hook_cleanup_verified):
        require(type(value) is bool,'REOPEN_LITERAL_BOOLEAN')
    require(type(call_exception_code) is int and 0<=call_exception_code<2**32,'REOPEN_EXCEPTION_CODE')
    require(not call_returned or call_attempted,'REOPEN_RETURN_WITHOUT_CALL')
    require(not call_attempted or preflight_passed,'REOPEN_CALL_WITHOUT_PREFLIGHT')
    require(not call_returned or call_exception_code==0,'REOPEN_RETURN_WITH_EXCEPTION')
    # ok reports a validated dispatch receipt only. It never reports a completed reopen.
    returned=call_attempted and call_returned and call_exception_code==0
    status=('dispatch-returned-business-pending' if returned else
            'dispatch-uncertain-business-pending' if call_attempted else 'dispatch-refused-no-call')
    return {'ok':returned and hook_cleanup_verified,'action':'reopen-current','requestId':request_id,
            'nativeReceiptSha256':native_receipt_sha256,'preflightPassed':preflight_passed,
            'nativeCallAttempted':call_attempted,'nativeCallReturned':call_returned,
            'callExceptionCode':call_exception_code,'hookCleanupVerified':hook_cleanup_verified,
            'status':status,'businessPending':True,'businessVerified':False,'reopenVerified':False,
            'persistenceVerified':False,'outcomeUncertain':not returned or not hook_cleanup_verified,
            'retryAttempted':False,'safeToRelease':False,'cleanupVerified':False}

def helper_pending_inspect_allowed(canonical,pending):
    """Client precheck only. Helper must repeat against its own immutable lease and file hash."""
    return (type(canonical) is dict and set(canonical)=={'kind','action','sessionPath','levelId'} and
            canonical['kind']=='native-scene' and canonical['action']=='inspect' and
            type(canonical['levelId']) is int and canonical['levelId']==1073741840 and
            type(pending) is dict and pending.get('action')=='reopen-current' and
            pending.get('levelId')==1073741840 and pending.get('hookCleanupVerified') is True and
            pending.get('sessionPath')==canonical['sessionPath'] and
            type(pending.get('requestId')) is str and re.fullmatch('[0-9a-f]{32}',pending['requestId']) is not None)
