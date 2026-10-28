"""Run the completed source module's offline batch and preserve its raw output."""
import argparse,datetime,io,json,os,unittest
from reference_cli import project_path,write_json,digest
from regional_registration import SOURCE,relative


def run(package,out):
    if not out.is_relative_to(SOURCE) or out.exists():raise ValueError('New owned batch receipt directory required')
    if not (package/'PACKAGE.json').is_file():raise ValueError('Frozen source package required before batch')
    os.environ['MONDSTADT_NATIVE_PACKAGE']=str(package);out.mkdir(parents=True);stream=io.StringIO()
    suite=unittest.TestLoader().loadTestsFromNames(['test_native_source_reference','test_native_frame_reference'])
    result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite);text=stream.getvalue();(out/'unittest.txt').write_text(text,encoding='utf8')
    receipt={'schema':1,'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'package':relative(package/'PACKAGE.json'),'packageSha256':digest(package/'PACKAGE.json'),
        'testsRun':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'successful':result.wasSuccessful(),
        'rawOutput':relative(out/'unittest.txt'),'rawOutputSha256':digest(out/'unittest.txt'),'gameProcessAccess':False,'installationWrites':False,'desktopAccess':False,
        'acceptanceBoundary':'Source extraction/coordinates/consumer behavior only; no editor import, save, collision or gameplay acceptance.'}
    write_json(out/'receipt.json',receipt);print(text);print(json.dumps(receipt));return result.wasSuccessful()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',required=True);p.add_argument('--out',required=True);a=p.parse_args();raise SystemExit(0 if run(project_path(a.package),project_path(a.out)) else 1)
