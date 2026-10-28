"""Single offline batch for the completed city correspondence/index module."""
import argparse,datetime,io,json,os,unittest
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def run(package,index_audit,out):
    if out.exists() or not out.is_relative_to(SOURCE):
        raise ValueError('New owned batch directory required')
    if not (package/'PACKAGE.json').exists() or not (index_audit/'PACKAGE.json').exists():
        raise ValueError('Both complete output packages required before testing')
    os.environ['CITY_SOURCE_PACKAGE']=str(package)
    os.environ['CITY_INDEX_AUDIT']=str(index_audit)
    suite=unittest.TestLoader().loadTestsFromName('test_city_source_correspondence')
    out.mkdir(parents=True);stream=io.StringIO()
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    (out/'unittest.txt').write_text(stream.getvalue(),encoding='utf8')
    receipt={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'sourcePackage':relative(package/'PACKAGE.json'),'sourcePackageSha256':digest(package/'PACKAGE.json'),
        'indexAuditPackage':relative(index_audit/'PACKAGE.json'),'indexAuditPackageSha256':digest(index_audit/'PACKAGE.json'),
        'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
        'successful':result.wasSuccessful(),'rawOutput':relative(out/'unittest.txt'),
        'rawOutputSha256':digest(out/'unittest.txt'),'gameProcessAccess':False,'desktopAccess':False,
        'installationWrites':False,'scope':'source module only, not city regeneration/editor import/collision/gameplay acceptance'}
    write_json(out/'receipt.json',receipt)
    print(stream.getvalue());print(json.dumps(receipt));return result.wasSuccessful()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',required=True);p.add_argument('--index-audit',required=True);p.add_argument('--out',required=True)
    a=p.parse_args()
    raise SystemExit(0 if run(project_path(a.package),project_path(a.index_audit),project_path(a.out)) else 1)
