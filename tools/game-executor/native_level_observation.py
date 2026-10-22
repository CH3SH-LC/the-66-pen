"""Pinned pure-memory reproduction of the LEVEL default-branch predicates."""
from pathlib import Path
import json
import native_profiles as profiles
LEVEL_PROFILE=Path(__file__).with_name('profiles')/'genshin-cn-7.1.0-level-observation.json'
LEVEL_PROFILE_SHA256='cda958d31085dfb4dadf8b1f7416ffbdf36516aef1d9f33d8f3ee739cfcde80b'
def load_profile():
    profiles.require(profiles.sha256(LEVEL_PROFILE)==LEVEL_PROFILE_SHA256,'LEVEL_PROFILE_SOURCE_HASH_MISMATCH')
    p=json.loads(LEVEL_PROFILE.read_text());base=profiles.load_profile()
    profiles.require(p['readonlyProfileId']==base['profileId'] and p['imageSha256']==base['image']['sha256'],'LEVEL_PROFILE_BINDING')
    return p
